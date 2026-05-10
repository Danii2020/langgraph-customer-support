# Roadmap: KB Provisioning

## Implementation Phases

### Phase 0: Attendee Pre-flight Documentation
**Goal**: Capture the credential + tooling assumptions in a single place so the workshop facilitator and attendees know what to set up *before* the workshop starts. This is documentation only — no code.
**Dependencies**: None
**Estimated complexity**: Low

1. Draft a "Pre-flight checklist" block (intended for `kb_provisioning/README.md` and the root README's new workshop section). Items:
   - `aws --version` shows AWS CLI v2 (≥ 2.15).
   - `sam --version` shows SAM CLI ≥ 1.100 (S3 Vectors resource support).
   - `aws sts get-caller-identity --region us-east-1` returns a valid `Account` + `Arn`.
   - In the AWS Console, **Bedrock → Model access → Manage model access** has `amazon.titan-embed-text-v2:0` set to **Access granted** in `us-east-1` (or the chosen workshop region).
   - The attendee's IAM principal can create IAM roles, S3 buckets, S3 Vectors resources, Bedrock KB/DataSource, and Lambda functions (see intent.md "Attendee Setup Prerequisites" for the full action list). For personal accounts, `AdministratorAccess` is the simplest grant.
2. Decide whether to ship a `kb_provisioning/scripts/preflight.sh` (or `.py`) that runs all four checks and prints PASS/FAIL. Optional but high-value for workshop UX. If shipped, it should: shell out to `aws sts get-caller-identity`, `aws --version`, `sam --version`; call `bedrock:GetFoundationModelAvailability` for the Titan v2 model in the configured region; exit non-zero if any check fails.
3. Verify: a fresh attendee following only the pre-flight checklist arrives at `sam deploy` with no surprises. Have one teammate dry-run the checklist on a clean machine before the workshop.

### Phase 1: SAM Template Skeleton & Directory Layout
**Goal**: Create the `kb_provisioning/` directory mirroring `evaluation/`'s structure, with a parseable but resource-less `template.yaml`. Verify `sam validate` passes and `sam build` runs to completion.
**Dependencies**: None
**Estimated complexity**: Low

1. Create directories: `kb_provisioning/`, `kb_provisioning/lambdas/`, `kb_provisioning/lambdas/seed_and_ingest/`, `kb_provisioning/scripts/`, `kb_provisioning/tests/`.
2. Create `kb_provisioning/template.yaml` with `AWSTemplateFormatVersion`, `Transform: AWS::Serverless-2016-10-31`, `Description`, the full `Parameters` block from contract.md (9 parameters with defaults), an empty `Resources:` section, and an empty `Outputs:` section. Use the same comment-banner style as `evaluation/template.yaml` (`# ----` separators).
3. Create `kb_provisioning/samconfig.toml` mirroring `evaluation/samconfig.toml`'s top-level shape: `version = 0.1`, `[default.deploy.parameters]` with `stack_name = "kb-provisioning"`, `region = "us-east-1"`, `capabilities = "CAPABILITY_IAM CAPABILITY_NAMED_IAM"`, `confirm_changeset = true`, `resolve_s3 = true`, `disable_rollback = true`, an empty-but-present `parameter_overrides` string, `s3_prefix = "kb-provisioning"`, `[default.build.parameters]` with `use_container = false`, and `[default.global.parameters]` with `region = "us-east-1"`.
4. Create `kb_provisioning/requirements-dev.txt` identical to `evaluation/requirements-dev.txt` (`pytest`, `pytest-mock`, `pytest-cov`).
5. Create `kb_provisioning/lambdas/seed_and_ingest/__init__.py` (empty file, matches `evaluation/lambdas/start_eval_job/__init__.py`).
6. Create `kb_provisioning/tests/__init__.py` (empty).
7. Create `kb_provisioning/lambdas/seed_and_ingest/handler.py` as a stub that returns `{}` so `sam build` can package it.
8. Verify: `sam validate --template kb_provisioning/template.yaml --region us-east-1` exits 0; `cd kb_provisioning && sam build` exits 0.

### Phase 2: IAM Role + Source S3 Bucket + S3 Vectors Bucket & Index
**Goal**: Add the data-plane resources the KB depends on. After this phase the stack deploys but does not yet contain a KB.
**Dependencies**: Phase 1
**Estimated complexity**: Medium

1. Add `Conditions` block to `template.yaml`: `HasSourceBucketName: !Not [!Equals [!Ref SourceBucketName, ""]]`, same for `HasVectorBucketName`, `EnableAutoIngestionCondition: !Equals [!Ref EnableAutoIngestion, "true"]`.
2. Add `SourceBucket :: AWS::S3::Bucket` with `BucketName: !If [HasSourceBucketName, !Ref SourceBucketName, !Sub "${AWS::StackName}-source-${AWS::AccountId}-${AWS::Region}"]`. Enable EventBridge notifications via `NotificationConfiguration: { EventBridgeConfiguration: { EventBridgeEnabled: true } }` (this also satisfies `evaluation/`'s `PromptTemplateChangeRule` precondition for any attendee who later wants to use this bucket for prompts).
3. Add `VectorBucket :: AWS::S3Vectors::VectorBucket` with the conditional `VectorBucketName`.
4. Add `VectorIndex :: AWS::S3Vectors::Index` with `VectorBucketName: !GetAtt VectorBucket.VectorBucketName`, `IndexName: !Ref VectorIndexName`, `Dimension: !Ref EmbeddingDimension`, `DistanceMetric: !Ref DistanceMetric`, `DataType: float32`.
5. Add `KnowledgeBaseRole :: AWS::IAM::Role` with the trust policy and inline policy from contract.md (verify the exact `s3vectors:*` action list against current AWS docs before committing — the action list in contract.md is the brief's recommendation, confirm against IAM service authorization reference).
6. Add stack outputs for `SourceBucketName`, `SourceBucketArn`, `VectorBucketArn`, `IndexArn`, `KnowledgeBaseRoleArn`, `Region` (with `Export.Name: !Sub "${AWS::StackName}-..."`).
7. Verify with a real `sam deploy --guided` against an opt-in workshop AWS account: stack reaches `CREATE_COMPLETE`; manual `aws s3 ls`, `aws s3vectors get-vector-bucket`, `aws iam get-role` confirm the resources.
8. Verify teardown: `sam delete` succeeds (source bucket is empty at this stage so no cleanup Lambda needed yet).

### Phase 3: Bedrock KnowledgeBase + DataSource
**Goal**: Wire the KB on top of the data-plane resources. After this phase the stack creates a KB that is empty (no ingestion yet).
**Dependencies**: Phase 2
**Estimated complexity**: Medium

1. Add `KnowledgeBase :: AWS::Bedrock::KnowledgeBase` exactly per contract.md (`Name`, `RoleArn`, `KnowledgeBaseConfiguration` with `VECTOR` + Titan v2 ARN, `StorageConfiguration` with `S3_VECTORS` + `IndexArn`).
2. Add `KnowledgeBaseDataSource :: AWS::Bedrock::DataSource` with `Name: !Sub "${KnowledgeBaseName}-data-source"`, `KnowledgeBaseId: !Ref KnowledgeBase`, `DataSourceConfiguration.Type: S3`, `S3Configuration.BucketArn: !GetAtt SourceBucket.Arn`, `InclusionPrefixes: [!Ref SourceDataPrefix]`. **Do not** include `VectorIngestionConfiguration` (inherit Bedrock's default chunking).
3. Add stack outputs `KnowledgeBaseId: !Ref KnowledgeBase`, `KnowledgeBaseArn: !GetAtt KnowledgeBase.KnowledgeBaseArn`, `DataSourceId: !GetAtt KnowledgeBaseDataSource.DataSourceId`. All with `Export.Name`.
4. Verify: `sam deploy` succeeds; `aws bedrock-agent get-knowledge-base --knowledge-base-id <output>` returns `status: ACTIVE`; `aws bedrock-agent get-data-source` returns `status: AVAILABLE`. The KB is queryable but empty.
5. Manual smoke test: upload `src/data/policies.txt` to `s3://${SourceBucketName}/data/policies.txt`, run `aws bedrock-agent start-ingestion-job --knowledge-base-id <kb> --data-source-id <ds>`, wait, query the KB via `aws bedrock-agent-runtime retrieve` to confirm vectors land in the index.
6. Verify teardown: `sam delete` succeeds (still no objects in the bucket at this point).

### Phase 4: Seed-and-Ingest Custom Resource Lambda
**Goal**: Make the deploy truly one command — automatically upload the seed files and start ingestion. Also handle the `Delete` lifecycle so `sam delete` doesn't fail on a non-empty bucket.
**Dependencies**: Phase 3
**Estimated complexity**: High

1. Create `kb_provisioning/scripts/prepare_lambda_assets.py`. Copies `src/data/policies.txt` and `src/data/data.txt` into `kb_provisioning/lambdas/seed_and_ingest/seed_data/` so `sam build` packages them with the function. Idempotent. Document running this before `sam build` (or wire it into a `Makefile` target if convenient).
2. Implement `kb_provisioning/lambdas/seed_and_ingest/handler.py` per the contract:
   - `handler(event, context)` dispatches on `event["RequestType"]` (`Create` | `Update` | `Delete`).
   - On `Create`: upload every file in `SEED_DATA_DIR` to `s3://{SourceBucketName}/{SourceDataPrefix}` (preserve filename), then call `bedrock-agent.start_ingestion_job(knowledgeBaseId=..., dataSourceId=...)`. Return the `ingestionJobId` in the response `Data`.
   - On `Update`: compare `event["ResourceProperties"]` to `event["OldResourceProperties"]`; if all tracked keys (`SourceBucketName`, `SourceDataPrefix`, `KnowledgeBaseId`, `DataSourceId`) are unchanged, `SUCCESS` no-op; otherwise re-upload and re-ingest.
   - On `Delete`: empty the source bucket (`list_objects_v2` paginated, `delete_objects` in batches of 1000); do not touch the KB or DataSource (CFN deletes those).
   - All boto3 clients constructed inside the handler (no module-level clients) so unit tests can patch `boto3.client`. Match the style of `evaluation/lambdas/start_eval_job/handler.py`.
   - `send_cfn_response` posts to `event["ResponseURL"]` via `urllib.request`. Wrap the entire handler body in try/except and emit `FAILED` on any exception so CFN doesn't hang.
3. Add `SeedAndIngestFunctionRole :: AWS::IAM::Role` (with `Condition: EnableAutoIngestionCondition`). Trust `lambda.amazonaws.com`. Managed policy `AWSLambdaBasicExecutionRole`. Inline policy with: `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket` on `SourceBucket`; `bedrock:StartIngestionJob` on the KB ARN.
4. Add `SeedAndIngestFunction :: AWS::Serverless::Function` (with `Condition: EnableAutoIngestionCondition`). `Runtime: python3.13`, `Timeout: 900`, `MemorySize: 256`, `CodeUri: lambdas/seed_and_ingest/`, `Handler: handler.handler`, `Role: !GetAtt SeedAndIngestFunctionRole.Arn`. Match the `Globals.Function` block style from `evaluation/template.yaml` — declare a `Globals.Function` with `Runtime: python3.13`, `MemorySize: 256`, `Timeout: 900`, no env vars (this stack doesn't need shared env vars).
5. Add `SeedAndIngestCustomResource :: AWS::CloudFormation::CustomResource` (with `Condition: EnableAutoIngestionCondition`). `ServiceToken: !GetAtt SeedAndIngestFunction.Arn`. Properties: `SourceBucketName`, `SourceDataPrefix`, `KnowledgeBaseId: !Ref KnowledgeBase`, `DataSourceId: !GetAtt KnowledgeBaseDataSource.DataSourceId`, `Region: !Ref AWS::Region`. Add `DependsOn: [SourceBucket, KnowledgeBase, KnowledgeBaseDataSource]`.
6. Verify end-to-end: `python kb_provisioning/scripts/prepare_lambda_assets.py && cd kb_provisioning && sam build && sam deploy --config-file samconfig.toml`. Stack reaches `CREATE_COMPLETE`. Confirm `aws s3 ls s3://${SourceBucketName}/data/` shows both seed files. Confirm `aws bedrock-agent list-ingestion-jobs` shows a `STARTING` or `IN_PROGRESS` job. Wait ~2 minutes; confirm it transitions to `COMPLETE`.
7. Verify idempotency: re-run `sam deploy` with no changes; confirm CFN reports no resource updates and no second ingestion job is started (custom resource sees identical `ResourceProperties`).
8. Verify teardown: `sam delete`; confirm bucket is emptied and stack fully deletes.

### Phase 5: Fallback Script + Workshop-Friendly samconfig defaults
**Goal**: Provide the Option-2 fallback for attendees who hit IAM friction with the custom resource, and lock in workshop-friendly defaults.
**Dependencies**: Phase 4
**Estimated complexity**: Low

1. Create `kb_provisioning/scripts/seed_and_ingest.py`. Standalone CLI that reads stack outputs via `aws cloudformation describe-stacks`, then performs the same upload + `start_ingestion_job` logic as the Lambda. Args: `--stack-name`, `--region`, `--data-dir` (default `src/data/`). Mirror the style of `evaluation/scripts/setup_s3.py` (argparse, boto3, print progress). This script can also be used post-deploy for re-syncing if attendees drop new files.
2. Update `kb_provisioning/samconfig.toml`'s `parameter_overrides` to include all parameters with their defaults explicitly (mirrors `evaluation/samconfig.toml` style — every parameter listed in one quoted string). Leave `SourceBucketName` and `VectorBucketName` empty so the auto-generated globally-unique names are used.
3. Add a top-of-file comment in `samconfig.toml` matching the `evaluation/samconfig.toml` style: usage hint, deploy command, `# Required parameters -- fill these in before deploying.` divider.
4. Verify: a fresh checkout + `cd kb_provisioning && sam build && sam deploy --config-file samconfig.toml --no-confirm-changeset` completes with zero attendee edits to `samconfig.toml`.

### Phase 6: Documentation Updates
**Goal**: Tell attendees what command to run and how to wire the output into the LangGraph app and the eval pipeline.
**Dependencies**: Phase 5
**Estimated complexity**: Low

1. Update root `README.md`: add a new top-level section "Provisioning the Knowledge Base (workshop)" before the "Knowledge base (RAG)" section. Lead with the **Pre-flight checklist** drafted in Phase 0 (AWS CLI v2, SAM CLI ≥ 1.100, `aws sts get-caller-identity` succeeds, Titan v2 model access granted in the Bedrock console). Document the two-step attendee flow: (a) `cd kb_provisioning && sam build && sam deploy --config-file samconfig.toml`; (b) copy `KnowledgeBaseId` output into `.env` as `KNOWLEDGE_BASE_ID` and into `evaluation/samconfig.toml`'s `parameter_overrides`. Mention region alignment requirement (`us-east-1` default; if changed, update `src/agents/bedrock.py` and `evaluation/samconfig.toml`). State explicitly that the stack uses the standard AWS credential chain — no access keys are passed as parameters — and that attendees are expected to have `aws configure` (or `aws sso login`) already done before the workshop.
2. Update `CLAUDE.md`: add `kb_provisioning/` to the "Repository layout" section as project #3. Add a `### Provisioning pipeline (kb_provisioning/)` section to "Commands" with the deploy + teardown commands. Add a brief architecture note under "Architecture" mirroring the `### Evaluation pipeline (evaluation/)` section style.
3. Update `.env.example`: add a comment near `KNOWLEDGE_BASE_ID` noting that this value comes from the `kb_provisioning` stack's `KnowledgeBaseId` output.
4. (Optional) Add a short `kb_provisioning/README.md` covering: prerequisites (model access, AWS CLI, SAM), the deploy command, the two-step copy/paste, the `sam delete` teardown, common errors (region mismatch, model access denied).

### Phase 7: Tests for the Custom Resource Lambda
**Goal**: Lock in the Lambda's behavior with unit tests, following the pattern in `evaluation/tests/`.
**Dependencies**: Phase 4
**Estimated complexity**: Medium

1. Create `kb_provisioning/tests/conftest.py` with `mock_s3_client`, `mock_bedrock_agent_client`, and helper fixtures for synthesizing CFN custom-resource events. Mirror `evaluation/tests/conftest.py`'s `MagicMock` style.
2. Create `kb_provisioning/tests/test_seed_and_ingest.py` using the `importlib.util.spec_from_file_location` loader pattern from `evaluation/tests/test_start_eval_job.py:10-19` so the test can import `handler.py` by absolute path.
3. Test classes:
   - `TestCreateRequest`: uploads happen, ingestion job starts, response data contains `IngestionJobId` and `FilesUploaded`.
   - `TestUpdateRequestNoOp`: identical `ResourceProperties` and `OldResourceProperties` → no S3 calls, no Bedrock calls, response is `SUCCESS`.
   - `TestUpdateRequestWithChanges`: differing `KnowledgeBaseId` → re-upload + re-ingest happen.
   - `TestDeleteRequest`: bucket is emptied (paginated `list_objects_v2` then `delete_objects`), no Bedrock calls.
   - `TestSendCfnResponse`: verifies the JSON body shape and `urllib.request.Request` is constructed with `method="PUT"` against `event["ResponseURL"]`.
   - `TestErrorHandling`: any exception in the handler body triggers a `FAILED` response with the exception message in `Reason`; never raises out of `handler`.
4. Verify coverage: `pytest kb_provisioning/tests/ --cov=kb_provisioning/lambdas/seed_and_ingest --cov-report=term` ≥ 80%.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Titan v2 model access not enabled in attendee's account | Medium | High (stack rollback) | Document as a precondition in README + workshop facilitator script. Provide screenshot of the Bedrock console "Model access" page. |
| `AWS::S3Vectors::*` resources fail in the attendee's region (still rolling out as of 2026-05-09) | Low (we default to `us-east-1`) | High (stack rollback) | Pin `region = "us-east-1"` in `samconfig.toml`'s `[default.global.parameters]`; document in README that other regions are best-effort. |
| Source/vector bucket name collision because two attendees use the same workshop AWS account | Medium | Medium (one of them gets `BucketAlreadyExists`) | Auto-generated names include `${AWS::AccountId}-${AWS::Region}` and `${AWS::StackName}`. Recommend each attendee uses a unique stack name (default `kb-provisioning`; suggest `kb-provisioning-${USER}` if sharing an account). |
| Custom resource Lambda fails to send a response → CFN hangs for 1 hour | Medium | High (workshop slot wasted) | Wrap entire handler in try/except, always send a response. Add a Lambda timeout of 900s (well below CFN's 60-min wait). Test the failure path. |
| `s3vectors:*` action list is incomplete or misnamed → KB ingestion fails with `AccessDenied` | Medium | High (KB never populates) | Phase 2 step 5 explicitly requires verifying actions against the IAM service authorization reference. Iterate on the policy by reading CloudTrail `AccessDenied` events from the first failing deploy. |
| Embedding dimension drift if attendee changes `EmbeddingModelArn` without changing `EmbeddingDimension` | Low (defaults are coherent) | High (KB silently stores wrong-dim vectors, all queries fail) | Document in `samconfig.toml` comments that the two parameters move together. Consider a `Conditions`-based assertion in a future revision. |
| Region mismatch between this stack and `evaluation/` → `KbSyncCompletionRule` never fires, eval pipeline never runs | Medium | Medium (silent failure; eval just looks idle) | Document in README. Both `samconfig.toml` files default to `us-east-1`; the only way to mismatch is to manually change one. |
| Seed Lambda packaging includes the actual `src/data/*.txt` snapshots → updating data requires re-running `prepare_lambda_assets.py` + redeploy | Low | Low | Document the workflow. The fallback script (`scripts/seed_and_ingest.py`) reads from `src/data/` directly so attendees can re-sync without redeploying. |
| `sam delete` fails because the vector bucket has unflushed data | Low (S3 Vectors managed deletion is supposed to handle this) | Medium | Test teardown explicitly. If S3 Vectors requires manual emptying, extend the seed Lambda's `Delete` handler to call `s3vectors:DeleteVectors`. |
| Attendee re-runs `sam deploy` mid-ingestion and triggers a duplicate ingestion job | Low | Low (Bedrock queues / dedupes; second job runs against same data) | Custom resource on `Update` with unchanged properties is a no-op. Document that mid-ingestion redeploys are safe but unnecessary. |

## File Change Map

### CREATE (new files)
- `kb_provisioning/template.yaml` — CREATE — SAM template defining the IAM role, S3 source bucket, S3 Vectors bucket+index, Bedrock KnowledgeBase, Bedrock DataSource, and (conditional) seed-and-ingest custom resource Lambda + role.
- `kb_provisioning/samconfig.toml` — CREATE — SAM deploy config with workshop-friendly defaults pinned to `us-east-1`, with full `parameter_overrides` string.
- `kb_provisioning/requirements-dev.txt` — CREATE — `pytest`, `pytest-mock`, `pytest-cov` (identical to `evaluation/requirements-dev.txt`).
- `kb_provisioning/lambdas/seed_and_ingest/__init__.py` — CREATE — empty package marker.
- `kb_provisioning/lambdas/seed_and_ingest/handler.py` — CREATE — custom resource Lambda implementing `Create` (upload + start ingestion), `Update` (no-op or re-trigger on property change), `Delete` (empty bucket).
- `kb_provisioning/lambdas/seed_and_ingest/seed_data/.gitkeep` — CREATE — keeps the directory present in git; actual `*.txt` snapshots are populated by `prepare_lambda_assets.py` and gitignored (or committed; pick during Phase 4).
- `kb_provisioning/scripts/prepare_lambda_assets.py` — CREATE — copies `src/data/*.txt` into the Lambda's `seed_data/` dir before `sam build`.
- `kb_provisioning/scripts/seed_and_ingest.py` — CREATE — standalone CLI for the `EnableAutoIngestion=false` fallback path and post-deploy re-syncs.
- `kb_provisioning/tests/__init__.py` — CREATE — empty package marker.
- `kb_provisioning/tests/conftest.py` — CREATE — pytest fixtures for mock S3, mock bedrock-agent, and synthetic CFN events.
- `kb_provisioning/tests/test_seed_and_ingest.py` — CREATE — unit tests for the custom resource Lambda.
- `kb_provisioning/README.md` — CREATE (optional, see Phase 6 step 4) — workshop quick start.

### MODIFY (existing files)
- `README.md` — MODIFY — add "Provisioning the Knowledge Base (workshop)" section in front of "Knowledge base (RAG)".
- `CLAUDE.md` — MODIFY — add `kb_provisioning/` as project #3 in "Repository layout"; add deploy commands; add architecture note.
- `.env.example` — MODIFY — add comment by `KNOWLEDGE_BASE_ID` noting it comes from the `kb_provisioning` stack output.
- `.gitignore` — MODIFY (probably) — add `kb_provisioning/.aws-sam/` (matches the existing `evaluation/.aws-sam/` directory which is already implicitly ignored or should be); add `kb_provisioning/lambdas/seed_and_ingest/seed_data/*.txt` if we choose not to commit the seed snapshots.

### UNCHANGED (do not touch)
- `src/**/*.py` — the LangGraph app is untouched.
- `main.py` — unchanged.
- `evaluation/**` — every file in the eval pipeline is unchanged. Cross-stack handoff is human-mediated.
- `requirements.txt` — the seed Lambda only uses boto3 (built into the Lambda runtime); the local fallback script also only needs boto3, which is already pinned at `1.40.26`.
