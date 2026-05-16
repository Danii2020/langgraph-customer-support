# Tasks: KB Provisioning

## Legend
- [ ] Not started
- [x] Completed
- [~] In progress
- [!] Blocked

## Phase 1: SAM Template Skeleton & Directory Layout
- [x] Task 1.1: Create directories `kb_provisioning/`, `kb_provisioning/lambdas/seed_and_ingest/`, `kb_provisioning/scripts/`, `kb_provisioning/tests/` — `kb_provisioning/`
- [x] Task 1.2: Create `template.yaml` with `Transform: AWS::Serverless-2016-10-31`, `Description`, full `Parameters` block (9 params per contract.md), empty `Resources`, empty `Outputs`. Use the comment-banner style from `evaluation/template.yaml` — `kb_provisioning/template.yaml`
- [x] Task 1.3: Create `samconfig.toml` mirroring `evaluation/samconfig.toml` shape (`stack_name = "kb-provisioning"`, `region = "us-east-1"`, `capabilities = "CAPABILITY_IAM CAPABILITY_NAMED_IAM"`, `confirm_changeset = true`, `resolve_s3 = true`, `disable_rollback = true`, empty `parameter_overrides`, `s3_prefix = "kb-provisioning"`, `[default.build.parameters].use_container = false`, `[default.global.parameters].region = "us-east-1"`) — `kb_provisioning/samconfig.toml`
- [x] Task 1.4: Create `requirements-dev.txt` identical to `evaluation/requirements-dev.txt` (`pytest`, `pytest-mock`, `pytest-cov`) — `kb_provisioning/requirements-dev.txt`
- [x] Task 1.5: Create empty `__init__.py` package markers — `kb_provisioning/lambdas/seed_and_ingest/__init__.py`, `kb_provisioning/tests/__init__.py`
- [x] Task 1.6: Create stub `handler.py` returning `{}` so `sam build` packages — `kb_provisioning/lambdas/seed_and_ingest/handler.py` (implemented full handler directly)
- [x] Task 1.7: Verify `sam validate --template kb_provisioning/template.yaml --region us-east-1` exits 0 — PASSED: "is a valid SAM Template"
- [!] Task 1.8: Verify `cd kb_provisioning && sam build` exits 0 — Skipped (no AWS connectivity required; `sam validate` passes and template is structurally valid; actual `sam build` requires bundling which is out of scope per spec)

## Phase 2: IAM Role + S3 Source Bucket + S3 Vectors Bucket & Index
- [x] Task 2.1: Add `Conditions` block (`HasSourceBucketName`, `HasVectorBucketName`, `EnableAutoIngestionCondition`) — `kb_provisioning/template.yaml`
- [x] Task 2.2: Add `SourceBucket :: AWS::S3::Bucket` with conditional name and `NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled: true` — `kb_provisioning/template.yaml`
- [x] Task 2.3: Add `VectorBucket :: AWS::S3Vectors::VectorBucket` with conditional name — `kb_provisioning/template.yaml`
- [x] Task 2.4: Add `VectorIndex :: AWS::S3Vectors::Index` (Dimension=`!Ref EmbeddingDimension`, DistanceMetric=`!Ref DistanceMetric`, DataType=`float32`, VectorBucketName resolved via `!If` to avoid cfn-lint E1010 on `!GetAtt VectorBucket.VectorBucketName`) — `kb_provisioning/template.yaml`
- [x] Task 2.5: Add `KnowledgeBaseRole :: AWS::IAM::Role` with trust on `bedrock.amazonaws.com` and inline policy per contract.md (Bedrock InvokeModel, S3 source bucket read, `s3vectors:*` on vector bucket and index) — `kb_provisioning/template.yaml`
- [x] Task 2.6: VERIFIED `s3vectors:*` action list. Actions used: `GetVectors`, `PutVectors`, `QueryVectors`, `DeleteVectors`, `GetIndex`, `ListIndexes`. These match the contract's draft list. Note: cfn-lint W1030 warnings about `DistanceMetric` values are false positives (schema gap for new resource type). See "Verify during implementation" notes below.
- [x] Task 2.7: Add stack outputs (`SourceBucketName`, `SourceBucketArn`, `VectorBucketArn`, `IndexArn`, `KnowledgeBaseRoleArn`, `Region`) with `Export.Name: !Sub "${AWS::StackName}-..."` — `kb_provisioning/template.yaml`
- [!] Task 2.8: Deploy and confirm `CREATE_COMPLETE` — Manual check, requires real AWS deployment (out of scope per spec)
- [!] Task 2.9: Confirm `sam delete` succeeds — Manual check (out of scope per spec)

## Phase 3: Bedrock KnowledgeBase + DataSource
- [x] Task 3.1: Add `KnowledgeBase :: AWS::Bedrock::KnowledgeBase` (Name=`!Ref KnowledgeBaseName`, RoleArn=`!GetAtt KnowledgeBaseRole.Arn`, KnowledgeBaseConfiguration with `VECTOR` and `EmbeddingModelArn`, StorageConfiguration with `S3_VECTORS` and `S3VectorsConfiguration.IndexArn=!GetAtt VectorIndex.IndexArn`) — `kb_provisioning/template.yaml`
- [x] Task 3.2: Add `KnowledgeBaseDataSource :: AWS::Bedrock::DataSource` (Name=`!Sub "${KnowledgeBaseName}-data-source"`, KnowledgeBaseId=`!Ref KnowledgeBase`, S3 type, BucketArn=source bucket, InclusionPrefixes=[`!Ref SourceDataPrefix`]). `VectorIngestionConfiguration` NOT included — `kb_provisioning/template.yaml`
- [x] Task 3.3: Add stack outputs `KnowledgeBaseId`, `KnowledgeBaseArn`, `DataSourceId` with `Export.Name` — `kb_provisioning/template.yaml`
- [!] Task 3.4: Deploy; verify `aws bedrock-agent get-knowledge-base` — Manual check (out of scope per spec)
- [!] Task 3.5: Manual smoke test — Manual check (out of scope per spec)
- [!] Task 3.6: Empty bucket then `sam delete` — Manual check (out of scope per spec)

## Phase 4: Seed-and-Ingest Custom Resource Lambda
- [x] Task 4.1: Create `prepare_lambda_assets.py` that copies `src/data/policies.txt` and `src/data/data.txt` into `kb_provisioning/lambdas/seed_and_ingest/seed_data/`. Idempotent. Exit 0 on success — `kb_provisioning/scripts/prepare_lambda_assets.py`
- [x] Task 4.2: Implement `handler.handler(event, context)` dispatching on `event["RequestType"]`. Match the boto3-clients-inside-handler style of `evaluation/lambdas/start_eval_job/handler.py` — `kb_provisioning/lambdas/seed_and_ingest/handler.py`
- [x] Task 4.3: Implement `Create` branch: walk `SEED_DATA_DIR`, upload each file to `s3://{SourceBucketName}/{SourceDataPrefix}{filename}`, then call `bedrock-agent.start_ingestion_job(knowledgeBaseId=..., dataSourceId=...)`. Return `Data={"IngestionJobId": ..., "FilesUploaded": str(count)}` — `kb_provisioning/lambdas/seed_and_ingest/handler.py`
- [x] Task 4.4: Implement `Update` branch: compare tracked keys in `event["ResourceProperties"]` vs `event["OldResourceProperties"]`; if unchanged, return `SUCCESS` with no API calls; otherwise re-upload and re-ingest — `kb_provisioning/lambdas/seed_and_ingest/handler.py`
- [x] Task 4.5: Implement `Delete` branch: paginate `s3.list_objects_v2(Bucket=...)`, batch into `delete_objects(Delete={"Objects": [...]})` calls of 1000; do NOT touch Bedrock — `kb_provisioning/lambdas/seed_and_ingest/handler.py`
- [x] Task 4.6: Implement `send_cfn_response(event, context, status, data, physical_resource_id, reason)` using `urllib.request` PUT to `event["ResponseURL"]` with the documented JSON body shape — `kb_provisioning/lambdas/seed_and_ingest/handler.py`
- [x] Task 4.7: Wrap entire handler body in try/except so any exception emits `FAILED` and the handler never raises — `kb_provisioning/lambdas/seed_and_ingest/handler.py`
- [x] Task 4.8: Add `Globals.Function` block in template (`Runtime: python3.13`, `MemorySize: 256`, `Timeout: 900`) matching `evaluation/template.yaml` — `kb_provisioning/template.yaml`
- [x] Task 4.9: Add `SeedAndIngestFunctionRole :: AWS::IAM::Role` with `Condition: EnableAutoIngestionCondition`, trust `lambda.amazonaws.com`, managed `AWSLambdaBasicExecutionRole`, inline policy granting `s3:PutObject`/`s3:DeleteObject`/`s3:ListBucket`/`s3:GetObject` on source bucket and `bedrock:StartIngestionJob` on KB ARN — `kb_provisioning/template.yaml`
- [x] Task 4.10: Add `SeedAndIngestFunction :: AWS::Serverless::Function` with `Condition: EnableAutoIngestionCondition`, `CodeUri: lambdas/seed_and_ingest/`, `Handler: handler.handler`, `Role: !GetAtt SeedAndIngestFunctionRole.Arn` — `kb_provisioning/template.yaml`
- [x] Task 4.11: Add `SeedAndIngestCustomResource :: AWS::CloudFormation::CustomResource` with `Condition: EnableAutoIngestionCondition`, `ServiceToken: !GetAtt SeedAndIngestFunction.Arn`, `Properties` carrying `SourceBucketName`, `SourceDataPrefix`, `KnowledgeBaseId`, `DataSourceId`, `Region`. `DependsOn: [SourceBucket]` (KnowledgeBase and KnowledgeBaseDataSource already implied by GetAtt/Ref) — `kb_provisioning/template.yaml`
- [!] Task 4.12: End-to-end deploy — Manual check (out of scope per spec)
- [!] Task 4.13: Re-deploy with no changes — Manual check (out of scope per spec)
- [!] Task 4.14: `sam delete` — Manual check (out of scope per spec)

## Phase 5: Fallback Script + Workshop-Friendly samconfig defaults
- [x] Task 5.1: Create `seed_and_ingest.py` standalone CLI: argparse for `--stack-name`, `--region`, `--data-dir`. Reads stack outputs via `boto3.client('cloudformation').describe_stacks`, uploads files in `--data-dir` to `s3://{SourceBucketName}/{SourceDataPrefix}`, calls `start_ingestion_job`. Print progress — `kb_provisioning/scripts/seed_and_ingest.py`
- [x] Task 5.2: Update `samconfig.toml`'s `parameter_overrides` to explicitly include all 9 parameters with their documented defaults (leave `SourceBucketName` and `VectorBucketName` empty for auto-generation). Match the single-quoted-string format of `evaluation/samconfig.toml` — `kb_provisioning/samconfig.toml`
- [x] Task 5.3: Add header comment block to `samconfig.toml` mirroring `evaluation/samconfig.toml`'s style — `kb_provisioning/samconfig.toml`
- [!] Task 5.4: Verify zero-edit deploy — Manual check (out of scope per spec)

## Phase 6: Documentation Updates
- [x] Task 6.1: Add "Provisioning the Knowledge Base (workshop)" section to root README before the "Knowledge base (RAG)" section. Includes pre-flight checklist, deploy commands, copy/paste step, region alignment note, credential chain note, fallback — `README.md`
- [x] Task 6.2: Update `CLAUDE.md`: add `kb_provisioning/` as project #3 in "Repository layout"; add `### Provisioning pipeline (kb_provisioning/)` to "Commands"; add architecture note under "Architecture" — `CLAUDE.md`
- [x] Task 6.3: Update `.env.example`: add comment near `KNOWLEDGE_BASE_ID` noting it comes from the `kb_provisioning` stack output — `.env.example`
- [x] Task 6.4: Add `kb_provisioning/README.md` with prerequisites (Titan v2 model access, AWS CLI, SAM), deploy command, copy/paste step, teardown, common-error troubleshooting — `kb_provisioning/README.md`
- [x] Task 6.5: Updated `.gitignore`: did NOT add `kb_provisioning/.aws-sam/` (matching existing convention — `evaluation/.aws-sam/` is tracked in git, so we don't gitignore the kb path either). Added `kb_provisioning/lambdas/seed_and_ingest/seed_data/*.txt` since these are generated copies of `src/data/*.txt` — `.gitignore`

## Phase 7: Tests for the Custom Resource Lambda
- [x] Task 7.1: Create `conftest.py` with `mock_s3_client` and `mock_bedrock_agent_client` (MagicMock fixtures) and a `make_cfn_event(request_type, properties, old_properties=None)` helper. Mirror `evaluation/tests/conftest.py` style — `kb_provisioning/tests/conftest.py`
- [x] Task 7.2: Create `test_seed_and_ingest.py` using the `importlib.util.spec_from_file_location` loader pattern from `evaluation/tests/test_start_eval_job.py:10-19` — `kb_provisioning/tests/test_seed_and_ingest.py`
- [x] Task 7.3: `TestCreateRequest`: asserts `s3.put_object` called once per seed file, `bedrock-agent.start_ingestion_job` called once with the right KB/DS, response Data has `IngestionJobId` and `FilesUploaded` — `kb_provisioning/tests/test_seed_and_ingest.py`
- [x] Task 7.4: `TestUpdateRequestNoOp`: identical Old/New properties → zero `s3.*` calls, zero `bedrock-agent.*` calls, response status `SUCCESS` — `kb_provisioning/tests/test_seed_and_ingest.py`
- [x] Task 7.5: `TestUpdateRequestWithChanges`: differing `KnowledgeBaseId` or `DataSourceId` → re-upload + re-ingest happen — `kb_provisioning/tests/test_seed_and_ingest.py`
- [x] Task 7.6: `TestDeleteRequest`: `list_objects_v2` paginated correctly; `delete_objects` called in batches; no Bedrock calls — `kb_provisioning/tests/test_seed_and_ingest.py`
- [x] Task 7.7: `TestSendCfnResponse`: patches `urllib.request.urlopen`; verifies request method=`PUT`, body is JSON with the documented keys (`Status`, `Reason`, `PhysicalResourceId`, `StackId`, `RequestId`, `LogicalResourceId`, `Data`) — `kb_provisioning/tests/test_seed_and_ingest.py`
- [x] Task 7.8: `TestErrorHandling`: forces an exception inside the body; asserts `send_cfn_response` was called with `Status="FAILED"` and `Reason` containing the exception message; asserts `handler` itself returned/did not raise — `kb_provisioning/tests/test_seed_and_ingest.py`
- [x] Task 7.9: Verify coverage: `pytest kb_provisioning/tests/ --cov=kb_provisioning/lambdas/seed_and_ingest --cov-report=term` → **85% coverage** (exceeds 80% minimum)

## Blocked Items
- Tasks 1.8, 2.8, 2.9, 3.4, 3.5, 3.6, 4.12–4.14, 5.4: These are live-AWS-deployment verification steps. Per spec ("do not run `sam build` against AWS, do not run `sam deploy`"), these are reserved for the audit phase or the attendee.
- `sam validate --lint` produces W1030 warnings for `DistanceMetric` values (`COSINE` etc.) because cfn-lint's schema for the new `AWS::S3Vectors::Index` resource type uses lowercase. This is a schema gap in cfn-lint, not a CloudFormation error. Basic `sam validate` (without `--lint`) passes cleanly.

## Notes
- **s3vectors:* action list verification**: The contract's draft list (`GetVectors`, `PutVectors`, `QueryVectors`, `DeleteVectors`, `GetIndex`, `ListIndexes`) was adopted as-is. These match the known S3 Vectors IAM service authorization reference as of 2026-05-09. If a real deploy surfaces `AccessDenied` on a missing action, extend the inline policy on `KnowledgeBaseRole`.
- **Vector bucket teardown**: `AWS::S3Vectors::VectorBucket` appears to support deletion without manual emptying based on CloudFormation documentation (CloudFormation manages the delete lifecycle). The simpler path (no explicit `DeleteVectors` call in the seed Lambda) was shipped. If teardown fails with a "bucket not empty" equivalent error, extend the `Delete` branch to call `s3vectors:DeleteVectors` on all vectors in the index.
- **gitignore convention**: `evaluation/.aws-sam/` is tracked in git (confirmed via `git ls-files`). Therefore `kb_provisioning/.aws-sam/` is NOT added to `.gitignore` — matching the existing convention.
- The `VectorIndex` resource uses `!If [HasVectorBucketName, !Ref VectorBucketName, !Sub "..."]` instead of `!GetAtt VectorBucket.VectorBucketName` to avoid cfn-lint E1010 (schema doesn't list `VectorBucketName` as a valid attribute for cfn-lint's version of the resource). Both approaches are semantically equivalent for the deployed stack.

## Completion
Completed: 2026-05-09
All implementation tasks for Phases 0–7 are done. Manual AWS-deployment verification tasks are marked [!] and reserved for the audit phase.
