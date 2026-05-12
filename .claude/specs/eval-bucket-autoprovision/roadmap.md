# Roadmap: eval-bucket-autoprovision

## Design Decisions (justifications for choices in `intent.md`)

### DD1. No `EnableAutoIngestion`-style conditional

`kb_provisioning/template.yaml` gates its seed-and-ingest Lambda behind
`EnableAutoIngestion: "true"|"false"`. We deliberately do **not** mirror
that pattern here.

Rationale:
- For `kb_provisioning/`, skipping auto-ingestion makes sense because the
  user may want to re-seed from a real document corpus that does not live
  in the repo. For `evaluation/`, the seed files (`evaluation_dataset.jsonl`,
  `thresholds.json`, `kb_prompt_template.txt`) are repo-versioned workshop
  data. There is no realistic scenario where the workshop attendee wants
  the buckets without the seed.
- Adding the conditional doubles the surface area of the
  `Resources:` section (one `Condition:` per Lambda + role + custom
  resource) for zero workshop benefit.
- If a power user really does want to skip seeding, they can comment out
  `SeedEvalAssetsCustomResource` locally. We do not optimize for that
  case.

### DD2. Buckets cleaned up on stack delete (no `DeletionPolicy: Retain`)

The `kb_provisioning/` stack also defaults to "delete the bucket". For a
workshop this is the right behavior — attendees expect `sam delete` to
fully tear down. Production forks should set
`DeletionPolicy: Retain` on the buckets and remove the empty-on-delete
branch from the Lambda; document in `intent.md` constraints (already
done) so a future maintainer does not accidentally "harden" the workshop
by changing the deletion policy.

### DD3. Demo script `upload_prompt_template.py` resolves bucket from stack output, not from samconfig.toml

We could read the bucket name by parsing `evaluation/samconfig.toml`, but:
- The bucket name is no longer a `parameter_override` after this feature.
  The samconfig file does not know it.
- `cloudformation:DescribeStacks` is the authoritative source — it
  reflects the actual deployed stack, not what the attendee thinks they
  deployed.
- The same lookup pattern is well-established (`aws cloudformation
  describe-stacks --query 'Stacks[0].Outputs[?OutputKey==\`...\`]'`); the
  boto3 equivalent is one paginated call.
- Attendees may rename their stack via `--stack-name` on the command
  line; the script accepts a `--stack-name` flag with a default that
  matches `samconfig.toml`.

### DD4. Single seed Lambda for both buckets

We could split this into two custom resources (one per bucket). We choose
a single Lambda because:
- The Create-time uploads only target `EvalBucket`. The `ResultsBucket` is
  empty at Create time and is filled by Bedrock during evaluation runs.
- The Delete-time empty path must run for both. A single Lambda with
  `bucket_to_empty` looping over `[EvalBucket, ResultsBucket]` is simpler
  than two near-identical custom resources.
- Matches the single-Lambda pattern in
  `kb_provisioning/lambdas/seed_and_ingest/handler.py`.

### DD5. `seed_assets/` directory inside the Lambda CodeUri (not bundled via S3 layer)

We could ship the seed files via a SAM `Layer`, an S3-resident archive, or
inlined as base64 in the template. We pick the `seed_assets/` directory
because:
- It matches the established `kb_provisioning/lambdas/seed_and_ingest/seed_data/`
  layout.
- `sam build` copies the whole `CodeUri` directory into the deployment
  package, so the files travel with the Lambda code with zero extra
  packaging steps.
- The Lambda code reads them via plain `open()` — no `boto3` indirection,
  no IAM permission to read a layer S3 bucket.
- The total seed size (`evaluation_dataset.jsonl` is small,
  `thresholds.json` is < 1KB, `kb_prompt_template.txt` is a few KB) is
  well under the 250MB unzipped Lambda package limit.

### DD6. `prepare_lambda_assets.py` is a separate pre-build step (not run inside `sam build`)

`sam build` does not provide a pre-build hook in the SAM CLI surface;
attempting to invoke the asset copy via a `Makefile` target would
diverge from the established workflow that the
`kb_provisioning/` README and `CLAUDE.md` already teach. We mirror the
established two-step workflow: run the script, then run `sam build`.

### DD7. EventBridge subscription on the eval bucket only

The results bucket does **not** need EventBridge notifications enabled
because we never trigger a downstream pipeline on a Bedrock write. Only
the eval bucket (which receives the prompt-template demo upload) needs
notifications. This is intentional and reduces blast-radius / IAM surface.

## Implementation Phases

### Phase 1: Foundation — seed Lambda + pre-build helper

**Goal**: Stand up the new Lambda function, its IAM role, and the
pre-build asset-copy helper. No template wiring yet; this phase produces
artifacts only.

**Dependencies**: None (the spec files in `.claude/specs/eval-bucket-autoprovision/`).

**Estimated complexity**: Medium (boilerplate-heavy but well-precedented).

1. Create directory
   `evaluation/lambdas/seed_eval_assets/` with `__init__.py` (empty).
2. Write `evaluation/lambdas/seed_eval_assets/handler.py`, port from
   `kb_provisioning/lambdas/seed_and_ingest/handler.py` with these
   differences:
   - Replace `_TRACKED_KEYS = ("SourceBucketName", "SourceDataPrefix",
     "KnowledgeBaseId", "DataSourceId")` with
     `_TRACKED_KEYS = ("EvalBucketName", "ResultsBucketName")`.
   - Replace `SEED_DATA_DIR = .../seed_data` with
     `SEED_ASSETS_DIR = .../seed_assets`.
   - Replace `upload_seed_data(bucket, prefix)` with
     `upload_seed_assets(bucket)` that iterates
     `SEED_FILES: list[tuple[str, str]]` instead of `os.listdir`.
   - Remove the `bedrock-agent.start_ingestion_job(...)` call entirely.
   - Add `Delete` handling that empties **both** `EvalBucketName` and
     `ResultsBucketName` (loop over the two buckets).
3. Write `evaluation/scripts/prepare_lambda_assets.py`, mirroring
   `kb_provisioning/scripts/prepare_lambda_assets.py`. Copy map:
   - `evaluation/dataset/evaluation_dataset.jsonl` →
     `evaluation/lambdas/seed_eval_assets/seed_assets/evaluation_dataset.jsonl`
   - `evaluation/config/thresholds.json` →
     `evaluation/lambdas/seed_eval_assets/seed_assets/thresholds.json`
   - `evaluation/prompts/kb_prompt_template.txt` →
     `evaluation/lambdas/seed_eval_assets/seed_assets/kb_prompt_template.txt`
4. Add `evaluation/lambdas/seed_eval_assets/seed_assets/.gitkeep` so the
   directory exists in version control even when the copied files are
   git-ignored.
5. Update `.gitignore` (root) to exclude
   `evaluation/lambdas/seed_eval_assets/seed_assets/*` except `.gitkeep`,
   mirroring the existing convention if `kb_provisioning/.../seed_data/`
   is similarly ignored. (Verify by reading the current `.gitignore`.)

### Phase 2: Core template wiring

**Goal**: Provision the buckets, custom resource, and IAM role in
`evaluation/template.yaml`. Update all references that previously read
from `!Ref EvalBucketName` etc. Outputs are exported.

**Dependencies**: Phase 1.

**Estimated complexity**: Medium (mostly mechanical edits; risk is in
the EventBridge `Input:` strings).

1. In `evaluation/template.yaml`, remove the three parameters
   `EvalBucketName`, `ResultsBucketName`, `PromptTemplateBucketName`
   from the `Parameters:` block.
2. Update `Globals.Function.Environment.Variables.EVAL_BUCKET_NAME` from
   `!Ref EvalBucketName` to `!Ref EvalBucket`.
3. Add `EvalBucket` resource (`AWS::S3::Bucket` with `BucketName` via
   `!Sub` and `NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled:
   true`).
4. Add `ResultsBucket` resource (`AWS::S3::Bucket` with `BucketName` via
   `!Sub`; no notification config).
5. Update `LambdaExecutionRole.Policies.S3ReadPermissions.Resource` to
   use `!GetAtt EvalBucket.Arn` / `!GetAtt ResultsBucket.Arn` /
   `!Sub "${EvalBucket.Arn}/*"` / `!Sub "${ResultsBucket.Arn}/*"`.
6. Add `SeedEvalAssetsFunctionRole` (IAM role) per contract.md.
7. Add `SeedEvalAssetsFunction` (`AWS::Serverless::Function`) per
   contract.md.
8. Add `SeedEvalAssetsCustomResource` (`AWS::CloudFormation::CustomResource`)
   with `DependsOn: [EvalBucket, ResultsBucket]`.
9. Update `KbSyncCompletionRule.Targets[0].Input` — replace
   `${EvalBucketName}` with `${EvalBucket}` and `${ResultsBucketName}`
   with `${ResultsBucket}` in the inline JSON. (No `- !Sub` map keys
   change; `!Ref EvalBucket` resolves to the bucket name.)
10. Update `PromptTemplateChangeRule.EventPattern.detail.bucket.name`
    from `!Ref PromptTemplateBucketName` to `!Ref EvalBucket`.
11. Update `PromptTemplateChangeRule.Targets[0].Input` — same
    `${EvalBucketName}` → `${EvalBucket}` and `${ResultsBucketName}` →
    `${ResultsBucket}` substitution in the inline JSON.
12. Add `Outputs.EvalBucketName` and `Outputs.ResultsBucketName` per
    contract.md.

### Phase 3: Workshop scripts and samconfig

**Goal**: Retire the bulk-seed script, upgrade the demo script, and
shorten `samconfig.toml`.

**Dependencies**: Phase 2.

**Estimated complexity**: Low.

1. Delete `evaluation/scripts/setup_s3.py`. Remove any references from
   `CLAUDE.md`.
2. Rewrite `evaluation/scripts/upload_prompt_template.py` per
   contract.md "Workshop demo script API":
   - Add `--bucket` (optional, explicit override).
   - Add `--stack-name` (default `"rag-eval-pipeline"`).
   - Default `--region` from `"us-east-2"` to `"us-east-1"` to match
     `samconfig.toml:12` (this is a correctness fix; the current default
     of `us-east-2` is stale from the LangGraph app's region and would
     not find the eval stack at all in the new workflow).
   - Keep `--prefix` (default `"prompts/"`) and `--template` (default
     `evaluation/prompts/kb_prompt_template.txt`).
   - Add `resolve_eval_bucket(cfn_client, stack_name)` helper that uses
     `cfn_client.describe_stacks` and the `Outputs[?OutputKey == "EvalBucketName"]`
     pattern.
   - Friendly error messages per contract.md error table.
3. Update `evaluation/samconfig.toml`:
   - Strip `EvalBucketName=...`, `ResultsBucketName=...`,
     `PromptTemplateBucketName=...` from `parameter_overrides`.
   - Keep `KnowledgeBaseId`, `EvalRoleArn`, `BedrockModelId`,
     `EvaluatorModelId`, `NotificationEmail`, `MaxPollingIterations`,
     `PromptTemplatePrefix`.
4. Update `CLAUDE.md` "Evaluation pipeline" section:
   - Replace the existing setup commands (`setup_s3.py` and the legacy
     `upload_prompt_template.py <bucket>`) with a single
     `python evaluation/scripts/prepare_lambda_assets.py` before
     `sam build && sam deploy`.
   - Add a "Retrigger the pipeline (workshop demo)" snippet showing
     `python evaluation/scripts/upload_prompt_template.py` with no
     arguments.
   - Note that `sam delete` now empties and removes the buckets
     automatically.

### Phase 4: Testing & validation

**Goal**: Unit tests for the seed Lambda and for the demo script's
bucket-resolution helper. Existing Lambda tests continue to pass.

**Dependencies**: Phase 3.

**Estimated complexity**: Medium.

1. Extend `evaluation/tests/conftest.py` with a `make_cfn_event(request_type,
   properties=None, old_properties=None, ...)` factory mirroring
   `kb_provisioning/tests/conftest.py:35-68`. Default `properties` matches
   the seed Lambda's `ResourceProperties` (`EvalBucketName`,
   `ResultsBucketName`, `Region`).
2. Add a new `mock_cfn_client` fixture to `evaluation/tests/conftest.py`
   that returns a MagicMock with a `.describe_stacks()` method whose
   default return value contains the `EvalBucketName` output.
3. Write `evaluation/tests/test_seed_eval_assets.py` mirroring
   `kb_provisioning/tests/test_seed_and_ingest.py` test-class structure:
   - `TestCreateRequest` — uploads three files, no bedrock-agent calls,
     `FilesUploaded == "3"`.
   - `TestUpdateRequestNoOp` — same `EvalBucketName` / `ResultsBucketName`
     pair → zero S3 calls.
   - `TestUpdateRequestWithChanges` — different `EvalBucketName` → re-upload.
   - `TestDeleteRequest` — paginated empty for both buckets; one
     `delete_objects` call per non-empty page per bucket.
   - `TestSendCfnResponse` — JSON body shape, PUT method, ResponseURL.
   - `TestErrorHandling` — `s3:PutObject` raise → `FAILED` response;
     `handler()` never raises.
4. Write `evaluation/tests/test_upload_prompt_template.py`:
   - `TestResolveEvalBucket.test_returns_bucket_when_output_present`
   - `TestResolveEvalBucket.test_raises_runtime_error_when_stack_not_found`
   - `TestResolveEvalBucket.test_raises_key_error_when_output_missing`
   - `TestMain.test_uses_bucket_flag_when_provided` (skips DescribeStacks)
   - `TestMain.test_resolves_from_stack_when_no_bucket_flag`
   - `TestMain.test_uploads_to_canonical_key`
5. Run `pytest evaluation/tests/` end-to-end. Verify all existing tests
   (`test_start_eval_job.py`, `test_check_eval_status.py`,
   `test_parse_eval_results.py`) still pass.
6. Run `cfn-lint evaluation/template.yaml` (if available) to catch
   `!Sub` typos or unreferenced parameters.
7. Run `sam validate --lint -t evaluation/template.yaml` from
   `evaluation/` to catch SAM-level issues.
8. **Manual deploy smoke test** (not part of CI): in a clean AWS account,
   `python evaluation/scripts/prepare_lambda_assets.py`, then
   `cd evaluation && sam build && sam deploy`. Verify:
   - Stack reaches `CREATE_COMPLETE`.
   - Eval bucket has the three canonical objects.
   - Eval bucket `NotificationConfiguration.EventBridgeConfiguration`
     is enabled.
   - Running `python evaluation/scripts/upload_prompt_template.py` (no
     args) starts a Step Functions execution.
   - `sam delete` succeeds.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bucket name collision with an existing global S3 bucket (someone else owns the same `{stack}-eval-{account}-{region}` name) | Very Low | High (stack fails to deploy) | The `${AccountId}` component makes collision impossible across accounts (S3 bucket names are global but AWS account IDs are unique). The only realistic collision is two deploys to the same account/region with the same stack name; that is intentional behavior (CFN refuses to overwrite). |
| Attendee forgets `prepare_lambda_assets.py` and runs `sam build` with empty `seed_assets/` | Medium | Medium (stack deploys but pipeline crashes on first run) | Document loudly in `CLAUDE.md`. Lambda logs `WARNING: source file not found` for each skipped file, which appears in CloudWatch — make sure the print statements are clear. Consider exiting non-zero from `prepare_lambda_assets.py` if any source file is missing (instead of just warning) — defer this to executor judgment but call it out. |
| `sam delete` IAM denial on `s3:DeleteObject` during bucket empty | Low | High (stack stuck in `DELETE_FAILED`) | Verified by the `SeedEvalAssetsFunctionRole` policy that explicitly grants `s3:DeleteObject` on both buckets. Unit test (`TestDeleteRequest`) covers the happy path. Manual remediation runbook: empty the bucket manually with `aws s3 rm --recursive` and retry `sam delete`. |
| `PromptTemplateChangeRule` fires on the Lambda's own seed upload (Create-time race) | Low | Low (one extra eval run on first deploy) | The seed Lambda runs as part of stack create; the rule is `ENABLED` at create time. The seed upload of `prompts/kb_prompt_template.txt` does match the rule's pattern, so an extra evaluation run will start. This is harmless — the eval will execute against the freshly-seeded dataset and produce a baseline pass/fail. Document in `intent.md` as expected behavior, not a bug. |
| CFN `Outputs.EvalBucketName` renamed by a future contributor, breaking `upload_prompt_template.py` | Low | Medium | G12 in `contract.md` calls out the contract explicitly. The unit test `TestResolveEvalBucket.test_returns_bucket_when_output_present` references the literal `"EvalBucketName"` string — any rename will break the test. |
| `upload_prompt_template.py` `--region` default mismatch (current value is `"us-east-2"` not `"us-east-1"`) | Currently active in repo | High (script silently looks at wrong region's stack) | Phase 3 fixes this. Add a regression test that asserts the argparse default for `--region` equals `"us-east-1"`. |
| Workshop attendee on Windows: `os.path.join` paths in `prepare_lambda_assets.py` may not match the Lambda zip layout produced by `sam build` on Windows | Low | Medium | `sam build` itself normalizes path separators inside the zip; this is not a concern for the Lambda runtime. Verify on Windows once if possible; otherwise document in `CLAUDE.md` as a known soft spot. |
| EventBridge propagation delay >30s, breaking the success criterion "execution starts within ~30 seconds" | Low | Low | The success criterion uses "~30 seconds" (with wiggle room); EventBridge typically delivers in <10s but can spike to ~60s. Adjust the criterion phrasing during testing rather than the architecture. |
| Single Lambda failing partway through Delete leaves one bucket empty and one full | Low | Medium | Lambda processes buckets sequentially; if it raises mid-loop, the exception envelope sends `FAILED` and CFN marks the resource `DELETE_FAILED`. Operator must rerun `sam delete` (idempotent — empty bucket is a no-op) or manually empty the second bucket. Acceptable workshop failure mode. |

## File Change Map

### CREATE

- `evaluation/lambdas/seed_eval_assets/__init__.py` — CREATE — empty
  marker file matching the layout of the other three Lambda dirs.
- `evaluation/lambdas/seed_eval_assets/handler.py` — CREATE — the seed
  Lambda. Port from
  `kb_provisioning/lambdas/seed_and_ingest/handler.py`.
- `evaluation/lambdas/seed_eval_assets/seed_assets/.gitkeep` — CREATE —
  preserves the directory under version control.
- `evaluation/scripts/prepare_lambda_assets.py` — CREATE — mirrors
  `kb_provisioning/scripts/prepare_lambda_assets.py`.
- `evaluation/tests/test_seed_eval_assets.py` — CREATE — unit tests
  mirroring `kb_provisioning/tests/test_seed_and_ingest.py`.
- `evaluation/tests/test_upload_prompt_template.py` — CREATE — unit
  tests for the upgraded demo script's bucket-resolution helper.

### MODIFY

- `evaluation/template.yaml` — MODIFY — remove three parameters; add
  two buckets, one IAM role, one Lambda, one custom resource, two
  outputs; rewrite five `!Ref` / `!Sub` references (see contract.md
  "Template references that must change" table).
- `evaluation/samconfig.toml` — MODIFY — strip three keys from
  `parameter_overrides`.
- `evaluation/scripts/upload_prompt_template.py` — MODIFY — rewrite to
  resolve bucket from CFN stack output by default, with `--bucket` /
  `--stack-name` flags. Fix `--region` default to `"us-east-1"`.
- `evaluation/tests/conftest.py` — MODIFY — append a `make_cfn_event`
  factory and a `mock_cfn_client` fixture. Do not touch existing
  fixtures.
- `CLAUDE.md` — MODIFY — replace the "Evaluation pipeline" setup
  commands; add a "Retrigger the pipeline (workshop demo)" snippet.
- `.gitignore` — MODIFY (if needed) — exclude
  `evaluation/lambdas/seed_eval_assets/seed_assets/*` except `.gitkeep`,
  matching the existing convention for
  `kb_provisioning/lambdas/seed_and_ingest/seed_data/` if present.

### DELETE

- `evaluation/scripts/setup_s3.py` — DELETE — fully superseded by the
  seed Lambda.

### UNCHANGED (called out explicitly)

- `evaluation/lambdas/start_eval_job/handler.py` — UNCHANGED — the
  S3 URIs in the event payload are now CloudFormation-resolved but
  identical in shape.
- `evaluation/lambdas/check_eval_status/handler.py` — UNCHANGED.
- `evaluation/lambdas/parse_eval_results/handler.py` — UNCHANGED.
- `evaluation/tests/test_start_eval_job.py` — UNCHANGED — must
  continue to pass.
- `evaluation/tests/test_check_eval_status.py` — UNCHANGED.
- `evaluation/tests/test_parse_eval_results.py` — UNCHANGED.
- `evaluation/dataset/evaluation_dataset.jsonl` — UNCHANGED (the
  prepare script reads it).
- `evaluation/config/thresholds.json` — UNCHANGED.
- `evaluation/prompts/kb_prompt_template.txt` — UNCHANGED.
- `evaluation/requirements-dev.txt` — UNCHANGED.
- All `kb_provisioning/` files — UNCHANGED (reference implementation).
