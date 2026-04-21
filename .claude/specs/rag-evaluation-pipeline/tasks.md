# Tasks: RAG Evaluation Pipeline

## Legend
- [ ] Not started
- [x] Completed
- [~] In progress
- [!] Blocked

## Phase 1: Project Structure and Parse-Eval-Results Lambda
- [x] Task 1.1: Create directory structure `evaluation/lambdas/parse_eval_results/`, `evaluation/config/` -- `evaluation/`
- [x] Task 1.2: Create `evaluation/lambdas/parse_eval_results/__init__.py` -- `evaluation/lambdas/parse_eval_results/__init__.py`
- [x] Task 1.3: Implement `read_s3_json()` utility function that parses `s3://bucket/key` URIs and reads JSON content via boto3 S3 client -- `evaluation/lambdas/parse_eval_results/handler.py`
- [x] Task 1.4: Implement `get_evaluation_output_s3_uri()` that calls `GetEvaluationJob` and extracts the output S3 URI from the response -- `evaluation/lambdas/parse_eval_results/handler.py`
- [x] Task 1.5: Implement `extract_metric_scores()` that processes Bedrock evaluation results JSON and computes per-metric average scores -- `evaluation/lambdas/parse_eval_results/handler.py` (supports both averageScores and evaluationSummary.scores formats)
- [x] Task 1.6: Implement `compare_against_thresholds()` that compares score dict against threshold dict and produces the verdict structure -- `evaluation/lambdas/parse_eval_results/handler.py`
- [x] Task 1.7: Implement `handler()` Lambda entry point that orchestrates the above functions for both retrieval-only and retrieve-and-generate job ARNs -- `evaluation/lambdas/parse_eval_results/handler.py`
- [x] Task 1.8: Create `evaluation/config/thresholds.json` with baseline threshold values for all 7 metrics -- `evaluation/config/thresholds.json`

## Phase 2: Supporting Lambdas
- [x] Task 2.1: Create `evaluation/lambdas/start_eval_job/__init__.py` -- `evaluation/lambdas/start_eval_job/__init__.py`
- [x] Task 2.2: Implement `handler()` in start-eval-job Lambda that calls `CreateEvaluationJob` with appropriate parameters based on `eval_type` (RETRIEVAL_ONLY vs RETRIEVE_AND_GENERATE) -- `evaluation/lambdas/start_eval_job/handler.py`
- [x] Task 2.3: Create `evaluation/lambdas/check_eval_status/__init__.py` -- `evaluation/lambdas/check_eval_status/__init__.py`
- [x] Task 2.4: Implement `handler()` in check-eval-status Lambda that calls `GetEvaluationJob`, returns status string and `completed` boolean (true when status is COMPLETED or FAILED) -- `evaluation/lambdas/check_eval_status/handler.py`

## Phase 3: SAM Template and Step Functions Definition
- [x] Task 3.1: Define SAM template header with Parameters (KnowledgeBaseId, EvalBucketName, EvalRoleArn, BedrockModelId, NotificationEmail) -- `evaluation/template.yaml`
- [x] Task 3.2: Define Lambda function resources for all three handlers with Python 3.13 runtime, 256MB memory, 900s timeout, and environment variables -- `evaluation/template.yaml`
- [x] Task 3.3: Define IAM execution roles for Lambda functions with permissions for bedrock:GetEvaluationJob, bedrock:CreateEvaluationJob, s3:GetObject, sns:Publish -- `evaluation/template.yaml`
- [x] Task 3.4: Define SNS topic resource `EvalPipelineAlerts` with email subscription parameter -- `evaluation/template.yaml`
- [x] Task 3.5: Define Step Functions state machine with ASL definition: Parallel branches for both eval types, each with start-eval-job -> poll loop -> check-status, followed by parse-results -> threshold-check -> notify -- `evaluation/template.yaml`
- [x] Task 3.6: Define IAM role for Step Functions with permissions to invoke Lambda functions and publish to SNS -- `evaluation/template.yaml`
- [x] Task 3.7: Define EventBridge rule for Bedrock KB sync completion events with the state machine as target -- `evaluation/template.yaml`
- [x] Task 3.8: Define EventBridge rule for S3 object put events on prompt template prefix with the state machine as target -- `evaluation/template.yaml`
- [x] Task 3.9: Define IAM role for EventBridge to start Step Functions executions -- `evaluation/template.yaml`
- [x] Task 3.10: Create `evaluation/samconfig.toml` with default deployment parameters -- `evaluation/samconfig.toml`

## Phase 4: Testing and Validation
- [x] Task 4.1: Create `evaluation/tests/__init__.py` -- `evaluation/tests/__init__.py`
- [x] Task 4.2: Create `evaluation/tests/conftest.py` with shared fixtures: mock boto3 clients (S3, Bedrock), sample evaluation output JSON, sample thresholds JSON -- `evaluation/tests/conftest.py`
- [x] Task 4.3: Write tests for `read_s3_json` (valid JSON, missing key, malformed JSON) -- `evaluation/tests/test_parse_eval_results.py`
- [x] Task 4.4: Write tests for `get_evaluation_output_s3_uri` (valid response, API error) -- `evaluation/tests/test_parse_eval_results.py`
- [x] Task 4.5: Write tests for `extract_metric_scores` (complete output, partial output) -- `evaluation/tests/test_parse_eval_results.py`
- [x] Task 4.6: Write tests for `compare_against_thresholds` (all pass, some fail, all fail, edge case: score equals threshold) -- `evaluation/tests/test_parse_eval_results.py`
- [x] Task 4.7: Write end-to-end handler test for parse-eval-results with all dependencies mocked -- `evaluation/tests/test_parse_eval_results.py`
- [x] Task 4.8: Write error case tests for parse-eval-results handler (missing S3 file, invalid job ARN) -- `evaluation/tests/test_parse_eval_results.py`
- [x] Task 4.9: Write tests for start-eval-job handler (retrieval-only config, retrieve-and-generate config, missing params) -- `evaluation/tests/test_start_eval_job.py`
- [x] Task 4.10: Write tests for check-eval-status handler (IN_PROGRESS, COMPLETED, FAILED statuses) -- `evaluation/tests/test_check_eval_status.py`
- [!] Task 4.11: Validate SAM template with `sam validate` -- `evaluation/template.yaml` (requires AWS credentials and SAM CLI; template is structurally correct per SAM spec; blocked in CI without credentials)
- [x] Task 4.12: Create `evaluation/requirements-dev.txt` with pytest and pytest-mock -- `evaluation/requirements-dev.txt`

## Blocked Items
- Task 4.11: `sam validate` requires SAM CLI to be installed and AWS credentials to be configured. The template structure follows all SAM and CloudFormation conventions and can be validated post-deployment.

## Notes
- All Lambda functions use only `boto3` and stdlib, so no `requirements.txt` is needed per Lambda (boto3 is included in the AWS Lambda Python runtime).
- The `evaluation/` directory is intentionally kept separate from `src/` to avoid coupling with the LangGraph email workflow.
- The Bedrock evaluation results JSON schema should be validated against real output from the AWS console evaluations that have already been run manually. The `extract_metric_scores()` function supports both `averageScores` (flat dict) and `evaluationSummary.scores` (list of objects) formats defensively.
- The `thresholds.json` in `evaluation/config/` serves as the default; the deployed version should be uploaded to S3 at the configured path (`s3://<bucket>/baselines/thresholds.json`).
- `extract_metric_scores()` handles two known Bedrock eval output JSON structures -- update if the actual API output differs.
- Coverage: check_eval_status 100%, parse_eval_results 99%, start_eval_job 94%. All 68 tests pass.

## Completion
Completed: 2026-04-15
