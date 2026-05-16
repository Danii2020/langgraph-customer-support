# Intent: RAG Evaluation Pipeline

## Problem Statement
The project relies on an Amazon Bedrock Knowledge Base for RAG-powered customer support replies. Currently, there is no automated way to evaluate the quality of retrieval and generation after Knowledge Base syncs or prompt template changes. Evaluation is done manually through the AWS console, which is slow, error-prone, and not repeatable. The team needs a programmatic, event-driven pipeline that runs Bedrock evaluation jobs, parses results, checks them against quality thresholds, and notifies stakeholders of regressions.

## Goals
1. Automate the execution and monitoring of Bedrock Knowledge Base evaluation jobs (both retrieval-only and retrieve-and-generate).
2. Parse evaluation results from S3 and compare per-metric scores against configurable baseline thresholds.
3. Provide pass/fail verdicts with per-metric detail and notify via SNS on success or failure.
4. Trigger the pipeline automatically on Knowledge Base sync events and prompt template changes via EventBridge.
5. Deploy the entire pipeline as infrastructure-as-code using AWS SAM.

## Success Criteria
- [ ] A SAM template provisions all resources (Lambda, Step Functions, SNS, EventBridge rules) in a single `sam deploy`.
- [ ] The parse-eval-results Lambda correctly extracts per-metric average scores from Bedrock evaluation output JSON.
- [ ] Threshold comparison produces an accurate structured verdict (passed/failed per metric, overall pass/fail).
- [ ] Step Functions state machine runs both retrieval-only and retrieve-and-generate evaluations in parallel, waits for completion, then parses and checks results.
- [ ] SNS notifications are sent with meaningful details on pipeline success or failure.
- [ ] EventBridge rules trigger the pipeline on KB sync completion and on prompt template S3 object changes.
- [ ] All Lambda functions have unit tests with at least 80% code coverage.

## Non-Goals
- Creating or configuring the Bedrock Knowledge Base itself (already done manually).
- Creating IAM roles for Bedrock evaluation (already provisioned manually).
- Building a web UI or dashboard for evaluation results.
- Modifying the existing LangGraph email support workflow in `src/`.
- Implementing custom evaluation metrics beyond what Bedrock provides.

## Constraints
- Must use Python 3.13 runtime for Lambda (matching the project's `requires-python = ">=3.13"`).
- Must use `boto3` for all AWS SDK calls (already a project dependency).
- Infrastructure must be defined with AWS SAM (template.yaml) for consistency with typical Bedrock/Lambda workflows.
- Lambda functions must have minimal dependencies (only boto3, which is included in the Lambda runtime).
- The pipeline must work in the `us-east-2` region (the project's configured AWS region).
- Must not modify any files under `src/` -- the evaluation pipeline is a standalone infrastructure component.

## Prior Art
- `src/utils/rag_utils.py` -- existing Knowledge Base integration using `AmazonKnowledgeBasesRetriever` with `KNOWLEDGE_BASE_ID` env var.
- `src/agents/bedrock.py` -- existing `boto3.client("bedrock-runtime")` usage pattern for Bedrock.
- `.env.example` -- established pattern for environment variable configuration (`KNOWLEDGE_BASE_ID`, `AWS_REGION`).
- AWS Bedrock Evaluation Jobs API -- `CreateEvaluationJob`, `GetEvaluationJob` for programmatic evaluation.
