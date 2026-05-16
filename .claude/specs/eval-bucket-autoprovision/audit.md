# Audit: eval-bucket-autoprovision

## Requirements Checklist

Traces every Goal and Success Criterion from `intent.md` to an
implementation artifact. Status updated by sdd-auditor on 2026-05-10.

| ID  | Requirement | Source | Status | Notes |
|---|---|---|---|---|
| R1  | `sam deploy` succeeds on a fresh AWS account with no pre-existing buckets (only the SAM artifact bucket via `resolve_s3 = true`). | intent.md Goal 1, Success Criterion 1 | NOT VERIFIED | Requires live deploy. Template structure is correct; nothing in the static surface blocks this, but only a real `sam deploy` can confirm. |
| R2  | Eval and results buckets are CloudFormation-managed resources with auto-generated names following the `${StackName}-<purpose>-${AccountId}-${Region}` convention. | intent.md Goal 2 | PASS | Verified: `evaluation/template.yaml:221` `BucketName: !Sub "${AWS::StackName}-eval-${AWS::AccountId}-${AWS::Region}"` and `:231` `BucketName: !Sub "${AWS::StackName}-eval-results-${AWS::AccountId}-${AWS::Region}"`. Matches `kb_provisioning/` convention exactly. |
| R3  | Eval bucket has `NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled: true` at create time. | intent.md Goal 3, Success Criterion 3 | PASS | Verified: `template.yaml:222-224`. End-to-end EventBridge fire requires live deploy. |
| R4  | On stack create, the custom resource Lambda uploads all three seed files to canonical S3 keys. | intent.md Goal 4, Success Criterion 2 | PASS | `TestCreateRequest::test_uploads_three_seed_files`, `::test_uploads_to_canonical_s3_keys` (verifies `datasets/rag_eval.jsonl`, `baselines/thresholds.json`, `prompts/kb_prompt_template.txt` keys are written to `EvalBucket`). Byte-identicality vs source files is live-deploy only. |
| R5  | On stack delete, the custom resource empties both eval and results buckets. | intent.md Goal 5, Success Criterion 6 | PASS | `TestDeleteRequest::test_empties_both_buckets` proves the Lambda loops over both buckets and calls `list_objects_v2` + `delete_objects`. Live `sam delete` verification deferred. |
| R6  | `evaluation/samconfig.toml` `parameter_overrides` no longer contains `EvalBucketName`, `ResultsBucketName`, or `PromptTemplateBucketName`. | intent.md Goal 6 | PASS | `grep -oE "[A-Z][A-Za-z]+=" evaluation/samconfig.toml \| sort -u` returns exactly the seven non-bucket keys (KnowledgeBaseId, EvalRoleArn, BedrockModelId, EvaluatorModelId, NotificationEmail, MaxPollingIterations, PromptTemplatePrefix). |
| R7  | `evaluation/scripts/setup_s3.py` is deleted. | intent.md Goal 7, Success Criterion 8 | PASS | `test -f evaluation/scripts/setup_s3.py` returns ABSENT. Only references remaining are in `.claude/specs/` (expected, those are historical). |
| R8  | `evaluation/scripts/upload_prompt_template.py` is kept but upgraded: invoking it with no positional argument resolves the eval bucket from the CFN stack output. | intent.md Goal 7, Success Criterion 5 | PASS | Script rewritten; `resolve_eval_bucket()` helper exists; argparse default flow covered by `TestMain::test_resolves_from_stack_when_no_bucket_flag`. Live workshop end-to-end deferred. |
| R9  | `CLAUDE.md` "Evaluation pipeline" section reflects the new deploy workflow (prepare → build → deploy) and the new demo workflow. | intent.md Goal 8 | PASS | `CLAUDE.md:55-81` updated. References `prepare_lambda_assets.py` before `sam build`, includes the "Retrigger the pipeline (workshop demo)" subsection, and notes that `sam delete` empties both buckets. No references to `setup_s3.py` remain. |
| R10 | Bucket names are deterministic per `(StackName, AccountId, Region)`; no collisions across accounts. | intent.md Success Criterion 7 | PASS | Pure consequence of the `!Sub` template; verified by inspection. Max bucket name `rag-eval-pipeline-eval-results-123456789012-us-east-1` is 53 chars (under the 63-char S3 limit). |
| R11 | All three existing Lambda unit test files pass without modification. | intent.md Success Criterion 9 | PASS | `pytest evaluation/tests/` — 107 passed; `test_start_eval_job.py` (15), `test_check_eval_status.py` (22), `test_parse_eval_results.py` (35) all green. |
| R12 | `evaluation/tests/test_seed_eval_assets.py` exists with the six documented test classes covering Create, Update (no-op + with-changes), Delete, error handling, CFN-response shape. | intent.md Success Criterion 10 | PASS | Six classes present + bonus `TestModuleConstants`: TestCreateRequest, TestUpdateRequestNoOp, TestUpdateRequestWithChanges, TestDeleteRequest, TestSendCfnResponse, TestErrorHandling, TestModuleConstants. 22 tests, all green. (See "Test Coverage Honesty" notes below.) |
| R13 | Bucket lifecycle is intentionally coupled to the stack (no `DeletionPolicy: Retain`). Documentation calls this out. | intent.md Constraint "Bucket lifecycle coupled to the stack" | PASS | `template.yaml:218-231` — no `DeletionPolicy` key on either bucket (CFN default is `Delete`). Comment block in `handler.py:10-14` calls out the convention and warns future maintainers. |
| R14 | Lambda runtime uses only stdlib + boto3 (no `requirements.txt` in the Lambda CodeUri). | intent.md Constraint "Python 3.13 runtime, no external deps" | PASS | `ls evaluation/lambdas/seed_eval_assets/requirements.txt` returns "No such file or directory". Imports in `handler.py` are `json`, `os`, `urllib.request`, `typing.Any`, `boto3` only. |
| R15 | All new resources deploy to the same region as the existing stack (`us-east-1`). | intent.md Constraint "Region pinning" | PASS | `samconfig.toml:12,32` both `us-east-1`. `upload_prompt_template.py` `--region` default is `us-east-1`. Lambda passes `Region` property through to boto3 client. |
| R16 | `prepare_lambda_assets.py` is a separate documented pre-build step (not invoked from inside the SAM template). | intent.md Constraint "Pre-build asset copy step is mandatory" | PASS | Standalone Python script with `if __name__ == "__main__": main()`. No `Makefile` rule or SAM `Metadata.BuildMethod` hook. `CLAUDE.md:65-66` documents the manual step. |
| R17 | `upload_prompt_template.py` uses only argparse + boto3 (no click / typer). | intent.md Constraint "stdlib + boto3 only" | PASS | Imports: `argparse`, `os`, `typing.Any`, `boto3`. |

## Contract Compliance

Traces every Guarantee (G1-G13) and every Interface promise from
`contract.md` to a verifying test or inspection step.

| ID   | Contract Item | Status | Verified By |
|---|---|---|---|
| C1   | New CFN resources: `EvalBucket`, `ResultsBucket`, `SeedEvalAssetsFunctionRole`, `SeedEvalAssetsFunction`, `SeedEvalAssetsCustomResource` exist in `evaluation/template.yaml`. | PASS | Template inspection: `EvalBucket:218`, `ResultsBucket:228`, `SeedEvalAssetsFunctionRole:236`, `SeedEvalAssetsFunction:277`, `SeedEvalAssetsCustomResource:292`. `sam validate` not run (no AWS creds). |
| C2   | New CFN outputs `EvalBucketName` and `ResultsBucketName` exist with the documented `Export.Name` and `OutputKey`. | PASS | `template.yaml:660-673`. `OutputKey: EvalBucketName`, `Export.Name: !Sub "${AWS::StackName}-EvalBucketName"`; same for ResultsBucketName. |
| C3   | Three parameters (`EvalBucketName`, `ResultsBucketName`, `PromptTemplateBucketName`) are removed from `Parameters:`. | PASS | `template.yaml:11-58` — only 7 parameters remain (KnowledgeBaseId, EvalRoleArn, BedrockModelId, EvaluatorModelId, NotificationEmail, MaxPollingIterations, PromptTemplatePrefix). |
| C4   | Lambda handler API: `handler`, `upload_seed_assets`, `empty_bucket`, `send_cfn_response` exist with the documented signatures. | PASS | `handler.py:44, 110, 128, 160`. Signatures match contract.md. |
| C5   | `SEED_FILES` constant has exactly three tuples and matches the canonical S3 keys. | PASS | `TestModuleConstants::test_seed_files_value` asserts the literal three-tuple list matches contract. |
| C6   | `_TRACKED_KEYS = ("EvalBucketName", "ResultsBucketName")`. | PASS | `TestModuleConstants::test_tracked_keys_value`. |
| C7   | `prepare_lambda_assets.py` `main()` copies exactly three files to `seed_assets/`. | PASS | `prepare_lambda_assets.py:28-41` defines three (src, dest) pairs and iterates. Verified by directory listing: `evaluation_dataset.jsonl`, `kb_prompt_template.txt`, `thresholds.json` all present in `seed_assets/`. (No unit test, per audit C17 design choice.) |
| C8   | `upload_prompt_template.py`: `main()` and `resolve_eval_bucket(cfn_client, stack_name)` exist with documented signatures and defaults. | PASS | `TestResolveEvalBucket` (5 tests), `TestMain::test_argparse_defaults`, `test_region_default_is_us_east_1`. |
| C9   | Five `!Ref`/`!Sub` references migrated per contract.md table. | PASS | `template.yaml:70` (`EVAL_BUCKET_NAME: !Ref EvalBucket`), `:115-118` (S3ReadPermissions `!GetAtt` ARNs), `:584-590` (KbSync `Input` uses `${EvalBucket}`/`${ResultsBucket}`), `:615` (`PromptTemplateChangeRule.EventPattern.detail.bucket.name: !Ref EvalBucket`), `:624-630` (PromptTemplateChange `Input` uses `${EvalBucket}`/`${ResultsBucket}`). All four canonical S3 URIs (`datasets/rag_eval.jsonl`, `results/rag/`, `baselines/thresholds.json`, `prompts/kb_prompt_template.txt`) present in both rules. |
| C10  | G1: post-deploy, eval bucket contains the three canonical objects byte-identical to source files. | NOT VERIFIED | Requires live deploy. Static test (`test_uploads_to_canonical_s3_keys`) confirms keys/buckets but uses synthetic file contents in `tmp_path`. The upload pipe is `open(local, "rb").read() → put_object(Body=...)`, so byte-identicality is structurally guaranteed once `prepare_lambda_assets.py` has run. |
| C11  | G2: post-deploy, `aws s3api get-bucket-notification-configuration --bucket <eval>` returns `EventBridgeConfiguration: {}`. | NOT VERIFIED | Requires live deploy. Template surface verified at C9. |
| C12  | G3: state machine `Input:` JSON matches the pre-feature JSON shape (only bucket name differs). | PASS | The four-key contract (`rag_dataset_s3_uri`, `rag_output_s3_uri`, `thresholds_s3_uri`, `prompt_template_s3_uri`) and the four canonical S3 keys (`datasets/rag_eval.jsonl`, `results/rag/`, `baselines/thresholds.json`, `prompts/kb_prompt_template.txt`) are byte-identical to the spec in both `KbSyncCompletionRule.Targets[0].Input` and `PromptTemplateChangeRule.Targets[0].Input`. Verified by `template.yaml:584-590, 624-630`. |
| C13  | G4: `sam delete` succeeds against a populated stack. | NOT VERIFIED | Requires live deploy with Bedrock-written `results/rag/*` data. Lambda Delete logic covered by unit tests. |
| C14  | G5: `(StackName, AccountId, Region)` triple determines the bucket name. | PASS | Pure `!Sub` substitution; verified at R2. |
| C15  | G6: `handler()` always sends a CFN response; never raises. | PASS | `TestErrorHandling::test_handler_never_raises`, `test_failed_on_s3_put_denial`, `test_failed_on_delete_denial`, `test_unknown_request_type_sends_failed`. All four exception paths fire `send_cfn_response` with `Status: "FAILED"` and return a dict without raising. The handler's outer `try/except Exception` envelope at `handler.py:61, 97-107` covers any failure. |
| C16  | G7: IAM role grants `s3:PutObject` / `s3:DeleteObject` only on the two named bucket ARNs (no wildcards). | PASS | `template.yaml:236-272`. `EvalBucketWriteAccess` Resource is `!GetAtt EvalBucket.Arn` + `${EvalBucket.Arn}/*`. `ResultsBucketEmptyOnDelete` Resource is `!GetAtt ResultsBucket.Arn` + `${ResultsBucket.Arn}/*`. No `"*"` wildcards on the bucket portion. (Note: `ResultsBucketEmptyOnDelete` has `s3:DeleteObject` and `s3:ListBucket` — sufficient for the empty-on-delete path.) |
| C17  | G8: `prepare_lambda_assets.py` is idempotent. | PASS by inspection | `shutil.copy2` is overwrite-by-default; no state outside the destination files; no unit test (per spec note "Test optional"). Spot-checked by re-running was not part of this audit. |
| C18  | G9: existing Lambda tests pass without modification. | PASS | 107/107 pytest pass; the three existing handler test files unchanged (verified via filesystem mtimes and inspection). |
| C19  | G10: `samconfig.toml` `parameter_overrides` has exactly seven keys after this feature lands. | PASS | `grep -oE "[A-Z][A-Za-z]+=" evaluation/samconfig.toml \| sort -u \| wc -l` returns 7. |
| C20  | G11: `python upload_prompt_template.py` with no args succeeds and triggers a new Step Functions execution within ~30 seconds. | NOT VERIFIED | Requires live deploy. Unit tests cover the resolve + upload flow. |
| C21  | G12: `Outputs.EvalBucketName.Export.Name == "${AWS::StackName}-EvalBucketName"` and `OutputKey == "EvalBucketName"`. | PASS | `template.yaml:660, 667`. |
| C22  | G13: `evaluation/scripts/setup_s3.py` does not exist. | PASS | `test -f` returns false. No live references anywhere (only in `.claude/specs/`). |
| C23  | Error contract: missing seed file → `print` warning; missing `EvalBucketName` output in stack → friendly `KeyError`; etc. | PASS | `TestCreateRequest::test_skips_missing_files` (warns, no failure, FilesUploaded=="1"), `TestResolveEvalBucket::test_raises_key_error_when_output_missing` (KeyError), `test_raises_runtime_error_when_stack_not_found` (RuntimeError with hint), `test_raises_runtime_error_when_stacks_list_is_empty`. |
| C24  | Lambda has no external `requirements.txt`; uses only `boto3` (runtime-provided) and stdlib. | PASS | `ls` confirms no `requirements.txt` under `evaluation/lambdas/seed_eval_assets/`. `handler.py` imports: `json`, `os`, `urllib.request`, `typing.Any`, `boto3`. |
| C25  | `upload_prompt_template.py` `--region` default is `"us-east-1"` (fix from current stale `"us-east-2"`). | PASS | `upload_prompt_template.py:95`. Asserted by `TestMain::test_region_default_is_us_east_1` and `test_argparse_defaults`. |

## Test Coverage

Maps each behavior guarantee and each handler branch to a concrete test.

| ID   | Test Description | Status | Test File |
|---|---|---|---|
| T1   | Seed Lambda Create uploads three files (canonical keys) to the EvalBucket. | PASS | `evaluation/tests/test_seed_eval_assets.py::TestCreateRequest::test_uploads_three_seed_files`, `::test_uploads_to_canonical_s3_keys` |
| T2   | Seed Lambda Create returns `Data: {"FilesUploaded": "3"}` when all three seed files are present. | PASS | `test_seed_eval_assets.py::TestCreateRequest::test_files_uploaded_count` |
| T3   | Seed Lambda Create skips missing seed files (only one present → `FilesUploaded == "1"`, no exception). | PASS | `test_seed_eval_assets.py::TestCreateRequest::test_skips_missing_files` |
| T4   | Seed Lambda Create does NOT call any `bedrock-agent` API. | PASS (weak assertion) | `test_seed_eval_assets.py::TestCreateRequest::test_no_bedrock_calls`. The assertion `mock_bedrock.start_ingestion_job.assert_not_called()` references a MagicMock that the handler never even touches — a no-op assertion. The structural protection comes from the handler never importing or instantiating `bedrock-agent`; the test is effectively a docstring. Acceptable as a guard but is coverage-only in style. |
| T5   | Seed Lambda Update with identical tracked properties: no S3 calls, SUCCESS, empty data. | PASS | `test_seed_eval_assets.py::TestUpdateRequestNoOp::test_no_calls_when_unchanged` |
| T6   | Seed Lambda Update with changed `EvalBucketName`: re-uploads to the new bucket. | PASS | `test_seed_eval_assets.py::TestUpdateRequestWithChanges::test_re_uploads_on_eval_bucket_change` |
| T7   | Seed Lambda Update with changed `ResultsBucketName`: re-uploads. | PASS | `test_seed_eval_assets.py::TestUpdateRequestWithChanges::test_re_uploads_on_results_bucket_change` |
| T8   | Seed Lambda Delete: paginated `list_objects_v2` + batched `delete_objects` for both buckets. | PASS | `test_seed_eval_assets.py::TestDeleteRequest::test_empties_both_buckets`. Asserts `delete_objects.call_count == 1` (for the non-empty page); the test correctly verifies the per-page batch and the both-bucket loop via the paginator-side-effect counter. |
| T9   | Seed Lambda Delete: no `bedrock-agent` calls. | PASS (weak assertion) | `test_seed_eval_assets.py::TestDeleteRequest::test_no_bedrock_calls`. Like T4, the assertion relies on a MagicMock attribute the handler never touches. Structurally guarded by the import set. |
| T10  | Seed Lambda Delete: empty bucket is a no-op (no `delete_objects` call). | PASS | `test_seed_eval_assets.py::TestDeleteRequest::test_empty_bucket_is_noop` |
| T11  | `send_cfn_response`: PUTs to `event["ResponseURL"]` with the right body shape. | PASS | `test_seed_eval_assets.py::TestSendCfnResponse::test_body_shape`, `::test_puts_to_response_url` |
| T12  | `send_cfn_response` with `status="FAILED"` includes the reason string in the body. | PASS | `test_seed_eval_assets.py::TestSendCfnResponse::test_failed_includes_reason` |
| T13  | Seed Lambda emits `FAILED` when `s3:PutObject` raises during Create. | PASS | `test_seed_eval_assets.py::TestErrorHandling::test_failed_on_s3_put_denial` |
| T14  | Seed Lambda emits `FAILED` when `s3:ListBucket` raises during Delete. | PASS | `test_seed_eval_assets.py::TestErrorHandling::test_failed_on_delete_denial` |
| T15  | Seed Lambda `handler()` never raises (any internal exception → returns normally with FAILED). | PASS | `test_seed_eval_assets.py::TestErrorHandling::test_handler_never_raises`, `::test_unknown_request_type_sends_failed` |
| T16  | Module-level constants: `SEED_FILES` and `_TRACKED_KEYS` match the contract spec. | PASS | `test_seed_eval_assets.py::TestModuleConstants::test_seed_files_value`, `::test_tracked_keys_value`, `::test_seed_assets_dir_is_under_handler_dir` |
| T17  | `resolve_eval_bucket()` returns the bucket name when the stack output is present. | PASS | `test_upload_prompt_template.py::TestResolveEvalBucket::test_returns_bucket_when_output_present` |
| T18  | `resolve_eval_bucket()` raises `RuntimeError` with a friendly hint when the stack does not exist. | PASS | `test_upload_prompt_template.py::TestResolveEvalBucket::test_raises_runtime_error_when_stack_not_found`, `::test_raises_runtime_error_hint_contains_stack_name`, `::test_raises_runtime_error_when_stacks_list_is_empty` |
| T19  | `resolve_eval_bucket()` raises `KeyError` when the stack exists but `EvalBucketName` output is missing. | PASS | `test_upload_prompt_template.py::TestResolveEvalBucket::test_raises_key_error_when_output_missing` |
| T20  | `upload_prompt_template.py` `main()` honors `--bucket` and skips the stack lookup. | PASS (weak assertion) | `test_upload_prompt_template.py::TestMain::test_bucket_flag_skips_stack_lookup`. The docstring says "no cloudformation client was used", but the assertions only check `mock_s3.upload_file.assert_called_once()` and `call_args[0][1] == "explicit-bucket"`. A buggy implementation that called CFN anyway would not be caught (the boto3.client patch returns the same `mock_s3` for any service). MEDIUM severity — should assert e.g. `mock_s3.describe_stacks.assert_not_called()`, or use `side_effect` to track service names. |
| T21  | `upload_prompt_template.py` `main()` resolves bucket from stack output when no `--bucket` is provided. | PASS | `test_upload_prompt_template.py::TestMain::test_resolves_from_stack_when_no_bucket_flag`. Uses `boto3.client` side_effect to return CFN then S3 in order; verifies `describe_stacks` was called and `upload_file` got the resolved bucket. |
| T22  | `upload_prompt_template.py` uploads to key `<prefix>kb_prompt_template.txt`. | PASS | `test_upload_prompt_template.py::TestMain::test_uploads_to_canonical_key`. Asserts the key ends with `kb_prompt_template.txt` and contains `prompts`. Does NOT pin the exact key `"prompts/kb_prompt_template.txt"`. |
| T23  | `upload_prompt_template.py` argparse defaults: `--region == "us-east-1"`, `--stack-name == "rag-eval-pipeline"`, `--prefix == "prompts/"`. | PASS (indirect) | `test_upload_prompt_template.py::TestMain::test_argparse_defaults` — but this test constructs a fresh `argparse.ArgumentParser` inline rather than introspecting the script's actual parser. The defaults match the contract, but a regression where the script's own parser drifts would not be caught here. `test_region_default_is_us_east_1` exercises the real script's region default end-to-end, so the gap is partially covered. MEDIUM severity. |
| T24  | (Regression) `pytest evaluation/tests/test_start_eval_job.py` passes. | PASS | All 15 tests pass. |
| T25  | (Regression) `pytest evaluation/tests/test_check_eval_status.py` passes. | PASS | All 22 tests pass. |
| T26  | (Regression) `pytest evaluation/tests/test_parse_eval_results.py` passes. | PASS | All 35 tests pass. |
| T27  | (Static) `sam validate -t evaluation/template.yaml` (from `evaluation/`) succeeds with no errors. | NOT VERIFIED | Not run — no AWS creds in this environment. Manual deploy verification needed. |
| T28  | (Static) `cfn-lint evaluation/template.yaml` passes if available (best-effort). | NOT VERIFIED | Not run in this environment. |
| T29  | (Manual) End-to-end smoke test: prepare → build → deploy → verify S3 objects → run `upload_prompt_template.py` → see Step Functions execution start → `sam delete`. | NOT VERIFIED | Live deploy required. |
| T30  | New: `prepare_lambda_assets.py` idempotency / coverage. | MISSING | No unit test exercises the prepare script. Spec marked this optional (audit row C17), so this is a deliberate gap, not a regression. Documenting for clarity. |

## Audit Log

| Date | Auditor | Finding | Severity | Resolution |
|---|---|---|---|---|
| 2026-05-10 | sdd-auditor | Template structure, IAM, EventBridge config, S3 keys, and Outputs match the contract verbatim. All 107 tests pass. | n/a | No action needed. |
| 2026-05-10 | sdd-auditor | `TestMain::test_bucket_flag_skips_stack_lookup` docstring promises to verify CFN was not called, but the assertions only check the bucket value. A buggy implementation that called CFN anyway would still pass the test. | MEDIUM | Strengthen by capturing service names through a `side_effect` capture function (the pattern already used in `test_region_default_is_us_east_1`). |
| 2026-05-10 | sdd-auditor | `TestCreateRequest::test_no_bedrock_calls` and `TestDeleteRequest::test_no_bedrock_calls` assert against a MagicMock that the handler never touches — they are effectively no-ops. The structural guard (handler does not import `bedrock-agent`) is what actually enforces the property. | LOW | Coverage-only style. Either remove the tests or replace with `assert "bedrock-agent" not in [c.args[0] for c in boto3_calls]` using a side_effect capture. Not blocking. |
| 2026-05-10 | sdd-auditor | `TestMain::test_argparse_defaults` constructs its own parser instead of importing the script's parser — it asserts a duplicate of the contract but not the actual script. `test_region_default_is_us_east_1` partly compensates. | MEDIUM | Add a regression test that calls `main()` with `patch.object(_mod, "argparse")` or inspects the real parser via `parser.parse_args([])` from inside the script. Alternatively factor the argparse setup into a `build_parser()` function the test can import. Not blocking. |
| 2026-05-10 | sdd-auditor | `prepare_lambda_assets.py` has no unit test. Per spec audit row C17 this was an explicit "optional" choice. | LOW | Acceptable per spec. Idempotency is structural (shutil.copy2 overwrite + no state). |
| 2026-05-10 | sdd-auditor | `urllib.request.urlopen` is called at module-import time of `urllib` (not, but `req.full_url` is checked in `test_puts_to_response_url`). The mocking pattern is sound. | n/a | No action. |
| 2026-05-10 | sdd-auditor | The `upload_prompt_template.py` key construction uses `f"{args.prefix.rstrip('/')}/kb_prompt_template.txt"`. With the default `--prefix "prompts/"` this yields `"prompts/kb_prompt_template.txt"` correctly; with an empty `--prefix ""` it would yield `"/kb_prompt_template.txt"` (leading slash). | LOW | The contract default is `"prompts/"`, so this is only triggered by explicit user misuse. Optional hardening: `if args.prefix: key = f"{args.prefix.rstrip('/')}/kb_prompt_template.txt" else: key = "kb_prompt_template.txt"`. Not blocking. |
| 2026-05-10 | sdd-auditor | The `SeedEvalAssetsCustomResource` does not have an explicit `DependsOn` for the `LambdaExecutionRole` or for the `KbSyncCompletionRule` / `PromptTemplateChangeRule`. CloudFormation's implicit ordering via `!GetAtt SeedEvalAssetsFunction.Arn` handles the role/Lambda chain, and the EventBridge rules pointing at the same buckets do not need to wait for the seed. Acceptable. | n/a | No action. |
| 2026-05-10 | sdd-auditor | `sam validate` not run (no AWS creds). All deploy-time success criteria (R1, C10, C11, C13, C20, T27-T29) remain NOT VERIFIED. | INFO | Live deploy required to close the loop. |

## Final Verdict

**Status**: APPROVED WITH RESERVATIONS

**Summary**: All static contract items pass; 107/107 unit tests pass; template, IAM, EventBridge config, S3 URI contract, stack outputs, and CLAUDE.md documentation match the spec exactly. The only outstanding items are deploy-time guarantees that cannot be checked without AWS credentials, and three test-quality observations where the asserts are weaker than the docstrings suggest. No CRITICAL or HIGH defects.

**Critical Issues** (must fix before merge):
- None.

**Warnings** (should fix, not blocking):
- W1: `TestMain::test_bucket_flag_skips_stack_lookup` does not actually verify CFN was skipped — the docstring promises behavior the assertions do not enforce. Tighten the assertion using the `boto3.client` side_effect capture pattern already used by `test_region_default_is_us_east_1`. (MEDIUM)
- W2: `TestMain::test_argparse_defaults` builds its own parser instead of exercising the script's actual parser. The script's true defaults are only indirectly covered via `test_region_default_is_us_east_1`. Add a test that drives the real `main()` with `sys.argv` containing no flags (and `--bucket` to short-circuit network calls) to pin the defaults. (MEDIUM)
- W3: `TestCreateRequest::test_no_bedrock_calls` and `TestDeleteRequest::test_no_bedrock_calls` assert against an unrelated MagicMock — they always pass regardless of implementation. Either remove them or convert to a check of the boto3.client service names used. (LOW)

**Recommendations** (nice to have):
- R1 (audit): Strengthen the upload-script key construction to handle an empty `--prefix` value without producing a leading slash (`"/kb_prompt_template.txt"`). Today this is only triggered by explicit user misuse, so not blocking.
- R2 (audit): Add a tiny unit test for `prepare_lambda_assets.py` using `tmp_path` mock source/dest directories and verifying byte-identical re-copy on second invocation (covers G8 idempotency explicitly).
- R3 (audit): Run `sam validate -t evaluation/template.yaml` (and ideally `cfn-lint`) at least once before the workshop to surface any SAM-level typos that this audit cannot catch.

**Deferred to live-deploy verification** (cannot be checked without AWS credentials):
- R1: `sam deploy` reaches `CREATE_COMPLETE` on a fresh account.
- C10: byte-identical seed-file content lands at the canonical keys.
- C11: `aws s3api get-bucket-notification-configuration` returns `EventBridgeConfiguration: {}`.
- C13: `sam delete` succeeds with Bedrock-written objects in `ResultsBucket`.
- C20 / G11: `upload_prompt_template.py` triggers a Step Functions execution within ~30s.
- T27 / T28: `sam validate`, `cfn-lint` static checks.
- T29: full end-to-end smoke test.
