Here's the complete implementation workflow based on Path B:
Phase 1 — Prepare Your Knowledge Base

Make sure your Knowledge Base is created and synced with your Cellfone SA customer service documents (FAQs, product info, policies, procedures).
Enable model access in Bedrock for your generator model (e.g., Claude Sonnet) and your evaluator/judge model (e.g., Claude Sonnet or Mistral Large). These should be two different models ideally — the judge should be equal or more capable than the generator.
Configure your KB prompt template via the console or SDK. This template mirrors the RAG-specific behavior of your LangGraph prompt — tone, language (Spanish), grounding instructions — but without the orchestration logic (email formatting, structured output, tool routing). This is what Bedrock Evaluations will test.

Phase 2 — Build the Evaluation Dataset

Create a JSONL file with 20-30 test cases. Each line follows the Bedrock format:

json{"conversationTurns": [{"prompt": {"content": [{"text": "¿Cuál es la política de devoluciones para el iPhone 15?"}]}, "referenceResponses": [{"content": [{"text": "La política de devoluciones de Cellfone SA permite devolver el iPhone 15 dentro de los primeros 30 días..."}]}]}]}
{"conversationTurns": [{"prompt": {"content": [{"text": "¿Tienen disponible el Samsung Galaxy S24 en color azul?"}]}, "referenceResponses": [{"content": [{"text": "Sí, el Samsung Galaxy S24 está disponible en azul..."}]}]}]}

Cover these categories in your dataset: typical product inquiries (the happy path), customer complaints that require specific policy knowledge, questions your KB should not be able to answer (out of scope), ambiguous questions that could match multiple documents, and multi-turn conversations if your use case supports them (up to 5 turns per conversation).
The referenceResponses field is your ground truth — the ideal answer a human agent would give. This is required for metrics like Correctness and Completeness. For retrieval-only metrics like Context Coverage, this field tells the evaluator what a complete answer should cover so it can judge whether the retrieved chunks contain enough information.
Upload the file to S3: s3://your-bucket/evaluation-datasets/golden-dataset.jsonl. Enable CORS on the bucket.

Phase 3 — Set Up IAM Permissions

Create an IAM role for evaluation jobs with the following permissions: bedrock:InvokeModel for both the generator and evaluator models, bedrock:Retrieve and bedrock:RetrieveAndGenerate on your Knowledge Base, s3:GetObject on your dataset prefix, and s3:PutObject on your results prefix. You can also let the Bedrock console create this role automatically when you run your first evaluation.
Create a second IAM role for Step Functions (the pipeline orchestrator) with permissions for bedrock:CreateEvaluationJob, bedrock:GetEvaluationJob, lambda:InvokeFunction, sns:Publish, and s3:GetObject on the results bucket.

Phase 4 — Run Your Baseline Evaluation Manually

Go to Bedrock console → Evaluations → Knowledge Bases → Create.
Run a Retrieval Only evaluation first. Select your KB, choose your evaluator model, select the metrics Context Relevance and Context Coverage, point to your JSONL dataset in S3, and specify an output S3 path. This tells you if your KB is retrieving the right chunks.
Run a Retrieve and Generate evaluation. Same setup but now you also select a generator model and enable the generation metrics: Correctness, Completeness, Helpfulness, Logical Coherence, and Faithfulness. This tests whether the model generates good answers from those chunks using your KB prompt template.
Review the results in the console — the radar chart, histograms, and per-question drill-downs. These scores become your baseline.
Store your baseline thresholds in S3 as s3://your-bucket/baselines/thresholds.json:

json{
  "retrieval_only": {
    "context_relevance": 0.78,
    "context_coverage": 0.75
  },
  "retrieve_and_generate": {
    "faithfulness": 0.82,
    "correctness": 0.78,
    "completeness": 0.72,
    "helpfulness": 0.73,
    "logical_coherence": 0.78
  }
}
Set these slightly below your actual baseline scores (2-5% margin) to account for normal variance without triggering false alarms.
Phase 5 — Build the Results Parser Lambda

Create a Lambda function (parse-eval-results) in Python. This function receives the evaluation job ARN, calls GetEvaluationJob to find the output S3 path, reads the results JSON file, extracts per-metric average scores, reads the thresholds from S3, compares each metric against its threshold, and returns a structured verdict:

json{
  "passed": false,
  "results": {
    "faithfulness": {"score": 0.71, "threshold": 0.82, "passed": false},
    "correctness": {"score": 0.85, "threshold": 0.78, "passed": true},
    "completeness": {"score": 0.80, "threshold": 0.72, "passed": true}
  },
  "failed_metrics": ["faithfulness"]
}
Phase 6 — Build the Step Functions Pipeline

Create the state machine with this flow:


Parallel state containing two branches:

Branch 1 — Retrieval evaluation:

CreateRetrievalEvalJob: SDK integration calling bedrock:CreateEvaluationJob with retrieval-only config, your KB ID, evaluator model, dataset URI, and output URI.
WaitForRetrievalJob: Loop — Wait 60 seconds → call bedrock:GetEvaluationJob → if InProgress, loop back; if Completed, exit; if Failed, go to error state.


Branch 2 — Generation evaluation:

CreateGenerationEvalJob: Same but with retrieve-and-generate config, adding the generator model and generation metrics.
WaitForGenerationJob: Same polling loop.




ParseResults: Invoke Lambda with both job ARNs. Lambda reads results from S3, compares against thresholds, returns the verdict.
ThresholdCheck: Choice state. If passed is true → NotifySuccess. If false → NotifyFailure.
NotifySuccess: Publish to SNS with a summary of all scores and "Evaluation passed — safe to deploy."
NotifyFailure: Publish to SNS with which metrics failed, the score vs. threshold delta, and "Deployment blocked — regression detected."

Phase 7 — Set Up Triggers

On KB data source changes: When you re-sync your Knowledge Base (new documents, updated docs), create an EventBridge rule that triggers the Step Functions execution. This catches regressions caused by content changes.
On KB prompt template changes: When you update the prompt template via the SDK, have your deployment script trigger the pipeline immediately after.
On CI/CD push: Add a stage in your CodePipeline or GitHub Actions workflow that triggers the Step Functions execution. This catches regressions from any project change — even if the KB itself didn't change.
Manual trigger: During development, trigger from the CLI with aws stepfunctions start-execution or from the console.

Phase 8 — Set Up SNS Notifications

Create an SNS topic (eval-pipeline-alerts). Subscribe your email and optionally a Slack webhook. The failure notification should include: which metrics regressed, the actual score vs. threshold, the percentage drop, and the evaluation job ARN so you can inspect the details in the Bedrock console.

Phase 9 — Test End-to-End

Green path: Run the pipeline with your current configuration. All metrics should pass the baseline thresholds. Verify you receive the success notification.
Red path — degrade the prompt: Change your KB prompt template to something minimal like "Answer the question: queryquery
query" (removing grounding instructions, language, and tone). Run the pipeline. Faithfulness and helpfulness should drop, and the pipeline should block.

Red path — degrade retrieval: Set numberOfResults to 1 in the evaluation config, or temporarily remove key documents from your KB and re-sync. Run the pipeline. Context coverage and completeness should drop.
Restore everything to its original state and verify the pipeline goes green again.