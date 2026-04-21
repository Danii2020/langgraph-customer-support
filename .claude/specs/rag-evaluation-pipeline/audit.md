# Audit: RAG Evaluation Pipeline

## Requirements Checklist
| ID | Requirement | Source | Status | Notes |
|---|---|---|---|---|
| R1 | SAM template provisions all resources in a single `sam deploy` | intent.md (Success Criteria) | PENDING | |
| R2 | parse-eval-results Lambda extracts per-metric average scores from Bedrock eval output | intent.md (Success Criteria) | PENDING | |
| R3 | Threshold comparison produces accurate structured verdict | intent.md (Success Criteria) | PENDING | |
| R4 | Step Functions runs retrieval-only and retrieve-and-generate evals in parallel | intent.md (Success Criteria) | PENDING | |
| R5 | SNS notifications sent with meaningful details on success/failure | intent.md (Success Criteria) | PENDING | |
| R6 | EventBridge rules trigger pipeline on KB sync and prompt template changes | intent.md (Success Criteria) | PENDING | |
| R7 | All Lambda functions have unit tests with >= 80% coverage | intent.md (Success Criteria) | PENDING | |
| R8 | No modifications to files under `src/` | intent.md (Non-Goals/Constraints) | PENDING | |
| R9 | Python 3.13 Lambda runtime | intent.md (Constraints) | PENDING | |
| R10 | Works in us-east-2 region | intent.md (Constraints) | PENDING | |

## Contract Compliance
| ID | Contract Item | Status | Verified By |
|---|---|---|---|
| C1 | parse-eval-results handler accepts two job ARNs and thresholds S3 URI | PENDING | |
| C2 | parse-eval-results returns verdict with passed, results, failed_metrics fields | PENDING | |
| C3 | start-eval-job handler accepts eval_type and config, returns job_arn | PENDING | |
| C4 | check-eval-status handler accepts job_arn, returns status and completed flag | PENDING | |
| C5 | Metric passes if and only if score >= threshold | PENDING | |
| C6 | Overall passed is true if and only if all metrics pass | PENDING | |
| C7 | Polling loop waits 60s between checks, max 60 iterations | PENDING | |
| C8 | Failed eval job routes to NotifyFailure | PENDING | |
| C9 | Missing thresholds file raises error routed to NotifyFailure | PENDING | |
| C10 | SNS notifications include full verdict JSON | PENDING | |
| C11 | EventBridge rules filter on specific Knowledge Base ID | PENDING | |
| C12 | Thresholds JSON follows the specified schema with retrieval_only and retrieve_and_generate sections | PENDING | |

## Test Coverage
| ID | Test Description | Status | Test File |
|---|---|---|---|
| T1 | read_s3_json reads and parses JSON from mocked S3 | PENDING | evaluation/tests/test_parse_eval_results.py |
| T2 | get_evaluation_output_s3_uri extracts output path from GetEvaluationJob response | PENDING | evaluation/tests/test_parse_eval_results.py |
| T3 | extract_metric_scores computes averages from Bedrock eval output | PENDING | evaluation/tests/test_parse_eval_results.py |
| T4 | compare_against_thresholds returns correct verdict when all pass | PENDING | evaluation/tests/test_parse_eval_results.py |
| T5 | compare_against_thresholds returns correct verdict when some fail | PENDING | evaluation/tests/test_parse_eval_results.py |
| T6 | compare_against_thresholds returns correct verdict when all fail | PENDING | evaluation/tests/test_parse_eval_results.py |
| T7 | parse-eval-results handler end-to-end with mocked dependencies | PENDING | evaluation/tests/test_parse_eval_results.py |
| T8 | parse-eval-results handler error cases (missing S3 file, bad JSON) | PENDING | evaluation/tests/test_parse_eval_results.py |
| T9 | start-eval-job handler creates retrieval-only job | PENDING | evaluation/tests/test_start_eval_job.py |
| T10 | start-eval-job handler creates retrieve-and-generate job | PENDING | evaluation/tests/test_start_eval_job.py |
| T11 | start-eval-job handler error cases (missing params, API errors) | PENDING | evaluation/tests/test_start_eval_job.py |
| T12 | check-eval-status handler returns IN_PROGRESS with completed=false | PENDING | evaluation/tests/test_check_eval_status.py |
| T13 | check-eval-status handler returns COMPLETED with completed=true | PENDING | evaluation/tests/test_check_eval_status.py |
| T14 | check-eval-status handler returns FAILED with completed=true | PENDING | evaluation/tests/test_check_eval_status.py |
| T15 | SAM template validates successfully | PENDING | manual validation |

## Audit Log
| Date | Auditor | Finding | Severity | Resolution |
|---|---|---|---|---|
| | | | | |
