# Contract: RAG Evaluation Pipeline

## Interfaces

### Lambda: parse-eval-results

The core Lambda function that parses Bedrock evaluation output and produces a threshold verdict.

```python
# evaluation/lambdas/parse_eval_results/handler.py

import json
import boto3
from typing import Any

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Parses Bedrock evaluation job results and compares against thresholds.

    Input event:
    {
        "retrieval_only_job_arn": "arn:aws:bedrock:us-east-2:...:evaluation-job/...",
        "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:...:evaluation-job/...",
        "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json"
    }

    Returns:
    {
        "passed": bool,
        "results": {
            "<metric_name>": {
                "score": float,
                "threshold": float,
                "passed": bool
            },
            ...
        },
        "failed_metrics": ["<metric_name>", ...]
    }
    """
    ...


def get_evaluation_output_s3_uri(bedrock_client: Any, job_arn: str) -> str:
    """Call GetEvaluationJob and extract the output S3 URI."""
    ...


def read_s3_json(s3_client: Any, s3_uri: str) -> dict[str, Any]:
    """Parse an s3://bucket/key URI and read the JSON content."""
    ...


def extract_metric_scores(eval_results: dict[str, Any]) -> dict[str, float]:
    """Extract per-metric average scores from the Bedrock evaluation results JSON."""
    ...


def compare_against_thresholds(
    scores: dict[str, float],
    thresholds: dict[str, float]
) -> dict[str, Any]:
    """
    Compare each metric score against its threshold.

    Returns:
    {
        "passed": bool,
        "results": {metric: {"score": float, "threshold": float, "passed": bool}},
        "failed_metrics": [str]
    }
    """
    ...
```

### Lambda: start-eval-job

Lambda that creates a Bedrock evaluation job for a given evaluation type.

```python
# evaluation/lambdas/start_eval_job/handler.py

import json
import boto3
from typing import Any

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Starts a Bedrock Knowledge Base evaluation job.

    Input event:
    {
        "eval_type": "RETRIEVAL_ONLY" | "RETRIEVE_AND_GENERATE",
        "knowledge_base_id": "string",
        "eval_config": {
            "dataset_s3_uri": "s3://...",
            "output_s3_uri": "s3://...",
            "role_arn": "arn:aws:iam::...:role/...",
            "model_id": "string"  # only for RETRIEVE_AND_GENERATE
        }
    }

    Returns:
    {
        "job_arn": "arn:aws:bedrock:...:evaluation-job/..."
    }
    """
    ...
```

### Lambda: check-eval-status

Lambda that checks the status of a Bedrock evaluation job (used in the polling loop).

```python
# evaluation/lambdas/check_eval_status/handler.py

import json
import boto3
from typing import Any

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Checks the status of a Bedrock evaluation job.

    Input event:
    {
        "job_arn": "arn:aws:bedrock:...:evaluation-job/..."
    }

    Returns:
    {
        "job_arn": "string",
        "status": "IN_PROGRESS" | "COMPLETED" | "FAILED" | "STOPPING" | "STOPPED",
        "completed": bool
    }
    """
    ...
```

### Data Models

#### Thresholds Configuration (S3 JSON file)

```json
{
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
```

#### Verdict Output (parse-eval-results Lambda response)

```json
{
    "passed": false,
    "results": {
        "context_relevance": {"score": 0.85, "threshold": 0.78, "passed": true},
        "context_coverage": {"score": 0.80, "threshold": 0.75, "passed": true},
        "faithfulness": {"score": 0.71, "threshold": 0.82, "passed": false},
        "correctness": {"score": 0.81, "threshold": 0.78, "passed": true},
        "completeness": {"score": 0.76, "threshold": 0.72, "passed": true},
        "helpfulness": {"score": 0.75, "threshold": 0.73, "passed": true},
        "logical_coherence": {"score": 0.80, "threshold": 0.78, "passed": true}
    },
    "failed_metrics": ["faithfulness"]
}
```

### Step Functions State Machine

The state machine definition (in ASL within the SAM template) orchestrates:

```
                    Start
                      |
              [Parallel Branch]
              /                \
    [Retrieval-Only]    [Retrieve-and-Generate]
    StartEvalJob           StartEvalJob
         |                      |
    WaitForJob             WaitForJob
    (poll loop)            (poll loop)
         |                      |
    CheckStatus            CheckStatus
         |                      |
    IsComplete?            IsComplete?
      /     \                /     \
   Yes      No(wait)      Yes     No(wait)
              \                     \
             [loop back]          [loop back]
              \                /
               \              /
                [Parallel End]
                      |
               ParseResults
                      |
               ThresholdCheck
                /          \
         Passed?         Failed?
            |                |
      NotifySuccess    NotifyFailure
           |                |
          End              End
```

### State Changes
- This feature does not modify the existing LangGraph application state (`GraphState`).
- All state is managed within the Step Functions execution context.
- Evaluation results and thresholds live in S3 (external state).

## Behavior Guarantees
1. The parse-eval-results Lambda will always return a complete verdict covering all metrics present in the thresholds file.
2. A metric is marked `"passed": true` if and only if `score >= threshold`.
3. The overall `"passed"` field is `true` if and only if all individual metrics passed.
4. If an evaluation job has status `FAILED`, the Step Functions state machine will transition to the failure notification path.
5. The polling loop will wait 60 seconds between status checks and will timeout after a configurable maximum number of iterations (default: 60, i.e., ~1 hour).
6. SNS notifications will include the full verdict JSON in the message body.
7. EventBridge rules will only trigger the pipeline for the configured Knowledge Base ID.

## Error Handling Contract
| Error Condition | Behavior | User Impact |
|---|---|---|
| Bedrock `GetEvaluationJob` returns error | Lambda raises exception, Step Functions catches and routes to NotifyFailure | SNS failure notification with error details |
| S3 results file not found or malformed | Lambda raises `ValueError`, Step Functions routes to NotifyFailure | SNS failure notification indicating parse error |
| Thresholds file not found in S3 | Lambda raises `FileNotFoundError`, Step Functions routes to NotifyFailure | SNS failure notification indicating missing thresholds |
| Evaluation job status is `FAILED` | Step Functions choice state routes to NotifyFailure | SNS failure notification with job failure status |
| Polling timeout exceeded | Step Functions choice state routes to NotifyFailure after max iterations | SNS failure notification indicating timeout |
| Lambda timeout (15 min max) | AWS retries based on SAM config; Step Functions catches | SNS failure notification |
| Missing or invalid input event fields | Lambda validates and raises `KeyError`/`ValueError` | Step Functions catches and notifies failure |

## Dependencies
- **Internal**: None. This is a standalone infrastructure component that does not import from `src/`.
- **External (Lambda runtime, no packaging needed)**:
  - `boto3` (included in AWS Lambda Python runtime)
  - `json` (stdlib)
- **Infrastructure**:
  - AWS SAM CLI for deployment
  - AWS CloudFormation (used by SAM)
  - AWS Bedrock (evaluation jobs API)
  - AWS S3 (evaluation results and thresholds)
  - AWS Step Functions
  - AWS SNS
  - AWS EventBridge
  - AWS IAM (roles for Lambda, Step Functions, EventBridge)

## Integration Points
- **S3 bucket**: Must contain evaluation datasets and receive evaluation output. Also stores `baselines/thresholds.json`.
- **Bedrock Knowledge Base**: Referenced by `KNOWLEDGE_BASE_ID`; evaluation jobs target this KB.
- **SNS Topic**: `eval-pipeline-alerts` -- subscribers receive pass/fail notifications.
- **EventBridge**: Listens for Bedrock KB sync events and S3 object put events on prompt template files.
- **IAM**: Lambdas need permissions for `bedrock:GetEvaluationJob`, `bedrock:CreateEvaluationJob`, `s3:GetObject`, `sns:Publish`. Step Functions needs `lambda:InvokeFunction`. EventBridge needs `states:StartExecution`.
