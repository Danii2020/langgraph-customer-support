# Tasks: eval-role-autoprovision

## Legend

- [ ] Not started
- [x] Completed
- [~] In progress
- [!] Blocked

## Phase 1: Add the role to the template

- [x] Task 1.1: In `evaluation/template.yaml`, insert the new
      `EvalServiceRole` `AWS::IAM::Role` resource per contract.md
      "CloudFormation resource (new)". Placement: after
      `EventBridgeInvocationRole` and before `EvalPipelineAlertsTopic`
      (keeps IAM roles clustered together at the top of `Resources:`).
      All four `Sid`-tagged inline-policy statements
      (`ReadEvalBucket`, `WriteResultsBucket`, `InvokeBedrockModels`,
      `RetrieveFromKnowledgeBase`) must appear with the exact actions
      and `Resource:` lists from contract.md. Trust policy uses
      `Principal.Service: bedrock.amazonaws.com` with
      `Condition.StringEquals.aws:SourceAccount: !Sub "${AWS::AccountId}"`.
      ARNs use `${AWS::Partition}` (not literal `aws`). —
      `evaluation/template.yaml`
- [x] Task 1.2: Add the `EvalServiceRoleArn` output to the `Outputs:`
      block per contract.md "CloudFormation output (new)". Placement:
      after `ParseEvalResultsFunctionArn` and before `EvalBucketName`
      (or wherever produces the smallest diff). Export name must be
      `!Sub "${AWS::StackName}-EvalServiceRoleArn"`. —
      `evaluation/template.yaml`

## Phase 2: Rewire references and remove the parameter

- [x] Task 2.1: Update
      `Globals.Function.Environment.Variables.EVAL_ROLE_ARN` from
      `!Ref EvalRoleArn` to `!GetAtt EvalServiceRole.Arn`. —
      `evaluation/template.yaml` (line ~71)
- [x] Task 2.2: Update
      `LambdaExecutionRole.Policies[0].PolicyDocument.Statement[?Sid==PassEvalRolePermission].Resource`
      from `!Ref EvalRoleArn` to `!GetAtt EvalServiceRole.Arn`. The
      action (`iam:PassRole`) and the Sid stay the same; only the
      Resource pointer changes. —
      `evaluation/template.yaml` (line ~128)
- [x] Task 2.3: Update `EvalPipelineStateMachine.DefinitionString`
      `!Sub` map (the YAML list item under `- |` that starts at
      ~line 547): change `EvalRoleArn: !Ref EvalRoleArn` to
      `EvalRoleArn: !GetAtt EvalServiceRole.Arn`. The inline JSON at
      `"role_arn": "${EvalRoleArn}"` (template.yaml:361) stays
      unchanged — only the right-hand side of the `!Sub` map entry
      changes. — `evaluation/template.yaml` (line ~552)
- [x] Task 2.4: Delete the entire `EvalRoleArn:` parameter block from
      `Parameters:` (lines 18-22 in the current file). —
      `evaluation/template.yaml`
- [x] Task 2.5: Remove the `EvalRoleArn="arn:aws:iam::...:role/..."`
      token from `evaluation/samconfig.toml`'s `parameter_overrides`
      line (line 22). Keep the six remaining tokens in their existing
      relative order: `KnowledgeBaseId`, `BedrockModelId`,
      `EvaluatorModelId`, `NotificationEmail`, `MaxPollingIterations`,
      `PromptTemplatePrefix`. Verify the final value of
      `parameter_overrides` is a well-formed double-quoted string. —
      `evaluation/samconfig.toml`

## Phase 3: Documentation

- [x] Task 3.1: In `CLAUDE.md`, sweep for any references to
      `EvalRoleArn`, "pre-create the role", "pre-provision the role",
      or "create an IAM role" in the context of the evaluation
      pipeline. Remove or rewrite. The current text (after the
      previous feature) did not mention the role explicitly — verified
      clean with grep. —
      `CLAUDE.md`
- [x] Task 3.2: In `CLAUDE.md`, "Architecture > Evaluation pipeline
      (`evaluation/`)" section, added a bullet for `EvalServiceRole`
      at the top of the provisioned-resources list. Style mirrors
      `KnowledgeBaseRole` in the `kb_provisioning/` section. —
      `CLAUDE.md`

## Phase 4: Validation

- [x] Task 4.1: From the `evaluation/` directory, ran
      `sam validate -t template.yaml`. Exit code 0. Template is valid.
- [!] Task 4.2: (Best-effort) `cfn-lint` not installed in executor
      environment (command not found, exit code 127). Deferred to
      manual run.
- [x] Task 4.3: Ran `pytest evaluation/tests/`. Result: 107 passed
      in 0.21s. Breakdown: test_start_eval_job 15, test_check_eval_status
      22, test_parse_eval_results 35, test_seed_eval_assets 22,
      test_upload_prompt_template 13. Baseline preserved.
- [!] Task 4.4: (Manual smoke test) Deferred to live-deploy —
      AWS credentials / live deploy is out of scope for executor.

## Blocked Items

- Task 4.2: `cfn-lint` not installed in executor environment. Deferred to manual run or CI.
- Task 4.4: Live AWS deployment deferred to auditor judgment / workshop attendee verification.

## Notes

- **Single-source-of-truth for the role's ARN.** After this feature,
  the role's ARN exists in exactly one place in the codebase:
  `!GetAtt EvalServiceRole.Arn`. Every consumer (`Globals.EVAL_ROLE_ARN`,
  `LambdaExecutionRole.PassEvalRolePermission.Resource`, the state
  machine `!Sub` map) reaches it through the same `!GetAtt`. The
  samconfig file does not contain the ARN. The Lambda handlers do not
  contain the ARN. The tests do not contain the ARN. This is the
  intended end state.

- **Order of operations.** Phase 1 must complete before Phase 2 — you
  cannot rewire references to a resource that does not yet exist.
  Phase 3 (docs) can run in parallel with Phase 1 or 2; do whichever
  produces the smallest review diff. Phase 4 is last.

- **State-machine substitution-map key kept literally.** The state
  machine `DefinitionString` has a `!Sub` map with key `EvalRoleArn`
  and value `!Ref EvalRoleArn`. After Task 2.3 the value becomes
  `!GetAtt EvalServiceRole.Arn`, but the KEY stays `EvalRoleArn`
  because the inline JSON at line 361 references `${EvalRoleArn}`.
  Do not rename the map key — that would require also editing the
  inline state-machine JSON and breaks the diff blast radius.

- **`PassEvalRolePermission` Sid stays.** The Sid on the inline
  statement in `LambdaExecutionRole` stays `PassEvalRolePermission`
  (it describes the action, not the target). Only the `Resource:`
  field changes. Same statement, same effect, new resource pointer.

- **Test count baseline.** Before this feature: 107 tests pass. After
  this feature: still 107 tests pass (this feature adds no tests).
  If the count changes either direction, something is wrong — either
  a test was accidentally added/deleted, or a handler was accidentally
  touched in violation of the contract.

- **No `start_eval_job` test changes.** The existing test for
  role-arn propagation lives at
  `evaluation/tests/test_start_eval_job.py` and uses a synthetic
  role-arn fixture. The test does not care that the source of the
  role-arn changed from a CFN parameter to a `!GetAtt` — the test
  exercises only the Lambda handler's behavior. Do not touch this
  test.

- **`sam validate` is required before merge.** Static template
  inspection (the auditor's main tool) catches contract violations
  but not all SAM-level syntax errors. `sam validate` is the
  authoritative check; do not declare audit complete without it
  (or until a manual run unblocks Task 4.1).

- **`AWS::IAM::Role.RoleName` length.** With
  `${AWS::StackName} = "rag-eval-pipeline"`, the rendered role name
  is `rag-eval-pipeline-eval-service-role` = 35 chars. IAM caps role
  names at 64 chars. Safe. If a future workshop uses a longer stack
  name (>29 chars), re-check the math; otherwise no risk.

- **Confused-deputy guard variant.** If a follow-up audit decides to
  add `aws:SourceArn`, the change is a single nested-condition tweak
  in the trust policy:
  ```yaml
  Condition:
    StringEquals:
      aws:SourceAccount: !Sub "${AWS::AccountId}"
    ArnLike:
      aws:SourceArn: !Sub "arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:evaluation-job/*"
  ```
  No other template changes needed. The current spec defers this
  pending empirical verification of Bedrock's source-ARN injection
  behavior.

- **Region/model-availability prereq.** The deploy region
  (`samconfig.toml:12`) is `us-east-1`. The workshop default models
  (`amazon.nova-pro-v1:0` for both generator and evaluator) require
  Bedrock model access to be granted in the AWS console for that
  account/region. The IAM role only governs permission to call
  `bedrock:InvokeModel`; it does not bypass the account-level model
  access setting. If an attendee's account has not enabled Nova Pro
  in `us-east-1`, the eval job fails with `AccessDeniedException`
  at runtime — and that failure looks like an IAM problem but is
  actually a Bedrock model-access problem. Document in CLAUDE.md or
  workshop README; not a defect of this feature.

## Completion

Completed: 2026-05-10
Final test count: 107 passed, 0 failed.
`sam validate` exit code: 0.
Files modified: `evaluation/template.yaml`, `evaluation/samconfig.toml`, `CLAUDE.md`.
