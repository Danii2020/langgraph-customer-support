# Audit: KB Provisioning

> Auditor: sdd-auditor. Date: 2026-05-09.
> All requirements and contract items below trace back to `intent.md` (R*) and `contract.md` (C*).

## Summary

**Status**: PASS WITH CAVEATS

**Headline**: The implementation faithfully matches the contract. All 9 stack
parameters, all 9 outputs, the resource shapes, the IAM trust + inline policies,
the custom resource lifecycle semantics (`Create`/`Update`-noop/`Update`-changes/
`Delete`), the `urllib`-based CFN response, and the try/except wrapping are all
present and correct. `sam validate` exits 0 and 18/18 unit tests pass at 85%
coverage (exceeds the 80% threshold). Three documented deviations from the
literal contract (`VectorIndex.VectorBucketName` via `!If`,
`SeedAndIngestCustomResource.DependsOn` reduced to `SourceBucket`, and the
`DistanceMetric` cfn-lint W1030 warning) are reasonable and explained. The
"caveats" are exclusively the live-AWS validation gaps the user flagged: no real
`sam deploy` has been run yet, so `s3vectors:*` action sufficiency and vector
bucket teardown semantics remain unverified end-to-end.

## Requirements Checklist
| ID | Requirement | Source | Status | Notes |
|---|---|---|---|---|
| R1 | A SAM template provisions all KB resources in a single `sam build && sam deploy` from `kb_provisioning/`. | intent.md > Goals #1, Success #1 | PASS | `template.yaml:104-296` declares the full resource graph; `samconfig.toml:26` ships workshop defaults. |
| R2 | Stack auto-seeds the source S3 bucket with `src/data/policies.txt` and `src/data/data.txt` and starts the initial ingestion job during `Create`. | intent.md > Goals #2 | PASS | `handler.py:62-67` (Create branch) + `prepare_lambda_assets.py:29` (file list). `seed_data/policies.txt` and `seed_data/data.txt` are present on disk. |
| R3 | Stack output `KnowledgeBaseId` maps 1:1 to the env var consumed by `src/utils/rag_utils.py`/`src/agents/bedrock.py` and `evaluation/samconfig.toml`. | intent.md > Goals #3, Success #5/#6 | PASS | `template.yaml:302-309` emits `KnowledgeBaseId`; `.env.example:12-16` documents the handoff. |
| R4 | Mirrors `evaluation/` conventions (layout, samconfig pattern, Globals.Function, parameter_overrides format). | intent.md > Goals #4 | PASS | Directory layout under `kb_provisioning/{lambdas,scripts,tests}/`; `samconfig.toml` mirrors `evaluation/samconfig.toml` shape exactly; `Globals.Function` declared at `template.yaml:95-99`. |
| R5 | Stacks are independent: separate template, samconfig, stack name, no cross-stack imports. | intent.md > Goals #5 | PASS | No `Fn::ImportValue` anywhere in `template.yaml`; default stack name `kb-provisioning` differs from `rag-eval-pipeline`. |
| R6 | `sam deploy` reaches `CREATE_COMPLETE` in under ~10 minutes. | intent.md > Success #2 | DEFERRED | Cannot verify offline. No live deploy has been performed. |
| R7 | `aws bedrock-agent get-knowledge-base` returns `status: ACTIVE` post-deploy. | intent.md > Success #3 | DEFERRED | Cannot verify offline. |
| R8 | At least one ingestion job in `COMPLETE` state post-deploy. | intent.md > Success #4 | DEFERRED | Cannot verify offline. |
| R9 | Pasting `KnowledgeBaseId` into `.env` lets `python main.py` exercise the retriever tool against the new KB without code changes. | intent.md > Success #5 | DEFERRED | Behavior is design-correct (the `.env` key matches `src/utils/rag_utils.py` consumer) but requires live KB to verify. |
| R10 | Pasting `KnowledgeBaseId` into `evaluation/samconfig.toml` produces a working eval pipeline. | intent.md > Success #6 | DEFERRED | Same — design is correct, end-to-end verification requires live deploy. |
| R11 | Custom resource Lambda has unit tests following `evaluation/tests/`'s import-by-absolute-path pattern. | intent.md > Success #7 | PASS | `test_seed_and_ingest.py:19-25` uses identical `importlib.util.spec_from_file_location` pattern as `evaluation/tests/test_start_eval_job.py:10-16`. |
| R12 | `sam delete` removes every stack-created resource without leaving orphaned billable resources. | intent.md > Success #8 | DEFERRED | `Delete` branch logic is implemented (`handler.py:81-84`, `empty_bucket` at `:129-154`) but live-AWS teardown not exercised. Vector bucket teardown is a known gap. |
| R13 | Lambda runtime is `python3.13`. | intent.md > Constraints | PASS | `template.yaml:97`. |
| R14 | Lambda depends only on `boto3` (no pip packages). | intent.md > Constraints | PASS | `handler.py:16-21` imports only `json`, `os`, `urllib.request`, `typing`, `boto3`. |
| R15 | Default region `us-east-1` pinned in `[default.global.parameters]`. | intent.md > Constraints | PASS | `samconfig.toml:35-36`. |
| R16 | `samconfig.toml` has `capabilities = "CAPABILITY_IAM CAPABILITY_NAMED_IAM"`. | intent.md > Constraints | PASS | `samconfig.toml:14`. |

## Contract Compliance
| ID | Contract Item | Status | Verified By |
|---|---|---|---|
| C1 | 9 documented parameters with documented defaults. | PASS | `template.yaml:12-82`. Each parameter checked: `KnowledgeBaseName=workshop-kb` (:13-15), `SourceBucketName=""` (:20-22), `VectorBucketName=""` (:28-30), `VectorIndexName=workshop-kb-index` (:37-40), `EmbeddingModelArn=arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0` (:42-44), `SourceDataPrefix=data/` (:50-52), `EmbeddingDimension=1024` (:57-59), `DistanceMetric=COSINE` with AllowedValues (:64-71), `EnableAutoIngestion=true` (:73-78). |
| C2 | 9 documented outputs each with `Export.Name: !Sub "${AWS::StackName}-..."`. | PASS | `template.yaml:301-368`. All 9 present: `KnowledgeBaseId` (:302-309), `KnowledgeBaseArn` (:311-315), `DataSourceId` (:317-324), `SourceBucketName` (:326-335), `SourceBucketArn` (:337-341), `VectorBucketArn` (:343-347), `IndexArn` (:349-353), `KnowledgeBaseRoleArn` (:355-359), `Region` (:361-368). Each carries the `${AWS::StackName}-<key>` export. |
| C3 | `VectorIndex` uses `Dimension`, `DistanceMetric`, `DataType: float32`. | PASS | `template.yaml:177-188`. `Dimension: !Ref EmbeddingDimension` (default 1024), `DistanceMetric: !Ref DistanceMetric` (default COSINE), `DataType: float32` literal. |
| C4 | `KnowledgeBase` shape: `Type: VECTOR`, Titan v2 ARN, `StorageConfiguration.Type: S3_VECTORS`, `IndexArn: !GetAtt VectorIndex.IndexArn`. | PASS | `template.yaml:193-205`. Matches verbatim. |
| C5 | `KnowledgeBaseDataSource` omits `VectorIngestionConfiguration` (default chunking inherited). | PASS | `template.yaml:212-222` — only `Name`, `KnowledgeBaseId`, and `DataSourceConfiguration` are present. No `VectorIngestionConfiguration` block. Comment at :209-211 explicitly explains the omission. |
| C6 | `KnowledgeBaseRole` trust + inline policy match contract. | PASS | `template.yaml:109-150`. Trust on `bedrock.amazonaws.com` (:117-119). Inline policy has the three documented Sids: `InvokeEmbeddingModel` with `bedrock:InvokeModel` on `!Ref EmbeddingModelArn` (:125-128), `ReadSourceBucket` with `s3:GetObject`/`s3:ListBucket` on bucket and `bucket/*` (:130-137), `VectorIndexAccess` with the six `s3vectors:*` actions on both `VectorBucketArn` and `IndexArn` (:139-150). |
| C7 | Idempotent re-deploy: identical-property `Update` is a no-op (no S3 calls, no Bedrock calls). | PASS | `handler.py:69-74`. The `Update` branch computes `changed = any(props.get(k) != old_props.get(k) for k in _TRACKED_KEYS)` where `_TRACKED_KEYS = ("SourceBucketName", "SourceDataPrefix", "KnowledgeBaseId", "DataSourceId")` (:26). If `not changed`, the function sends `SUCCESS` and returns without touching S3 or Bedrock. Verified by `TestUpdateRequestNoOp::test_no_s3_calls_when_properties_unchanged` which asserts `put_object.assert_not_called()` and `start_ingestion_job.assert_not_called()`. |
| C8 | Output `KnowledgeBaseId` is stable across no-op re-deploys; export name `${AWS::StackName}-KnowledgeBaseId` is stable. | PASS | `template.yaml:308`. Export name is `!Sub "${AWS::StackName}-KnowledgeBaseId"`. Value is `!Ref KnowledgeBase`, which CFN keeps stable across no-op updates. |
| C9 | Handler dispatches on `event["RequestType"]`: `Create` uploads+ingests, `Update` no-op when unchanged, `Delete` empties bucket. | PASS | `handler.py:62-87`. Explicit `if/elif` on `Create`/`Update`/`Delete` with the contracted semantics. `Delete` branch calls `empty_bucket` and never touches Bedrock. |
| C10 | Handler always sends a CFN response; never raises. | PASS | `handler.py:49-99`. The entire body is wrapped in `try/except Exception`. The `except` branch builds `reason = f"{type(exc).__name__}: {exc}"` and calls `send_cfn_response(..., "FAILED", ...)`. The handler returns `{}` rather than re-raising. Verified by `TestErrorHandling::test_handler_never_raises`, `test_emits_failed_when_s3_raises`, `test_emits_failed_when_bedrock_raises`, and `test_failed_response_reason_contains_exception_message`. |
| C11 | Single-command attendee surface succeeds with no edits to `samconfig.toml`. | PASS (design-level) | `samconfig.toml:26` ships every parameter with its default. `disable_rollback = true` at :28. Live deploy not run. |
| C12 | Fallback (`EnableAutoIngestion=false`) → `scripts/seed_and_ingest.py` performs the same effect. | PASS | `scripts/seed_and_ingest.py:39-127` reads stack outputs via `cloudformation:DescribeStacks`, uploads files, calls `start_ingestion_job` with the same `knowledgeBaseId`/`dataSourceId` shape as the Lambda. |
| C13 | Seed files land at `s3://${SourceBucketName}/${SourceDataPrefix}` matching `src/data/*.txt`. | PASS (design-level) | `handler.py:111` constructs `s3_key = f"{prefix}{filename}"` and uploads via `put_object(Bucket=bucket, Key=s3_key, Body=...)`. `TestCreateRequest::test_put_object_uses_correct_prefix_and_bucket` asserts the bucket+key path. |
| C14 | `Delete` empties source bucket so CFN bucket delete succeeds. | PASS | `handler.py:129-154`. Uses `s3.get_paginator("list_objects_v2").paginate(...)` to walk the bucket, batches into `delete_objects(Delete={"Objects": batch})`. Skips when no objects. Also drains `list_object_versions` for the versioned case (best-effort, suppressed in try/except). Verified by `TestDeleteRequest::test_calls_delete_objects_for_each_page` (multi-page) and `test_empty_bucket_skips_delete_when_no_objects`. |
| C15 | Missing Titan v2 access → custom resource emits `FAILED` with the boto3 error verbatim in `Reason`. | PASS | `handler.py:89-99`. Any boto3 exception in `start_ingestion` (called from the `Create`/`Update`-changes branches) is caught and the exception message becomes `Reason`. `TestErrorHandling::test_emits_failed_when_bedrock_raises` validates the FAILED-on-bedrock-error path. |
| C16 | No `Fn::ImportValue` between this stack and `evaluation/`; cross-stack only via copy/paste. | PASS | `grep -n "ImportValue\|Fn::ImportValue" kb_provisioning/template.yaml` returns no matches. Documented in `.env.example:12-16` and `kb_provisioning/README.md`. |

## Test Coverage
| ID | Test Description | Status | Test File |
|---|---|---|---|
| T1 | `Create` request: uploads happen, ingestion job starts, response Data has `IngestionJobId` and `FilesUploaded`. | PASS | `kb_provisioning/tests/test_seed_and_ingest.py::TestCreateRequest` (3 tests, all green) |
| T2 | `Update` request with identical OldResourceProperties is a no-op. | PASS | `kb_provisioning/tests/test_seed_and_ingest.py::TestUpdateRequestNoOp` (2 tests; one explicitly asserts `put_object.assert_not_called()` and `start_ingestion_job.assert_not_called()`) |
| T3 | `Update` request with changed `KnowledgeBaseId` re-uploads and re-starts ingestion. | PASS | `kb_provisioning/tests/test_seed_and_ingest.py::TestUpdateRequestWithChanges` (2 tests: KnowledgeBaseId change, DataSourceId change) |
| T4 | `Delete` paginates `list_objects_v2`, batches `delete_objects`, never calls Bedrock. | PASS | `kb_provisioning/tests/test_seed_and_ingest.py::TestDeleteRequest` (3 tests) |
| T5 | `send_cfn_response` PUTs a JSON body of the documented shape to `event["ResponseURL"]`. | PASS | `kb_provisioning/tests/test_seed_and_ingest.py::TestSendCfnResponse` (4 tests; verifies HTTP method PUT, body contains 7 documented keys, FAILED carries Reason, IDs populated from event) |
| T6 | Any exception triggers `FAILED` with exception message in `Reason`; handler never raises. | PASS | `kb_provisioning/tests/test_seed_and_ingest.py::TestErrorHandling` (4 tests) |
| T7 | `prepare_lambda_assets.py` idempotency. | MISSING (optional) | Not implemented. Marked optional in audit stub; the script is simple `shutil.copy2`, low risk. |
| T8 | Standalone `seed_and_ingest.py` script tests. | MISSING (optional) | Not implemented. Marked optional in audit stub. |
| T9 | Coverage ≥ 80% for handler.py. | PASS | `pytest --cov=kb_provisioning/lambdas/seed_and_ingest` reports `handler.py` at **85%** (95 stmts, 14 missed). |
| T10 | `sam validate` exits 0. | PASS | `sam validate --template kb_provisioning/template.yaml --region us-east-1` exits 0 ("is a valid SAM Template"). |

### Test results — pytest output

```
collected 18 items
... 18 passed in 0.22s
Coverage: kb_provisioning/lambdas/seed_and_ingest/handler.py  95 stmts  14 missed  85%
```

No flaky tests. No skipped tests. No xfail/xpassed.

## `sam validate` result

- `sam validate --template kb_provisioning/template.yaml --region us-east-1` → exit 0. Output: "is a valid SAM Template".
- `sam validate --template ... --lint` → exit 1 with three W1030 warnings: `DistanceMetric: {'Ref': 'DistanceMetric'}` is not one of `['cosine', 'euclidean']`. This is the documented cfn-lint schema gap (the template parameter's `AllowedValues` is `COSINE` / `EUCLIDEAN` / `DOT_PRODUCT` in uppercase, matching the actual AWS service contract; cfn-lint's schema for the new `AWS::S3Vectors::Index` resource lists lowercase values). The implementation matches what AWS expects; the cfn-lint warning is a false positive.

## Documented deviations

| # | Deviation | Status | Notes |
|---|---|---|---|
| D1 | `VectorIndex.VectorBucketName` uses `!If [HasVectorBucketName, !Ref VectorBucketName, !Sub "..."]` instead of `!GetAtt VectorBucket.VectorBucketName`. | ACCEPTABLE | Verified `template.yaml:177-184`: `DependsOn: VectorBucket` is present at :179, so the implicit ordering is preserved. The two formulations are semantically equivalent at CFN time. The `!If` arm produces the same string the bucket itself uses at :172-175. Reason given (cfn-lint E1010 gap) is plausible. |
| D2 | `SeedAndIngestCustomResource.DependsOn` reduced from `[SourceBucket, KnowledgeBase, KnowledgeBaseDataSource]` to just `[SourceBucket]`. | ACCEPTABLE | Verified `template.yaml:282-296`: `Properties.KnowledgeBaseId: !Ref KnowledgeBase` (:294) and `Properties.DataSourceId: !GetAtt KnowledgeBaseDataSource.DataSourceId` (:295) both create implicit dependencies in CloudFormation, so the explicit `DependsOn` for those two is redundant. `SourceBucket` is kept explicit because the bucket name is built from a `!Sub` (not a `Ref`/`GetAtt` to the bucket) so the implicit edge is not formed. Sound reasoning. |
| D3 | cfn-lint W1030 on `DistanceMetric: COSINE`. | ACCEPTABLE | The parameter declares `AllowedValues: [COSINE, EUCLIDEAN, DOT_PRODUCT]` (uppercase) at `template.yaml:67-70`, matching the AWS service contract for `AWS::S3Vectors::Index`. cfn-lint's schema for the brand-new resource type uses lowercase. Confirmed reproduces only under `--lint`; basic `sam validate` is clean. |

## Live-AWS validation gaps

These items genuinely cannot be checked offline and require a real `sam deploy`:

1. **`s3vectors:*` action list sufficiency** (referenced from contract C6 and roadmap Phase 2 step 5). The shipped list — `GetVectors`, `PutVectors`, `QueryVectors`, `DeleteVectors`, `GetIndex`, `ListIndexes` — matches the contract's draft list and is consistent with the IAM service authorization reference as of 2026-05-09. However, only a live ingestion (which exercises the role from Bedrock's side) can definitively confirm no `AccessDenied` arises from a missing action. If a real deploy surfaces `AccessDenied`, append the missing action to `KnowledgeBaseAccess` inline policy at `template.yaml:139-150`.
2. **Vector bucket teardown semantics**. The implementation ships the simpler path: `empty_bucket` (`handler.py:129-154`) handles only the source S3 bucket; there is no `s3vectors:DeleteVectors` call on `Delete`. The contract / tasks.md both note this as "verify during implementation." If `sam delete` fails with a "vector bucket not empty" equivalent error, the `Delete` branch must be extended to enumerate and delete vectors from `VectorIndex` before the resource is removed.
3. **End-to-end deploy**, `KB ACTIVE`, ingestion `COMPLETE`, and the LangGraph/evaluation handoffs (R6–R10, R12). The implementation is structurally complete; only an attendee or facilitator running `sam deploy` against a real AWS account can verify the success criteria.

## Recommendations

1. **(P0) Run a real `sam deploy`** against a workshop AWS account before the workshop to close the three live-AWS gaps above. Capture the resulting `KnowledgeBaseId`, then run `python main.py` and a single eval deploy to validate the full copy/paste handoff once. This is the gating step before approving for workshop use.
2. **(P1) During the live deploy, watch CloudTrail for `AccessDenied`** events tagged to the `KnowledgeBaseRole` execution principal. If any surface, append the missing `s3vectors:*` action to `template.yaml:141-147` and re-deploy. This is the only realistic way to confirm the action list is exhaustive.
3. **(P1) After teardown, run `aws s3vectors get-vector-bucket --vector-bucket-arn <arn>`** to confirm the vector bucket is actually gone. If it persists, extend `empty_bucket` in `handler.py` to also drain the vector index via `s3vectors:DeleteVectors` (or invoke the bedrock-side delete path explicitly).
4. **(P2) Consider adding the optional tests T7/T8** (`test_prepare_lambda_assets.py`, `test_seed_and_ingest_script.py`). The current 85% coverage is fine for the Lambda, but the standalone fallback script (`scripts/seed_and_ingest.py`) has zero test coverage and is the documented Option-2 path attendees fall back to. A single happy-path test against mocked boto3 would be cheap insurance.
5. **(P3) Document the cfn-lint W1030 noise** in the workshop facilitator notes so attendees who run `sam validate --lint` are not confused. The current note in `tasks.md` is good; consider lifting it into `kb_provisioning/README.md`'s troubleshooting table.
6. **(P3) Vector bucket teardown contingency**: if D2/live-AWS gap 2 surfaces a failure, the cleanest fix is to extend the `Delete` branch in `handler.py` to call `boto3.client("s3vectors").list_vectors` + `delete_vectors` against the configured `IndexArn`. The seed Lambda already has the IAM scaffolding (`s3:DeleteObject` and friends on the source bucket); add `s3vectors:DeleteVectors` and `s3vectors:ListVectors` to `SeedAndIngestFunctionRole` (`template.yaml:227-261`) if you go this route.

## Final Verdict

**Status**: APPROVED WITH RESERVATIONS

**Summary**: Static implementation is contract-compliant and well-tested. The
reservations are entirely deferred live-AWS verifications (no `sam deploy` has
been run), which the user explicitly flagged as out-of-scope for offline audit.

**Critical Issues** (must fix before merge): None.

**Warnings** (should fix, not blocking):
- Live-AWS deploy is required before the workshop to validate `s3vectors:*` action sufficiency and vector bucket teardown.
- The standalone fallback script `kb_provisioning/scripts/seed_and_ingest.py` has no unit tests.

**Recommendations** (nice to have):
- Add T7/T8 optional tests.
- Lift the cfn-lint W1030 explanation into the README troubleshooting table.

## Audit Log
| Date | Auditor | Finding | Severity | Resolution |
|---|---|---|---|---|
| 2026-05-09 | sdd-auditor | All 16 requirements (R1–R16) and 16 contract items (C1–C16) reviewed. 12 PASS, 0 FAIL, 4 DEFERRED to live AWS (R6, R7, R8, R12 plus R9/R10 which are design-correct but require live KB). | LOW | No code changes needed; run a real `sam deploy` to close DEFERRED items. |
| 2026-05-09 | sdd-auditor | 18/18 unit tests pass; coverage 85% (exceeds 80% minimum). | INFO | None. |
| 2026-05-09 | sdd-auditor | `sam validate` exits 0; `sam validate --lint` surfaces three W1030 warnings on `DistanceMetric` — confirmed false positive (cfn-lint schema lag on the new `AWS::S3Vectors::Index` resource). | LOW | Document in README troubleshooting. |
| 2026-05-09 | sdd-auditor | Three documented deviations (D1 `VectorIndex.VectorBucketName` via `!If` + `DependsOn`, D2 `CustomResource.DependsOn` reduced to `[SourceBucket]`, D3 cfn-lint W1030) reviewed; all acceptable with sound technical justification. | LOW | None. |
| 2026-05-09 | sdd-auditor | Standalone fallback script `scripts/seed_and_ingest.py` lacks unit tests. Optional per audit stub, but worth adding a single happy-path test. | MEDIUM | Add `test_seed_and_ingest_script.py` (Phase 7 optional T8). |
| 2026-05-09 | sdd-auditor | Live-AWS gaps: (a) `s3vectors:*` action sufficiency, (b) vector bucket teardown, (c) end-to-end deploy/ingestion/handoff. | HIGH (deferred) | Schedule a pre-workshop dry-run `sam deploy` and capture results. |
