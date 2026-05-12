# Tasks: eval-bucket-autoprovision

## Legend

- [ ] Not started
- [x] Completed
- [~] In progress
- [!] Blocked

## Phase 1: Foundation — seed Lambda + pre-build helper

- [x] Task 1.1: Create directory `evaluation/lambdas/seed_eval_assets/` with an
      empty `__init__.py` (mirrors the layout of the three existing Lambda
      dirs). — `evaluation/lambdas/seed_eval_assets/__init__.py`
- [x] Task 1.2: Create `evaluation/lambdas/seed_eval_assets/seed_assets/.gitkeep`
      so the directory survives in git when the seed files are gitignored. —
      `evaluation/lambdas/seed_eval_assets/seed_assets/.gitkeep`
- [x] Task 1.3: Port `handler.py` from
      `kb_provisioning/lambdas/seed_and_ingest/handler.py`. Adaptations:
      - Replace `SEED_DATA_DIR` with `SEED_ASSETS_DIR`.
      - Define `SEED_FILES: list[tuple[str, str]]` with the three canonical
        (local_filename, s3_key) pairs from contract.md.
      - Replace `_TRACKED_KEYS` with `("EvalBucketName", "ResultsBucketName")`.
      - Replace `upload_seed_data(s3_client, bucket, prefix)` with
        `upload_seed_assets(s3_client, bucket)` that iterates `SEED_FILES`
        (no prefix parameter — the prefix is encoded in each tuple).
      - Remove `start_ingestion()` and all `bedrock-agent` references.
      - Modify the `Delete` branch to loop over `[EvalBucketName,
        ResultsBucketName]` and call `empty_bucket()` for each.
      - Keep `send_cfn_response()` and `empty_bucket()` byte-identical to
        the reference (just renamed `physical_resource_id` default if
        appropriate).
      — `evaluation/lambdas/seed_eval_assets/handler.py`
- [x] Task 1.4: Create `evaluation/scripts/prepare_lambda_assets.py` mirroring
      `kb_provisioning/scripts/prepare_lambda_assets.py`. Set up the three
      source-to-dest path pairs in a list and iterate them with `shutil.copy2`.
      Print `Copied:` / `WARNING: source file not found` lines per the
      reference. — `evaluation/scripts/prepare_lambda_assets.py`
- [x] Task 1.5: Inspect `.gitignore` (root). If `kb_provisioning/lambdas/seed_and_ingest/seed_data/`
      is ignored, add a parallel rule for
      `evaluation/lambdas/seed_eval_assets/seed_assets/` (preserve `.gitkeep`).
      If `seed_data/` is **not** ignored, leave `.gitignore` alone. —
      `.gitignore`

## Phase 2: Core template wiring

- [x] Task 2.1: In `evaluation/template.yaml`, delete the three parameter
      blocks for `EvalBucketName`, `ResultsBucketName`,
      `PromptTemplateBucketName`. Keep `KnowledgeBaseId`, `EvalRoleArn`,
      `BedrockModelId`, `EvaluatorModelId`, `NotificationEmail`,
      `MaxPollingIterations`, `PromptTemplatePrefix`. —
      `evaluation/template.yaml`
- [x] Task 2.2: Update `Globals.Function.Environment.Variables.EVAL_BUCKET_NAME`
      from `!Ref EvalBucketName` to `!Ref EvalBucket`. —
      `evaluation/template.yaml`
- [x] Task 2.3: Add the `EvalBucket` resource (`AWS::S3::Bucket`) with
      `BucketName: !Sub "${AWS::StackName}-eval-${AWS::AccountId}-${AWS::Region}"`
      and `NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled:
      true`. — `evaluation/template.yaml`
- [x] Task 2.4: Add the `ResultsBucket` resource (`AWS::S3::Bucket`) with
      `BucketName: !Sub "${AWS::StackName}-eval-results-${AWS::AccountId}-${AWS::Region}"`.
      No notification config. — `evaluation/template.yaml`
- [x] Task 2.5: Update `LambdaExecutionRole.Policies.S3ReadPermissions.Resource`
      to use `!GetAtt EvalBucket.Arn`, `!Sub "${EvalBucket.Arn}/*"`,
      `!GetAtt ResultsBucket.Arn`, `!Sub "${ResultsBucket.Arn}/*"` — replacing
      the old `!Sub "arn:aws:s3:::${EvalBucketName}"` style references. —
      `evaluation/template.yaml`
- [x] Task 2.6: Add the `SeedEvalAssetsFunctionRole` (`AWS::IAM::Role`) with the
      `EvalBucketWriteAccess` and `ResultsBucketEmptyOnDelete` policy
      statements per contract.md. — `evaluation/template.yaml`
- [x] Task 2.7: Add the `SeedEvalAssetsFunction` (`AWS::Serverless::Function`)
      with `CodeUri: lambdas/seed_eval_assets/`, `Handler: handler.handler`,
      and `Role: !GetAtt SeedEvalAssetsFunctionRole.Arn`. —
      `evaluation/template.yaml`
- [x] Task 2.8: Add the `SeedEvalAssetsCustomResource`
      (`AWS::CloudFormation::CustomResource`) with
      `DependsOn: [EvalBucket, ResultsBucket]` and `ResourceProperties`
      `{EvalBucketName, ResultsBucketName, Region}`. —
      `evaluation/template.yaml`
- [x] Task 2.9: Update `KbSyncCompletionRule.Targets[0].Input` — replace
      `${EvalBucketName}` with `${EvalBucket}` and `${ResultsBucketName}`
      with `${ResultsBucket}` in the inline JSON. — `evaluation/template.yaml`
- [x] Task 2.10: Update `PromptTemplateChangeRule.EventPattern.detail.bucket.name`
      from `!Ref PromptTemplateBucketName` to `!Ref EvalBucket`. —
      `evaluation/template.yaml`
- [x] Task 2.11: Update `PromptTemplateChangeRule.Targets[0].Input` — same
      `${EvalBucketName}` → `${EvalBucket}` and `${ResultsBucketName}` →
      `${ResultsBucket}` substitution in the inline JSON. —
      `evaluation/template.yaml`
- [x] Task 2.12: Add `Outputs.EvalBucketName` and `Outputs.ResultsBucketName`
      with the exact `Export.Name` and `Description` from contract.md. —
      `evaluation/template.yaml`
- [!] Task 2.13: Run `sam validate -t evaluation/template.yaml` from the
      `evaluation/` directory and resolve any errors. — Skipped (no AWS creds / sam not in scope)

## Phase 3: Workshop scripts and samconfig

- [x] Task 3.1: Delete `evaluation/scripts/setup_s3.py`. —
      `evaluation/scripts/setup_s3.py`
- [x] Task 3.2: Rewrite `evaluation/scripts/upload_prompt_template.py`:
      - Argparse flags: `--bucket` (optional, no positional), `--stack-name`
        (default `"rag-eval-pipeline"`), `--region` (default `"us-east-1"`),
        `--prefix` (default `"prompts/"`), `--template` (default
        `evaluation/prompts/kb_prompt_template.txt` resolved relative to
        the script).
      - Function `resolve_eval_bucket(cfn_client, stack_name) -> str` that
        calls `cfn_client.describe_stacks(StackName=stack_name)` and finds
        `Outputs[?OutputKey == "EvalBucketName"].OutputValue`.
      - `main()` flow: parse args → if `--bucket`, use it; else
        `boto3.client("cloudformation", region_name=args.region)` →
        `resolve_eval_bucket(...)` → `boto3.client("s3", region_name=args.region)`
        → `upload_file(args.template, bucket, key)`.
      - Friendly error messages per contract.md error table.
      — `evaluation/scripts/upload_prompt_template.py`
- [x] Task 3.3: Update `evaluation/samconfig.toml` `parameter_overrides`:
      remove `EvalBucketName="..."`, `ResultsBucketName="..."`,
      `PromptTemplateBucketName="..."`. Keep the other seven keys. Verify
      `stack_name = "rag-eval-pipeline"` and `region = "us-east-1"`
      remain (these are the defaults `upload_prompt_template.py` assumes). —
      `evaluation/samconfig.toml`
- [x] Task 3.4: Update `CLAUDE.md` "Evaluation pipeline" section:
      - Replace `python evaluation/scripts/setup_s3.py <bucket-name> --region us-east-1`
        and `python evaluation/scripts/upload_prompt_template.py <bucket-name>`
        with a single line: `python evaluation/scripts/prepare_lambda_assets.py`.
      - Move the `prepare_lambda_assets.py` line to just before
        `sam build` (mirroring the kb_provisioning section).
      - Add a new short "Retrigger the pipeline (workshop demo)"
        subsection: `python evaluation/scripts/upload_prompt_template.py`
        (no args).
      - Add a note that `sam delete` now empties both buckets automatically.
      — `CLAUDE.md`

## Phase 4: Testing & validation

- [x] Task 4.1: Extend `evaluation/tests/conftest.py` with a
      `make_cfn_event(request_type, properties=None, old_properties=None,
      response_url=..., stack_id=..., request_id=..., logical_resource_id=...,
      physical_resource_id=...) -> dict` factory mirroring
      `kb_provisioning/tests/conftest.py:35-68`. Default `properties` =
      `{"EvalBucketName": "my-eval-bucket", "ResultsBucketName":
      "my-results-bucket", "Region": "us-east-1"}`. — `evaluation/tests/conftest.py`
- [x] Task 4.2: Add a `mock_cfn_client` fixture to
      `evaluation/tests/conftest.py` that returns a MagicMock with a default
      `describe_stacks` return value containing an `EvalBucketName` output. —
      `evaluation/tests/conftest.py`
- [x] Task 4.3: Write `evaluation/tests/test_seed_eval_assets.py` with all
      test classes from audit.md T1-T16:
      `TestCreateRequest`, `TestUpdateRequestNoOp`,
      `TestUpdateRequestWithChanges`, `TestDeleteRequest`,
      `TestSendCfnResponse`, `TestErrorHandling`, `TestModuleConstants`. Use
      the same `importlib.util.spec_from_file_location` handler-loading idiom
      as `evaluation/tests/test_start_eval_job.py:10-19`. —
      `evaluation/tests/test_seed_eval_assets.py`
- [x] Task 4.4: Write `evaluation/tests/test_upload_prompt_template.py` with
      `TestResolveEvalBucket` (T17-T19) and `TestMain` (T20-T23) test
      classes. — `evaluation/tests/test_upload_prompt_template.py`
- [x] Task 4.5: Run `pytest evaluation/tests/` and verify all tests pass
      (including the unchanged regression suite for the three existing
      handler tests). — 107 passed, 0 failed
- [x] Task 4.6: Run `python evaluation/scripts/prepare_lambda_assets.py` and
      verify it creates the three files under
      `evaluation/lambdas/seed_eval_assets/seed_assets/`. — Verified: 3 files copied
- [!] Task 4.7: Run `sam validate -t evaluation/template.yaml` (from
      `evaluation/`) one more time after all changes; verify no errors. —
      Skipped (sam build/deploy out of scope; no AWS creds)
- [!] Task 4.8: (Manual smoke test) In a clean AWS account / region:
      `python evaluation/scripts/prepare_lambda_assets.py`, then
      `cd evaluation && sam build && sam deploy --config-file samconfig.toml`.
      Verify `CREATE_COMPLETE`, verify S3 objects, verify EventBridge
      configuration. Then run `python evaluation/scripts/upload_prompt_template.py`
      and watch Step Functions execute. Then `sam delete` and verify
      `DELETE_COMPLETE`. — Skipped (manual smoke test; AWS deploy out of scope)

## Blocked Items

- Task 2.13 / 4.7: `sam validate` — blocked (no AWS credentials; sam build/deploy out of scope per spec)
- Task 4.8: Manual AWS smoke test — blocked (no AWS credentials; explicitly marked manual/out-of-scope)

## Notes

- **Cross-reference between Phase 2 and Phase 3.** The default
  `--stack-name = "rag-eval-pipeline"` and `--region = "us-east-1"` in
  `upload_prompt_template.py` (Phase 3) must match `samconfig.toml`'s
  `stack_name` and `region` (verified in Phase 3 Task 3.3). If a future
  PR changes either samconfig value, the upload script defaults must move
  in lockstep.
- **Seed file race on first deploy.** Per the risk table in roadmap.md,
  the Create-time seed of `prompts/kb_prompt_template.txt` will itself
  trigger `PromptTemplateChangeRule` and start a Step Functions execution
  during `CREATE_COMPLETE`. This is expected behavior and produces a
  baseline pass/fail result; it is not a bug. The sdd-executor does not
  need to suppress this.
- **EventBridge propagation delay.** The "execution starts within ~30
  seconds" success criterion has wiggle room (EventBridge can spike to
  ~60s under load). If the smoke test in Task 4.8 takes longer, that is
  not a regression — adjust the criterion phrasing in `intent.md` before
  considering the work blocked.
- **Bucket name length cap.** S3 bucket names are limited to 63 chars.
  The longest expected bucket name is
  `rag-eval-pipeline-eval-results-123456789012-us-east-1` = 53 chars.
  Safe. If the workshop ever uses a stack name longer than ~20 chars,
  re-check the math.
- **Demo-script unit tests use boto3 mocks, not real CFN.** Tests for
  `resolve_eval_bucket()` pass a MagicMock CFN client. The smoke test
  (Task 4.8) is the only real-CFN verification — there is no
  in-CI deploy step.
- **Path normalization.** The Lambda handler reads seed files via
  `os.path.join(SEED_ASSETS_DIR, filename)`. `sam build` always packages
  the Lambda with POSIX paths inside the zip regardless of the build OS,
  so this is portable. Do not introduce backslash literals in handler.py.
- **Do not change handler-loading idiom.** The new test files MUST use
  `importlib.util.spec_from_file_location` with an absolute
  `_HANDLER_PATH`, matching `evaluation/tests/test_start_eval_job.py`.
  Do not switch to `from evaluation.lambdas.seed_eval_assets import handler`
  — the Lambda dirs are not installed packages.
- **Order of operations during executor.** The executor should complete
  Phase 1 fully before Phase 2 (the template `CodeUri` reference will
  fail `sam build` if the Lambda directory does not exist). Phase 3 can
  proceed in parallel with Phase 2 in principle but is cleanest done
  after the template is stable. Phase 4 tests are written last so they
  can pin against the actual implementation.

## Completion

Implementation completed: 2026-05-10
All 107 pytest evaluation/tests/ tests pass (including 22 existing regression tests).
