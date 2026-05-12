# Intent: eval-bucket-autoprovision

## Problem Statement

Today the `evaluation/` SAM stack is **not self-service**. Before a workshop
attendee can `sam deploy` the RAG evaluation pipeline, they must:

1. Manually create an "eval" S3 bucket (used for dataset, thresholds, and
   prompt template) with a globally-unique name they have to pick themselves.
2. Manually create a "results" S3 bucket for Bedrock evaluation job output.
3. Manually enable EventBridge notifications on the eval bucket (SAM cannot
   do this for a pre-existing bucket, and the `PromptTemplateChangeRule`
   silently does nothing without it).
4. Run `evaluation/scripts/setup_s3.py <bucket>` to upload
   `evaluation/dataset/evaluation_dataset.jsonl` and
   `evaluation/config/thresholds.json` to the canonical S3 keys
   (`datasets/rag_eval.jsonl` and `baselines/thresholds.json`).
5. Run `evaluation/scripts/upload_prompt_template.py <bucket>` to upload
   `evaluation/prompts/kb_prompt_template.txt` to `prompts/kb_prompt_template.txt`.
6. Paste both bucket names into `evaluation/samconfig.toml`
   `parameter_overrides` as `EvalBucketName`, `ResultsBucketName`, and
   `PromptTemplateBucketName`.

This pre-flight ritual is error-prone (bucket-name collisions, wrong region,
missing EventBridge config, wrong S3 keys), creates state that escapes
CloudFormation's view, and blocks the workshop's "one command to deploy"
goal. The sibling `kb_provisioning/` stack already solved the same shape of
problem for KB document seeding; the eval stack must follow that pattern.

Separately, **uploading a modified prompt template to retrigger the pipeline
is a deliberate workshop teaching moment** — attendees should see the
`PromptTemplateChangeRule` fire end-to-end. That capability must survive
this refactor as a first-class, scripted action (the attendee runs one
command and watches Step Functions execute), not as a casualty of the
cleanup.

Affected:
- Workshop attendees (the primary audience) — every minute spent on bucket
  plumbing is a minute lost from the evaluation concepts being taught.
- Workshop instructors — every "my bucket name is taken" question is a
  support-cost spike during the workshop window.

## Goals

1. `sam deploy` of the `evaluation/` stack succeeds without any prerequisite
   S3 setup beyond the per-stack SAM artifact bucket that `resolve_s3 = true`
   already handles.
2. The eval and results S3 buckets are CloudFormation-managed resources
   inside `evaluation/template.yaml`, with auto-generated globally-unique
   names that follow the convention already used in `kb_provisioning/`
   (`${AWS::StackName}-<purpose>-${AWS::AccountId}-${AWS::Region}`).
3. The eval bucket has EventBridge notifications enabled at create time so
   `PromptTemplateChangeRule` works out of the box.
4. On stack create, a custom resource Lambda uploads the three seed files
   from inside the Lambda package to their canonical S3 keys.
5. On stack delete, the same custom resource empties both buckets so
   CloudFormation can remove them (no `BucketNotEmpty` failures).
6. The `evaluation/samconfig.toml` `parameter_overrides` line no longer
   contains `EvalBucketName`, `ResultsBucketName`, or
   `PromptTemplateBucketName`.
7. The legacy bulk-seed script `evaluation/scripts/setup_s3.py` is deleted
   (fully superseded by the custom resource on Create). The prompt-template
   upload script `evaluation/scripts/upload_prompt_template.py` is
   **kept and upgraded** into a workshop demo helper: invoked with no
   bucket argument, it auto-resolves the eval bucket name from the
   CloudFormation stack output and re-uploads
   `evaluation/prompts/kb_prompt_template.txt` to
   `prompts/kb_prompt_template.txt`. The re-upload triggers
   `PromptTemplateChangeRule` and starts a new evaluation run — this is
   the canonical "watch the pipeline fire" demo step.
8. `CLAUDE.md`'s "Evaluation pipeline" section is updated to reflect both
   the new deploy workflow (`prepare_lambda_assets.py` then `sam build &&
   sam deploy`) and the new demo workflow (`upload_prompt_template.py` to
   retrigger).

## Success Criteria

- [ ] A fresh AWS account with no pre-existing eval/results buckets can run
      `python evaluation/scripts/prepare_lambda_assets.py` followed by
      `cd evaluation && sam build && sam deploy --config-file samconfig.toml`
      and the stack reaches `CREATE_COMPLETE`.
- [ ] After `CREATE_COMPLETE`, listing the eval bucket shows three objects
      at the canonical keys:
      `datasets/rag_eval.jsonl`,
      `baselines/thresholds.json`,
      `prompts/kb_prompt_template.txt`.
- [ ] The eval bucket's `NotificationConfiguration` has
      `EventBridgeConfiguration` enabled.
- [ ] Uploading a new `prompts/kb_prompt_template.txt` to the eval bucket
      triggers the `EvalPipelineStateMachine` via `PromptTemplateChangeRule`
      with no additional `aws s3api put-bucket-notification-configuration`
      call.
- [ ] Running `python evaluation/scripts/upload_prompt_template.py` with
      no bucket argument (using only `--stack-name` / `--region` defaults
      that match `samconfig.toml`) successfully resolves the eval bucket
      from the stack's `EvalBucketName` output, uploads
      `evaluation/prompts/kb_prompt_template.txt` to
      `prompts/kb_prompt_template.txt`, and a new Step Functions execution
      starts within ~30 seconds.
- [ ] The Step Functions state machine receives the correct four S3 URIs in
      its input (matching the `KbSyncCompletionRule` / `PromptTemplateChangeRule`
      `Input:` JSON), all derived from CloudFormation resource refs.
- [ ] `sam delete --stack-name <name> --region us-east-1` succeeds without
      manual bucket emptying.
- [ ] Re-deploying the same stack name into the same account/region in a
      different test run does not collide on bucket names (the
      `${AccountId}-${Region}` suffix guarantees uniqueness per account).
- [ ] `evaluation/scripts/setup_s3.py` no longer exists in the repo;
      `CLAUDE.md` no longer references it.
- [ ] All existing `evaluation/tests/` Lambda unit tests still pass.
- [ ] A new `evaluation/tests/test_seed_eval_assets.py` covers Create,
      Update (no-op + with-changes), Delete, error handling, and CFN-response
      shape — mirroring `kb_provisioning/tests/test_seed_and_ingest.py`.

## Non-Goals

- We are **not** introducing an `EnableAutoIngestion`-style conditional to
  optionally skip seeding. The custom resource is part of the bucket's
  lifecycle by design; making it optional would split the contract for
  no workshop benefit. (Justified in `roadmap.md` "Design Decisions".)
- We are **not** changing the Step Functions state machine's input contract.
  The four S3 URIs in `Input:` keep the same shape and the same canonical
  keys (`datasets/rag_eval.jsonl`, `baselines/thresholds.json`,
  `prompts/kb_prompt_template.txt`, `results/rag/`) — only the bucket
  portion of each URI changes from `${...BucketName-parameter}` to
  `!Ref EvalBucket` / `!Ref ResultsBucket`.
- We are **not** changing the three existing Lambda handlers
  (`start_eval_job`, `check_eval_status`, `parse_eval_results`) or their
  unit tests — they already read S3 URIs from the event payload, so the
  bucket migration is transparent to them.
- We are **not** removing the `PromptTemplatePrefix` parameter. It is still
  useful (lets users widen or narrow the trigger), and removing it would
  break the `KbSyncCompletionRule` / `PromptTemplateChangeRule` API for
  users who already deployed with a custom prefix.
- We are **not** retaining backwards-compatibility hooks (e.g. an
  `ExistingEvalBucketName` override parameter). The workshop is a fresh
  install every time; adding a "bring your own bucket" branch would
  approximately double the conditional surface area for zero workshop value.
  Documented as an intentional constraint, not an oversight.
- We are **not** deleting `evaluation/scripts/upload_prompt_template.py`.
  It is repurposed (not retired) into a workshop demo helper that resolves
  the eval bucket name from the CFN stack output. The legacy
  positional-`<bucket>` invocation is replaced by an auto-resolving
  default; an explicit `--bucket` flag is retained as an escape hatch.
- We are **not** building a second "upload-dataset" or "upload-thresholds"
  demo script. The seed Lambda already plants those assets on Create, and
  re-uploading them is not a teaching moment we need (only prompt-template
  changes are part of the demo flow).

## Constraints

- **Bucket lifecycle coupled to the stack.** `sam delete` empties and
  removes both eval and results buckets. For a workshop this is correct;
  any future production fork would need to revisit this (likely by setting
  `DeletionPolicy: Retain` on the buckets and removing the empty-on-delete
  branch from the custom resource Lambda). Call this out in
  documentation so a future contributor does not strip the empty-on-delete
  path "for safety" and break workshop teardown.
- **Globally-unique bucket names required.** Mirror the
  `kb_provisioning/` convention exactly:
  `!Sub "${AWS::StackName}-eval-${AWS::AccountId}-${AWS::Region}"` and
  `!Sub "${AWS::StackName}-eval-results-${AWS::AccountId}-${AWS::Region}"`.
  This is deterministic per account/region/stack-name and short enough to
  stay under the 63-char S3 limit for sane stack names.
- **CFN custom resource response contract.** The seed Lambda MUST always
  PUT a response to `event["ResponseURL"]` — success or failure — or
  CloudFormation hangs for an hour and the stack rolls back. The
  `kb_provisioning/lambdas/seed_and_ingest/handler.py` `send_cfn_response`
  function is the reference implementation; reuse its shape verbatim.
- **Stack output `EvalBucketName` is part of the public API of this stack.**
  The repurposed `upload_prompt_template.py` reads it via
  `cloudformation:DescribeStacks`, so the export name
  (`!Sub "${AWS::StackName}-EvalBucketName"`) and the output's
  `Description` field become a contract: do not rename or remove the
  output once shipped.
- **Python 3.13 runtime, no external deps in the Lambda package.** The
  Lambda must use only the standard library plus the boto3 already in the
  Python 3.13 Lambda runtime — matching the convention used by every other
  Lambda in this repo. Tests live in `evaluation/requirements-dev.txt`
  (pytest, pytest-mock, pytest-cov), not in the Lambda package.
- **Region pinning.** The state machine, EventBridge rules, and SNS topic
  all live in `us-east-1` per `evaluation/samconfig.toml`. The new buckets
  must be created in the same region; the existing Lambda handlers
  hardcode `region_name="us-east-1"` for boto3 clients and any cross-region
  S3 would break them.
- **Pre-build asset copy step is mandatory.** Just like
  `kb_provisioning/scripts/prepare_lambda_assets.py`, attendees must run
  `python evaluation/scripts/prepare_lambda_assets.py` before `sam build`,
  or the seed files will not be packaged into the Lambda. This is a
  documented manual step; do not attempt to invoke it from inside the SAM
  template or from a Makefile-only path (the workshop uses raw `sam build`).
- **EventBridge bus must match.** The eval bucket's EventBridge
  notifications fire on the default event bus in the same region; the
  `PromptTemplateChangeRule` already targets the default bus implicitly.
  No `EventBusName:` override is required; do not add one.
- **`upload_prompt_template.py` must remain stdlib + boto3 only.** It
  runs from an attendee's machine in the workshop venv; no new
  third-party dependencies (no click, no typer) — match the existing
  argparse-based style in `evaluation/scripts/setup_s3.py` /
  `upload_prompt_template.py`.

## Prior Art

- **`kb_provisioning/template.yaml`** — provisions its own `SourceBucket`
  with `NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled:
  true`, uses an auto-naming `!If [HasSourceBucketName, !Ref Override,
  !Sub "${AWS::StackName}-source-${AWS::AccountId}-${AWS::Region}"]` pattern,
  and runs a custom resource Lambda to seed + empty the bucket. This is the
  direct architectural template for the new feature; mirror it.
- **`kb_provisioning/lambdas/seed_and_ingest/handler.py`** — reference
  implementation of a CFN custom resource Lambda that uploads seed files on
  Create and empties the bucket on Delete. Reuse the
  `send_cfn_response()` helper, the `empty_bucket()` paginator pattern,
  and the never-raise error-handling envelope.
- **`kb_provisioning/scripts/prepare_lambda_assets.py`** — reference
  pre-build helper that copies seed files into the Lambda's `CodeUri/`
  directory before `sam build`. Mirror its argument-free, idempotent shape.
- **`kb_provisioning/tests/test_seed_and_ingest.py` and `conftest.py`** —
  reference test layout: `importlib.util.spec_from_file_location` to load
  the handler by absolute path, `make_cfn_event()` factory in conftest,
  and one test class per lifecycle method
  (`TestCreateRequest`, `TestUpdateRequestNoOp`,
  `TestUpdateRequestWithChanges`, `TestDeleteRequest`,
  `TestSendCfnResponse`, `TestErrorHandling`).
- **`evaluation/tests/test_start_eval_job.py:10-19`** — the existing
  `importlib.util` handler-loading idiom that the new test module must use.
- **`evaluation/template.yaml:514-520, 554-560`** — the EventBridge rule
  `Input:` JSON shape the state machine consumes. The four-key contract
  (`rag_dataset_s3_uri`, `rag_output_s3_uri`, `thresholds_s3_uri`,
  `prompt_template_s3_uri`) must not change; only the bucket portion of
  each URI changes.
- **`evaluation/scripts/setup_s3.py`** — the legacy bulk-seed workflow
  being retired. The S3 keys it wrote (`datasets/rag_eval.jsonl`,
  `baselines/thresholds.json`) are the canonical keys the new custom
  resource must write to.
- **`evaluation/scripts/upload_prompt_template.py` (current)** — the
  argparse + boto3 shape and the `prompts/kb_prompt_template.txt`
  destination key. The new version keeps both, swaps the positional
  `<bucket>` argument for an optional `--bucket` flag, and adds a
  `--stack-name` flag that defaults to `rag-eval-pipeline` (matching
  `evaluation/samconfig.toml:11`).
