# Roadmap: eval-role-autoprovision

## Design Decisions (justifications for choices in `intent.md`)

### DD1. No optional-override branch for `EvalRoleArn`

We considered keeping `EvalRoleArn` as an optional parameter
(default `""`) and gating `EvalServiceRole` creation behind a
`Condition: !Equals [!Ref EvalRoleArn, ""]`. Rejected because:

- The previous feature (`eval-bucket-autoprovision`) already chose the
  same tradeoff (no `ExistingEvalBucketName` override) and the workshop
  is a fresh install every time.
- An optional-override path doubles the `Resource:` surface area at
  every of the five references (each becomes
  `!If [HasExistingRole, !Ref EvalRoleArn, !GetAtt EvalServiceRole.Arn]`).
- The escape hatch for power users is to fork the template — a much
  cleaner contract than carrying conditional plumbing for the workshop's
  benefit.

If a production fork needs the override, it should re-introduce both
the parameter and the `!If` switch locally; do not preemptively add it
here.

### DD2. `aws:SourceAccount` only, no `aws:SourceArn`

Considered adding
`aws:SourceArn: arn:aws:bedrock:${AWS::Region}:${AWS::AccountId}:evaluation-job/*`
to the trust-policy condition. Rejected for the workshop default because:

- The AWS Bedrock documentation for evaluation-job service roles is
  not explicit about which `aws:SourceArn` shape Bedrock injects during
  `sts:AssumeRole`. The user-guide page recommends
  `aws:SourceAccount` only, with `aws:SourceArn` listed as "optional".
- An incorrect `aws:SourceArn` value silently breaks the trust policy
  with no actionable error (Bedrock returns
  "AccessDenied: Cannot assume role" with no hint).
- The workshop deploys to one account; the `aws:SourceAccount` guard
  is sufficient against confused-deputy attacks from cross-account
  scenarios.

If empirical verification later confirms Bedrock's `aws:SourceArn`
shape, add the condition as a follow-up patch; for now, document in
intent.md that this is a deliberate workshop-mode choice.

### DD3. Inline policy (`Policies:`) not managed policy (`ManagedPolicyArns:`)

The role's permissions are bespoke to this stack's resources
(`EvalBucket`, `ResultsBucket`, the specific
`BedrockModelId` / `EvaluatorModelId` / `KnowledgeBaseId`). A managed
policy would either need to be created in-template (adding a separate
`AWS::IAM::ManagedPolicy` resource) or live as a pre-existing artifact
in the account. Both are worse than an inline policy:

- A separate `AWS::IAM::ManagedPolicy` doubles the resource count for
  no functional gain.
- A pre-existing managed policy reintroduces the very pre-provisioning
  step this feature is removing.

Inline policy matches the convention used by every other IAM role in
`evaluation/template.yaml` and in `kb_provisioning/template.yaml`.

### DD4. Foundation-model ARN via `!Sub` (not via a custom resource)

Considered a CloudFormation custom resource Lambda that calls
`bedrock:GetFoundationModel` to look up the canonical ARN from a
plain ID. Rejected because:

- For the workshop default (`amazon.nova-pro-v1:0`), the ARN format is
  deterministic and well-known
  (`arn:${Partition}:bedrock:${Region}::foundation-model/${Id}`).
- A custom resource adds a Lambda, its IAM role, and a stack-create
  latency cost (~5-10s) for a string concatenation.
- The failure modes of `!Sub` (attendee passes an ARN as the ID,
  attendee passes an inference-profile ID) are clearly documented in
  the parameter description; the custom resource would not help with
  the inference-profile case anyway.

### DD5. Region/account intrinsics, not parameters

We considered exposing `EvalRegion` and `EvalAccountId` as parameters
for cross-account / cross-region setups. Rejected because:

- The samconfig already pins `region = "us-east-1"`.
- A cross-account eval job is fundamentally a different deployment
  model (it needs `aws:ResourceOrgPaths` conditions, cross-account
  role chaining, etc.) that the workshop does not address.
- `${AWS::Region}` and `${AWS::AccountId}` resolve at stack-create
  time and give the correct values for every supported deployment.

### DD6. One inline policy with multiple `Sid`-tagged statements

We considered splitting the policy into multiple smaller policies
(one per `Sid`), each as a separate `Policies:` list entry. Rejected
because:

- The four statements share the same role's permission boundary; a
  single inline policy is the minimum-friction artifact.
- Multiple `Policies:` entries each carry a name and a separate
  `PolicyDocument:` block, which doubles the YAML surface for no
  semantic difference.
- The single-policy-multiple-Sid pattern is what `LambdaExecutionRole`
  already uses (`evaluation/template.yaml:98-128`) and what
  `KnowledgeBaseRole` uses in `kb_provisioning/template.yaml:123-152`.
  Stay consistent.

### DD7. Separate `Sid: ReadEvalBucket` vs `Sid: WriteResultsBucket`

We considered a single `S3Permissions` Sid covering both buckets.
Rejected because:

- The bucket purposes are semantically different (read source data
  vs write evaluation output). Splitting the Sid makes the policy
  self-documenting.
- Future debugging ("why can't Bedrock read the prompt template?") is
  faster when the Sid name maps to the failing action.
- Same pattern as `kb_provisioning/template.yaml`'s
  `KnowledgeBaseRole`, which uses one Sid per purpose
  (`InvokeEmbeddingModel`, `ReadSourceBucket`, `VectorIndexAccess`).

### DD8. No `permissions_boundary` on the role

Considered attaching a permissions boundary to defense-in-depth against
policy-drift. Rejected because:

- The inline policy itself is already minimum-privilege; a boundary
  would be functionally a no-op (it can only further restrict, and
  the inline policy is already at the floor).
- Workshop accounts often lack pre-existing permission boundary
  policies, so requiring one creates a new pre-provisioning step —
  the exact problem this feature is solving.
- A production fork should add the boundary; the workshop does not.

### DD9. No unit tests for handler changes (because there are none)

Per spec note in the user's request: "There's no Lambda handler
change, so no new unit tests are needed for handler logic." The
existing `evaluation/tests/test_start_eval_job.py` regresses the
role-arn propagation path because the test fixture builds an event
with a synthetic `role_arn` and asserts it reaches
`bedrock.create_evaluation_job(roleArn=...)`. That coverage is
preserved.

Auditor verification relies on:

1. `sam validate -t evaluation/template.yaml` for template
   correctness.
2. `cfn-lint` (best-effort) for `!Sub` typo and unreferenced-parameter
   detection.
3. Inspection of the rendered policy document against the contract.md
   data models.
4. The manual smoke test (`sam deploy`, observe Step Functions execute
   end-to-end against a real Knowledge Base).

This matches the working norm established by the previous feature: the
executor produces correct artifacts, the auditor verifies them, no
intermediate test-writer pass.

## Implementation Phases

### Phase 1: Add the role to the template

**Goal**: Insert the `EvalServiceRole` resource and the
`EvalServiceRoleArn` output into `evaluation/template.yaml`. Do not
yet remove the parameter or rewire references — keep the template
working with both the parameter and the new role in parallel for one
intermediate commit so review diffs stay readable.

**Dependencies**: None.

**Estimated complexity**: Low (single resource + single output, both
mechanically derived from contract.md).

1. In `evaluation/template.yaml`, insert the new `EvalServiceRole`
   `AWS::IAM::Role` resource. Placement: after
   `EventBridgeInvocationRole` (around current line 199) and before
   `EvalPipelineAlertsTopic`, keeping the file's "IAM roles cluster
   together at the top of Resources" convention.
2. In the `Outputs:` block, add `EvalServiceRoleArn` with the
   description, value (`!GetAtt EvalServiceRole.Arn`), and export name
   from contract.md. Placement: after the existing
   `ParseEvalResultsFunctionArn` output or before `EvalBucketName`
   (either works; pick whichever keeps the diff smallest).

### Phase 2: Rewire references and remove the parameter

**Goal**: Switch every `!Ref EvalRoleArn` to
`!GetAtt EvalServiceRole.Arn`, delete the `EvalRoleArn` parameter,
delete the `EvalRoleArn=...` token from `samconfig.toml`.

**Dependencies**: Phase 1.

**Estimated complexity**: Low (four small edits, mechanically
derivable from the contract.md table).

1. In `evaluation/template.yaml`,
   `Globals.Function.Environment.Variables.EVAL_ROLE_ARN` (line 71):
   change `!Ref EvalRoleArn` → `!GetAtt EvalServiceRole.Arn`.
2. In `LambdaExecutionRole.Policies.PassEvalRolePermission.Resource`
   (line 128): change `!Ref EvalRoleArn` →
   `!GetAtt EvalServiceRole.Arn`.
3. In `EvalPipelineStateMachine.DefinitionString` `!Sub` map (line
   552): change `EvalRoleArn: !Ref EvalRoleArn` →
   `EvalRoleArn: !GetAtt EvalServiceRole.Arn`. The inline state-machine
   JSON at the `${EvalRoleArn}` reference site (template.yaml:361)
   stays unchanged.
4. In `evaluation/template.yaml` `Parameters:` block (lines 18-22):
   delete the entire `EvalRoleArn:` parameter block.
5. In `evaluation/samconfig.toml:22` `parameter_overrides`: remove
   the `EvalRoleArn="arn:aws:iam::...:role/..."` token (including the
   leading or trailing space). Keep the other six tokens
   (`KnowledgeBaseId`, `BedrockModelId`, `EvaluatorModelId`,
   `NotificationEmail`, `MaxPollingIterations`, `PromptTemplatePrefix`)
   in their existing order.

### Phase 3: Documentation

**Goal**: Update `CLAUDE.md` to reflect that the role is now
auto-provisioned.

**Dependencies**: Phase 2 (so the docs match what the template does).

**Estimated complexity**: Low.

1. In `CLAUDE.md`, "Evaluation pipeline" command section (around line
   55): verify there are no remaining references to pre-creating an
   IAM role. (Current text mostly references the buckets, but sweep
   to be sure.)
2. In `CLAUDE.md`, "Architecture > Evaluation pipeline (`evaluation/`)"
   section (around line 200, near the line that lists the EventBridge
   rules): add a sentence noting that the stack auto-provisions
   `EvalServiceRole` (a Bedrock service role) and that attendee prep
   is now reduced to `KnowledgeBaseId`, `NotificationEmail`, and the
   two model IDs. Mirror the wording style already used in that
   section.
3. In `CLAUDE.md`, anywhere else that mentions `EvalRoleArn` (search
   the full file): remove or update the mention. As of 2026-05-10
   there is exactly one such mention in `eval-bucket-autoprovision`'s
   constraint about preserving the role parameter; this feature
   supersedes that, so the wording should update.

### Phase 4: Validation

**Goal**: Confirm the template is syntactically valid and the unit
test baseline is preserved.

**Dependencies**: Phase 3.

**Estimated complexity**: Low.

1. From `evaluation/`, run `sam validate -t template.yaml`. Verify
   exit code 0. (If AWS creds are unavailable in the executor's
   environment, document the skip in `tasks.md` and defer to manual
   smoke test.)
2. (Best-effort) Run `cfn-lint evaluation/template.yaml`. Address any
   warnings about the new `!Sub` patterns. Common findings to expect
   and ignore: `W3045` (deprecated S3 bucket NotificationConfiguration
   warnings) is from the previous feature; ignore unless the new
   diff introduces new warnings.
3. Run `pytest evaluation/tests/`. Verify all 107 tests still pass
   (no test files are added or modified by this feature). If a test
   fails, the failure is a regression in the migration — debug
   before declaring Phase 4 complete.
4. (Manual smoke test, deferred to auditor judgment / live deploy.)
   In a clean AWS account:
   `python evaluation/scripts/prepare_lambda_assets.py`, then
   `cd evaluation && sam build && sam deploy --config-file
   samconfig.toml`. Verify `CREATE_COMPLETE`. Verify the
   `EvalServiceRoleArn` output. Trigger a Step Functions execution
   via `python evaluation/scripts/upload_prompt_template.py` and
   verify it reaches `PASSED` or `FAILED` (either is acceptable as
   long as the role permissions did not block the eval job from
   running). Run `sam delete` and verify `DELETE_COMPLETE`.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `!Sub` ARN construction produces a wrong ARN for the workshop default model (`amazon.nova-pro-v1:0`) | Very Low | High (eval job fails with AccessDenied) | The ARN format is well-documented; we use the canonical pattern from AWS docs. Manual smoke test in Phase 4 step 4 catches this. |
| Attendee passes a foundation-model ARN as `BedrockModelId` instead of a plain ID, breaking the `!Sub` policy | Low (workshop ships with plain IDs in samconfig) | Medium (silent AccessDenied at job runtime, debugging cost) | Update the `BedrockModelId` and `EvaluatorModelId` parameter `Description:` to call out "plain model ID, not ARN" with the workshop default example. Documented in contract.md error-handling table. |
| Attendee passes an inference-profile ID (e.g. `us.amazon.nova-pro-v1:0`) | Low | Medium | Same as above; documented in contract.md and intent.md constraints. Workshop default uses a non-profile model. |
| IAM eventual-consistency: first `CreateEvaluationJob` call after stack create hits `ValidationException: roleArn is invalid` because IAM has not propagated the role | Low | Low | Step Functions task already retries 2x with backoff 2.0 starting at 10s — covers the typical 1-3s IAM propagation window. No code change needed. |
| `sam delete` while a Bedrock evaluation job is in `IN_PROGRESS` → IAM `DeleteRole` returns `DeleteConflict` | Low (workshop attendees rarely tear down mid-eval) | Medium (stack stuck in `DELETE_FAILED`) | Attendee waits for the eval job to finish (or calls `aws bedrock stop-evaluation-job`) then retries `sam delete`. Acceptable failure mode; document in contract.md error table. |
| `aws:SourceAccount`-only trust policy is insufficient against some future Bedrock-side change that requires `aws:SourceArn` | Very Low | High (trust policy stops working, all eval jobs fail) | DD2 documents the choice and provides the upgrade path. The unit-test baseline does not exercise the live trust policy, so a future Bedrock change is only catchable by the manual smoke test or by live failure. Workshop instructor should re-run the smoke test once per workshop cohort. |
| `LambdaExecutionRole.PassEvalRolePermission.Resource` left pointing at the deleted `!Ref EvalRoleArn` (forgotten reference) | Low (caught by `sam validate`) | High (template fails to deploy: "unresolved reference EvalRoleArn") | Phase 2 step 2 explicitly fixes this reference. `sam validate` in Phase 4 step 1 catches the omission. |
| `EvalPipelineStateMachine.DefinitionString` `!Sub` map left pointing at `!Ref EvalRoleArn` (forgotten reference) | Low (caught by `sam validate`) | High (same as above) | Phase 2 step 3 explicitly fixes this reference. |
| Removing the parameter but leaving `EvalRoleArn="..."` in `samconfig.toml` | Medium (easy to miss in a yaml-vs-toml diff) | Medium (`sam deploy` rejects with "Parameter EvalRoleArn does not exist") | Phase 2 step 5 explicitly removes the samconfig token. Auditor verifies via grep. |
| `${AWS::Partition}` breaks in some edge-case partition where Bedrock is unavailable | Very Low | Medium | Bedrock is available in `aws` (commercial) and `aws-us-gov` (govcloud) partitions. The workshop default targets `aws`. `${AWS::Partition}` is the correct portable pattern; an explicit `aws` literal would be worse for govcloud forks. |
| Region/model mismatch: the role policy permits invoking the model in `${AWS::Region}` but the attendee's account has not enabled Bedrock model access for the chosen model in that region | Low (workshop docs ship a model that is enabled by default in us-east-1) | High (AccessDenied at job runtime, looks like an IAM problem but is actually a Bedrock model-access problem) | Document in intent.md "Region/model interplay" constraint. The fix is at the AWS console (Bedrock model access page), not in the template. |
| Workshop attendee re-runs `sam deploy` and expects to provide a different role ARN | Very Low | Low | The new contract is "the stack provisions its own role"; attendees do not have an opt-out. Document this in CLAUDE.md if it becomes a recurring question. |

## File Change Map

### CREATE

- None.

### MODIFY

- `evaluation/template.yaml` — MODIFY — add one `AWS::IAM::Role`
  resource (`EvalServiceRole`); add one output (`EvalServiceRoleArn`);
  delete one parameter (`EvalRoleArn`); rewire four
  `!Ref EvalRoleArn` references to `!GetAtt EvalServiceRole.Arn`
  (Globals env var, LambdaExecutionRole inline statement, state-machine
  !Sub map, plus deleting the parameter declaration itself).
- `evaluation/samconfig.toml` — MODIFY — remove the
  `EvalRoleArn="arn:aws:iam::...:role/..."` token from
  `parameter_overrides`. No other changes.
- `CLAUDE.md` — MODIFY — sweep for any `EvalRoleArn` mentions and
  remove them; add a one-line note in the "Architecture > Evaluation
  pipeline" section that `EvalServiceRole` is now auto-provisioned;
  trim attendee-prep wording if any pre-create-the-role steps remain.

### DELETE

- None.

### UNCHANGED (called out explicitly)

- `evaluation/lambdas/start_eval_job/handler.py` — UNCHANGED.
- `evaluation/lambdas/check_eval_status/handler.py` — UNCHANGED.
- `evaluation/lambdas/parse_eval_results/handler.py` — UNCHANGED.
- `evaluation/lambdas/seed_eval_assets/handler.py` — UNCHANGED.
- `evaluation/scripts/prepare_lambda_assets.py` — UNCHANGED.
- `evaluation/scripts/upload_prompt_template.py` — UNCHANGED.
- `evaluation/tests/conftest.py` — UNCHANGED.
- `evaluation/tests/test_start_eval_job.py` — UNCHANGED (regression).
- `evaluation/tests/test_check_eval_status.py` — UNCHANGED.
- `evaluation/tests/test_parse_eval_results.py` — UNCHANGED.
- `evaluation/tests/test_seed_eval_assets.py` — UNCHANGED.
- `evaluation/tests/test_upload_prompt_template.py` — UNCHANGED.
- `evaluation/requirements-dev.txt` — UNCHANGED.
- `evaluation/dataset/`, `evaluation/config/`, `evaluation/prompts/`
  — UNCHANGED.
- All `kb_provisioning/` files — UNCHANGED (reference implementation).
- All `src/`, `main.py`, root-level files — UNCHANGED.
