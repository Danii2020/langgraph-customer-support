# Roadmap: RAG Evaluation Pipeline

## Implementation Phases

### Phase 1: Project Structure and Parse-Eval-Results Lambda
**Goal**: Establish the `evaluation/` directory structure and implement the core results-parsing Lambda.
**Dependencies**: None
**Estimated complexity**: Medium

1. Create `evaluation/` directory at project root with subdirectories for lambdas and config.
2. Create `evaluation/lambdas/parse_eval_results/__init__.py` (empty).
3. Implement `evaluation/lambdas/parse_eval_results/handler.py` with:
   - `read_s3_json()` -- parse S3 URI and read JSON.
   - `get_evaluation_output_s3_uri()` -- call `GetEvaluationJob` to extract output path.
   - `extract_metric_scores()` -- extract per-metric averages from Bedrock eval output.
   - `compare_against_thresholds()` -- compare scores to thresholds, produce verdict.
   - `handler()` -- orchestrate the above, accept both job ARNs, return combined verdict.
4. Create `evaluation/config/thresholds.json` with baseline threshold values.

### Phase 2: Supporting Lambdas (start-eval-job, check-eval-status)
**Goal**: Implement the Lambdas needed by the Step Functions polling loop.
**Dependencies**: Phase 1
**Estimated complexity**: Low

1. Create `evaluation/lambdas/start_eval_job/__init__.py` (empty).
2. Implement `evaluation/lambdas/start_eval_job/handler.py`:
   - Accept evaluation type and config from the event.
   - Call `CreateEvaluationJob` via `boto3`.
   - Return the job ARN.
3. Create `evaluation/lambdas/check_eval_status/__init__.py` (empty).
4. Implement `evaluation/lambdas/check_eval_status/handler.py`:
   - Accept job ARN from the event.
   - Call `GetEvaluationJob` to check status.
   - Return status and a boolean `completed` flag.

### Phase 3: SAM Template and Step Functions Definition
**Goal**: Define all infrastructure as code -- Lambda functions, Step Functions state machine, SNS topic, EventBridge rules, and IAM roles.
**Dependencies**: Phase 2
**Estimated complexity**: High

1. Create `evaluation/template.yaml` (SAM template) with:
   - Parameters for KnowledgeBaseId, EvalBucketName, EvalRoleArn, BedrockModelId, AWS region.
   - Lambda function resources for all three handlers (Python 3.13 runtime, 256MB memory, 900s timeout).
   - SNS topic resource (`EvalPipelineAlerts`).
   - Step Functions state machine resource with ASL definition inline:
     - Parallel state with two branches (retrieval-only, retrieve-and-generate).
     - Each branch: invoke start-eval-job Lambda, then a polling loop (Wait 60s -> invoke check-eval-status -> Choice: completed? -> loop or continue).
     - After parallel: invoke parse-eval-results Lambda.
     - Choice state on `$.passed`: true -> NotifySuccess (SNS Publish), false -> NotifyFailure (SNS Publish).
     - Catch blocks on all Lambda invocations routing to NotifyFailure.
   - EventBridge rule for KB sync completion events targeting the state machine.
   - EventBridge rule for S3 object put events on prompt template paths targeting the state machine.
   - IAM roles for Lambda execution, Step Functions execution, and EventBridge invocation.
2. Create `evaluation/samconfig.toml` with default deployment parameters.

### Phase 4: Testing and Validation
**Goal**: Write unit tests for all Lambda functions and validate the SAM template.
**Dependencies**: Phase 3
**Estimated complexity**: Medium

1. Create `evaluation/tests/__init__.py`.
2. Create `evaluation/tests/test_parse_eval_results.py`:
   - Test `read_s3_json` with mocked S3 client.
   - Test `get_evaluation_output_s3_uri` with mocked Bedrock client.
   - Test `extract_metric_scores` with sample Bedrock eval output.
   - Test `compare_against_thresholds` with passing, failing, and mixed scenarios.
   - Test `handler` end-to-end with all dependencies mocked.
3. Create `evaluation/tests/test_start_eval_job.py`:
   - Test handler with mocked `CreateEvaluationJob`.
   - Test error cases (missing params, API errors).
4. Create `evaluation/tests/test_check_eval_status.py`:
   - Test handler with various job statuses (IN_PROGRESS, COMPLETED, FAILED).
5. Create `evaluation/tests/conftest.py` with shared fixtures (mock S3/Bedrock clients, sample data).
6. Validate SAM template: `sam validate --template evaluation/template.yaml`.
7. Create `evaluation/requirements-dev.txt` with test dependencies (pytest, moto or pytest-mock).

## Risk Assessment
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bedrock evaluation job API response format changes | Low | High | Pin to known API version; add defensive parsing with clear error messages |
| Evaluation jobs take longer than 1 hour to complete | Low | Medium | Make polling timeout configurable via SAM parameter; default 60 iterations x 60s = 1 hour |
| S3 bucket permissions misconfigured | Medium | High | Document required bucket policy in SAM template comments; validate with `sam deploy` |
| Bedrock evaluation output JSON schema is undocumented or varies | Medium | High | Build `extract_metric_scores()` with flexible parsing and comprehensive test coverage against sample outputs |
| Lambda cold start delays in polling loop | Low | Low | Acceptable for async evaluation pipeline; no mitigation needed |
| EventBridge rule matches unintended events | Low | Medium | Use precise event patterns filtering on specific KB ID and S3 prefix |

## File Change Map
- `evaluation/` -- CREATE -- root directory for the evaluation pipeline
- `evaluation/lambdas/parse_eval_results/__init__.py` -- CREATE -- package marker
- `evaluation/lambdas/parse_eval_results/handler.py` -- CREATE -- results parsing and threshold comparison logic
- `evaluation/lambdas/start_eval_job/__init__.py` -- CREATE -- package marker
- `evaluation/lambdas/start_eval_job/handler.py` -- CREATE -- Bedrock evaluation job creation
- `evaluation/lambdas/check_eval_status/__init__.py` -- CREATE -- package marker
- `evaluation/lambdas/check_eval_status/handler.py` -- CREATE -- evaluation job status polling
- `evaluation/config/thresholds.json` -- CREATE -- baseline threshold values
- `evaluation/template.yaml` -- CREATE -- SAM infrastructure-as-code template
- `evaluation/samconfig.toml` -- CREATE -- SAM deployment configuration defaults
- `evaluation/tests/__init__.py` -- CREATE -- test package marker
- `evaluation/tests/conftest.py` -- CREATE -- shared test fixtures
- `evaluation/tests/test_parse_eval_results.py` -- CREATE -- unit tests for parse Lambda
- `evaluation/tests/test_start_eval_job.py` -- CREATE -- unit tests for start-eval-job Lambda
- `evaluation/tests/test_check_eval_status.py` -- CREATE -- unit tests for check-eval-status Lambda
- `evaluation/requirements-dev.txt` -- CREATE -- test dependencies
