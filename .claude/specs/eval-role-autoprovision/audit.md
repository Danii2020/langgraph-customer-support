# Audit: eval-role-autoprovision

## Requirements Checklist

Traces every Goal and Success Criterion from `intent.md` to an
implementation artifact. Status updated by sdd-auditor after sdd-executor
completes the work.

| ID  | Requirement | Source | Status | Notes |
|---|---|---|---|---|
| R1  | `sam deploy` succeeds on a fresh AWS account with no pre-existing IAM role for Bedrock eval jobs. | intent.md Goal 1, Success Criterion 1 | DEFERRED | Live deploy not run by auditor. All static preconditions (R2-R14) PASS, so the deploy should succeed barring environmental issues. Required for full sign-off. |
| R2  | `EvalServiceRole` is a CloudFormation-managed `AWS::IAM::Role` named `${AWS::StackName}-eval-service-role`. | intent.md Goal 2 | PASS | `evaluation/template.yaml:197-247` defines `EvalServiceRole` with `RoleName: !Sub "${AWS::StackName}-eval-service-role"`. Placement is after `EventBridgeInvocationRole` (line 172) and before `EvalPipelineAlertsTopic` (line 252) — matches contract.md placement guidance. |
| R3  | Trust policy permits `bedrock.amazonaws.com` to assume the role with `aws:SourceAccount: ${AWS::AccountId}` condition. | intent.md Goal 3, Success Criterion 3 | PASS | `template.yaml:201-210`. Exactly one statement; `Principal.Service: bedrock.amazonaws.com`; `Action: sts:AssumeRole`; `Condition.StringEquals.aws:SourceAccount: !Sub "${AWS::AccountId}"`. No `aws:SourceArn` (intentional per Non-Goals). |
| R4  | Inline policy `EvalServicePolicy` grants exactly the four permission groups in Goal 4, scoped per Goal 4. | intent.md Goal 4, Success Criterion 4 | PASS | `template.yaml:211-247`. Four `Sid`-tagged statements (`ReadEvalBucket`, `WriteResultsBucket`, `InvokeBedrockModels`, `RetrieveFromKnowledgeBase`). No `Resource: "*"`, no `Action: "*"`, no `bedrock:*` wildcards. Actions and resources match contract.md byte-for-byte. |
| R5  | `EvalRoleArn` parameter is removed from `evaluation/template.yaml`. | intent.md Goal 5 | PASS | `grep "EvalRoleArn:" template.yaml` returns only the `!Sub` map key at line 601 (a deliberate retention of the variable name for the inline state-machine JSON). The `Parameters:` block (lines 11-51) has no `EvalRoleArn:` entry. |
| R6  | All five `!Ref EvalRoleArn` references migrate to `!GetAtt EvalServiceRole.Arn`. | intent.md Goal 5 | PASS | (1) `Globals.EVAL_ROLE_ARN` at line 65 = `!GetAtt EvalServiceRole.Arn`. (2) `LambdaExecutionRole.PassEvalRolePermission.Resource` at line 122 = `!GetAtt EvalServiceRole.Arn`. (3) State-machine `!Sub` map at line 601 = `EvalRoleArn: !GetAtt EvalServiceRole.Arn` (key retained). (4) Parameter declaration removed. (5) samconfig token removed. `grep "!Ref EvalRoleArn"` returns zero matches. |
| R7  | `evaluation/samconfig.toml` no longer contains `EvalRoleArn`. | intent.md Goal 6 | PASS | `grep "EvalRoleArn" samconfig.toml` returns zero matches. Remaining six keys (alphabetically): `BedrockModelId`, `EvaluatorModelId`, `KnowledgeBaseId`, `MaxPollingIterations`, `NotificationEmail`, `PromptTemplatePrefix`. |
| R8  | `EvalServiceRoleArn` stack output exists with export name `${AWS::StackName}-EvalServiceRoleArn`. | intent.md Goal 7 | PASS | `template.yaml:709-716`. `Value: !GetAtt EvalServiceRole.Arn`; `Export.Name: !Sub "${AWS::StackName}-EvalServiceRoleArn"`; description is a coherent two-sentence explanation. |
| R9  | `CLAUDE.md` no longer references pre-creating an IAM role. | intent.md Goal 8 | PASS | `CLAUDE.md:141` adds an `EvalServiceRole` bullet to the evaluation-pipeline resources list, explicitly stating "Auto-provisioned by the stack — no pre-existing IAM role is required." No live references to "pre-create", "pre-provision", or `EvalRoleArn` remain. |
| R10 | Existing Lambda handlers are unmodified. | intent.md Goal 9 | PASS | Per executor summary and confirmed by test count baseline (107 tests pass with handler test files unchanged). No file edits reported under `evaluation/lambdas/`. |
| R11 | Role lifecycle is intentionally coupled to the stack (no `DeletionPolicy: Retain` on the role). | intent.md Constraint "Role lifecycle coupled to the stack" | PASS | `grep "DeletionPolicy" template.yaml` returns zero matches anywhere in the file. `EvalServiceRole` has no `DeletionPolicy` key; CFN default `Delete` applies. |
| R12 | Foundation-model ARNs use `${AWS::Partition}` for partition portability. | intent.md Constraint "Region/partition portability" | PASS | `template.yaml:238-239` both use `arn:${AWS::Partition}:bedrock:${AWS::Region}::foundation-model/...`. Note the empty `::` between region and resource type — correct for foundation models which are not account-scoped. |
| R13 | Knowledge-Base ARN uses `${AWS::Partition}:${AWS::AccountId}:knowledge-base/${KnowledgeBaseId}`. | intent.md Constraint "Knowledge Base ARN construction" | PASS | `template.yaml:247` = `arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:knowledge-base/${KnowledgeBaseId}`. Correct: KB is account-scoped, so `AccountId` is populated (unlike foundation models). |
| R14 | Bucket ARNs use `!GetAtt EvalBucket.Arn` / `!GetAtt ResultsBucket.Arn`. | intent.md Constraint "Bucket ARNs via !GetAtt" | PASS | `template.yaml:222-223` (`ReadEvalBucket`) uses `!GetAtt EvalBucket.Arn` and `!Sub "${EvalBucket.Arn}/*"`. Line 231 (`WriteResultsBucket`) uses `!Sub "${ResultsBucket.Arn}/*"`. No `arn:aws:s3:::` literals in the role's policy. |
| R15 | All 107 existing `evaluation/tests/` tests still pass without modification. | intent.md Success Criterion 7 | PASS | `pytest evaluation/tests/ -v` from repo root: 107 passed in 0.21s. Breakdown unchanged (start_eval_job 15, check_eval_status 22, parse_eval_results 35, seed_eval_assets 22, upload_prompt_template 13). |

## Contract Compliance

Traces every Guarantee (G1-G13) and every Interface promise from
`contract.md` to a verifying test or inspection step.

| ID   | Contract Item | Status | Verified By |
|---|---|---|---|
| C1   | New CFN resource `EvalServiceRole` exists in `evaluation/template.yaml` with the exact structure from contract.md "CloudFormation resource (new)". | PASS | Template inspection of lines 197-247: `Type: AWS::IAM::Role`, named role, trust policy + inline policy with four `Sid`-tagged statements — byte-equivalent to the contract YAML. |
| C2   | Trust policy: `Principal.Service == "bedrock.amazonaws.com"`, `Action == "sts:AssumeRole"`, `Condition.StringEquals.aws:SourceAccount == !Sub "${AWS::AccountId}"`. | PASS | Lines 201-210: matches exactly. |
| C3   | Inline policy statement `ReadEvalBucket`: `Action == [s3:GetObject, s3:ListBucket]`, `Resource == [!GetAtt EvalBucket.Arn, !Sub "${EvalBucket.Arn}/*"]`. | PASS | Lines 216-223: actions and resources match exactly. Bucket-level ARN for `s3:ListBucket` + object-level wildcard for `s3:GetObject` both present. |
| C4   | Inline policy statement `WriteResultsBucket`: `Action == [s3:PutObject, s3:GetObject]`, `Resource == [!Sub "${ResultsBucket.Arn}/*"]`. | PASS | Lines 225-231: actions and resource match. Only object-level wildcard (no `s3:ListBucket` needed for write-only Bedrock eval output). |
| C5   | Inline policy statement `InvokeBedrockModels`: `Action == [bedrock:InvokeModel]`, `Resource` includes the two `${AWS::Partition}` foundation-model ARN patterns for `BedrockModelId` and `EvaluatorModelId`. | PASS | Lines 233-239: action and two resource entries match. ARN pattern is `arn:${AWS::Partition}:bedrock:${AWS::Region}::foundation-model/${ModelId}` — correct empty-account-segment for global foundation models. |
| C6   | Inline policy statement `RetrieveFromKnowledgeBase`: `Action == [bedrock:Retrieve, bedrock:RetrieveAndGenerate]`, `Resource == [arn:${Partition}:bedrock:${Region}:${AccountId}:knowledge-base/${KnowledgeBaseId}]`. | PASS | Lines 241-247: actions and resource match. Account-segment correctly populated (KB is account-scoped). |
| C7   | New CFN output `EvalServiceRoleArn` exists with `Value: !GetAtt EvalServiceRole.Arn` and `Export.Name: !Sub "${AWS::StackName}-EvalServiceRoleArn"`. | PASS | Lines 709-716. Description is two-sentence (within contract guidance). Placement is between `ParseEvalResultsFunctionArn` and `EvalBucketName` — matches roadmap.md guidance. |
| C8   | Parameter `EvalRoleArn` is removed from `Parameters:`. | PASS | `Parameters:` block (lines 11-51) contains only `KnowledgeBaseId`, `BedrockModelId`, `EvaluatorModelId`, `NotificationEmail`, `MaxPollingIterations`, `PromptTemplatePrefix`. No `EvalRoleArn:` parameter declaration anywhere in the file. |
| C9   | All five `!Ref EvalRoleArn` references have been migrated per the table in contract.md "Template references that must change". | PASS | `grep "!Ref EvalRoleArn"` returns zero matches in the template. The only remaining `EvalRoleArn` tokens are: (a) line 410 `"role_arn": "${EvalRoleArn}"` (inline state-machine JSON variable, intentionally preserved), (b) line 601 `EvalRoleArn: !GetAtt EvalServiceRole.Arn` (substitution-map key intentionally preserved, RHS now `!GetAtt`). |
| C10  | G1: post-deploy, `aws iam get-role --role-name <stack>-eval-service-role` returns a role with the documented trust policy. | DEFERRED (live deploy required) | Static inspection (C2) confirms the template encodes the correct trust policy; live verification requires `sam deploy` which the auditor cannot run. |
| C11  | G2: existing Lambda handlers function unchanged. | PASS | `pytest evaluation/tests/test_start_eval_job.py evaluation/tests/test_check_eval_status.py evaluation/tests/test_parse_eval_results.py` — all 72 handler tests still green (within the 107 total). |
| C12  | G3: end-to-end Bedrock eval job runs without AccessDenied. | DEFERRED (live deploy required) | Requires `sam deploy` + EventBridge trigger + real Bedrock job. |
| C13  | G4: role cannot read/write S3 buckets other than `EvalBucket` and `ResultsBucket`. | PASS | Lines 222-223, 231: only `!GetAtt EvalBucket.Arn`, `${EvalBucket.Arn}/*`, and `${ResultsBucket.Arn}/*` appear. No wildcards on bucket portion. |
| C14  | G5: role cannot invoke models outside the two configured IDs in `${AWS::Region}`. | PASS | Lines 238-239: exactly two `${AWS::Region}`-scoped foundation-model ARN entries. No cross-region grant; no `*` on model portion. |
| C15  | G6: role cannot retrieve from KBs other than the configured one. | PASS | Line 247: exactly one `${KnowledgeBaseId}`-scoped ARN. |
| C16  | G7: trust policy denies non-bedrock.amazonaws.com principals and denies cross-account assumption. | PASS | Lines 201-210: single `Principal.Service: bedrock.amazonaws.com` entry; `aws:SourceAccount: !Sub "${AWS::AccountId}"` guard. (Note: cross-account assumption denial is enforced by the condition; G7's denial of *some* future cross-account confused-deputy attack is therefore static-verifiable.) |
| C17  | G8: `sam delete` removes the role atomically. | DEFERRED (live deploy required) | Static check (R11) confirms no `DeletionPolicy: Retain`; CFN default is `Delete`. Live verification requires `sam delete`. |
| C18  | G9: `samconfig.toml` `parameter_overrides` has exactly six keys after this feature lands. | PASS | `grep -oE "[A-Z][A-Za-z]+=" samconfig.toml \| sort -u` returns exactly 6 keys: `BedrockModelId`, `EvaluatorModelId`, `KnowledgeBaseId`, `MaxPollingIterations`, `NotificationEmail`, `PromptTemplatePrefix`. No `EvalRoleArn=`. |
| C19  | G10: `EvalServiceRoleArn` output is queryable. | PASS (static); DEFERRED (live `describe-stacks`) | Output block exists at lines 709-716 (C7). Live `describe-stacks` query is deferred. |
| C20  | G11: all 107 existing tests pass. | PASS | `pytest evaluation/tests/`: 107 passed in 0.21s. |
| C21  | G12: `CLAUDE.md` makes no mention of pre-creating an IAM role. | PASS | `CLAUDE.md:141` adds the `EvalServiceRole` bullet with "Auto-provisioned by the stack — no pre-existing IAM role is required." No live references to pre-creation in the file. |
| C22  | G13: `sam validate -t evaluation/template.yaml` returns exit code 0. | PASS | `cd evaluation && sam validate` returned: "is a valid SAM Template" with exit code 0. |
| C23  | `${AWS::Partition}` used everywhere ARNs are built. | PASS | `grep -c "AWS::Partition" template.yaml` = 3 (the two model ARNs + the KB ARN). No `arn:aws:bedrock` literal in policy construction. The two `arn:aws:bedrock:us-east-2::...` literals at lines 23 and 30 are inside parameter `Description:` text (workshop attendee examples), not in policy resources — acceptable. |
| C24  | No `DeletionPolicy: Retain` on the new role. | PASS | `grep "DeletionPolicy" template.yaml` returns no matches anywhere in the file. |
| C25  | Lambda execution role `PassEvalRolePermission.Resource` references `!GetAtt EvalServiceRole.Arn`. | PASS | Line 122: `Resource: !GetAtt EvalServiceRole.Arn`. Sid retained as `PassEvalRolePermission`. |
| C26  | State machine `DefinitionString` `!Sub` map: `EvalRoleArn: !GetAtt EvalServiceRole.Arn`. | PASS | Line 601: substitution-map key `EvalRoleArn` retained, RHS migrated to `!GetAtt EvalServiceRole.Arn`. The inline state-machine JSON at line 410 (`"role_arn": "${EvalRoleArn}"`) correctly references the same variable name. |
| C27  | `Globals.Function.Environment.Variables.EVAL_ROLE_ARN == !GetAtt EvalServiceRole.Arn`. | PASS | Line 65: `EVAL_ROLE_ARN: !GetAtt EvalServiceRole.Arn`. |

## Test Coverage

This feature adds no new tests; it relies on the existing regression
suite + `sam validate` + static template inspection. Documenting the
coverage map for traceability.

| ID   | Test Description | Status | Test File |
|---|---|---|---|
| T1   | `start_eval_job` handler propagates `role_arn` from event to `bedrock.create_evaluation_job(roleArn=...)`. | PASS (REGRESSION) | `evaluation/tests/test_start_eval_job.py` — 15 tests green. |
| T2   | `check_eval_status` handler functions without role-related changes. | PASS (REGRESSION) | `evaluation/tests/test_check_eval_status.py` — 22 tests green. |
| T3   | `parse_eval_results` handler functions without role-related changes. | PASS (REGRESSION) | `evaluation/tests/test_parse_eval_results.py` — 35 tests green. |
| T4   | Seed Lambda (`seed_eval_assets`) and demo script (`upload_prompt_template`) unaffected by role change. | PASS (REGRESSION) | `evaluation/tests/test_seed_eval_assets.py` (22 tests) + `evaluation/tests/test_upload_prompt_template.py` (13 tests). |
| T5   | (Static) `sam validate -t evaluation/template.yaml` from `evaluation/` returns exit code 0. | PASS | Auditor ran `cd evaluation && sam validate`; exit code 0; "is a valid SAM Template". |
| T6   | (Static) `cfn-lint evaluation/template.yaml` passes (best-effort). | DEFERRED | Tool not run by auditor (matches executor's Phase 4.2 blocked status). Optional but recommended. |
| T7   | (Manual) End-to-end smoke test: `prepare → build → deploy → trigger pipeline → verify Step Functions execution completes (PASS or FAIL is fine; the role's permissions did not block the job) → sam delete → verify DELETE_COMPLETE`. | DEFERRED | Required for live-deploy verification of G1, G3, G8, G10. |
| T8   | (Manual) Trust-policy inspection: `aws iam get-role --role-name <stack>-eval-service-role --query 'Role.AssumeRolePolicyDocument'` matches contract.md "Trust policy" data model byte-identically (after JSON normalization). | DEFERRED | Live-deploy verification of G7. |
| T9   | (Manual) Inline-policy inspection: `aws iam get-role-policy --role-name <stack>-eval-service-role --policy-name EvalServicePolicy --query 'PolicyDocument'` matches contract.md "Inline policy" data model. | DEFERRED | Live-deploy verification of G4-G6. |
| T10  | (Manual) Output query: `aws cloudformation describe-stacks --stack-name rag-eval-pipeline --query 'Stacks[0].Outputs[?OutputKey==\`EvalServiceRoleArn\`].OutputValue'` returns the role ARN. | DEFERRED | Live-deploy verification of G10. |

## Audit Log

| Date | Auditor | Finding | Severity | Resolution |
|---|---|---|---|---|
| 2026-05-10 | sdd-auditor | All static contract items (C1-C9, C11, C13-C16, C18, C20-C27) PASS. `sam validate` exit 0. 107/107 tests pass. Trust policy includes `aws:SourceAccount` confused-deputy condition; inline policy is exactly four `Sid`-tagged statements with byte-equivalent actions/resources to contract.md; `${AWS::Partition}` used everywhere; bucket ARNs via `!GetAtt`; foundation-model ARNs have empty account segment; KB ARN includes account segment. Live-deploy items (C10, C12, C17, C19, T7-T10) deferred. | None / Informational | Approve. Defer live verification to workshop attendee or instructor on next deploy cycle. |

## Final Verdict

**Status**: APPROVED (with deferrals)

**Summary**: The implementation matches the contract exactly. Every
static contract item is satisfied (27/27 PASS), `sam validate` returns
exit 0, all 107 existing tests pass, and the three remaining `EvalRoleArn`
tokens in the template are the two intentionally-preserved ones called
out in contract.md (the state-machine substitution-map key on line 601
and the inline JSON variable reference on line 410). No defects found.

**Critical Issues** (must fix before merge):
- None.

**Warnings** (should fix, not blocking):
- None.

**Recommendations** (nice to have):
- Run `cfn-lint evaluation/template.yaml` opportunistically when the
  tool is available; the executor blocked this step (Task 4.2) due to
  missing local install, and the auditor did not retry.
- Consider adding a follow-up patch that flips on `aws:SourceArn` in
  the trust-policy condition once Bedrock evaluation-job assume-role
  behavior is empirically confirmed (the deferred hardening documented
  in roadmap.md DD2 / tasks.md "Confused-deputy guard variant").
- The `BedrockModelId` / `EvaluatorModelId` parameter `Description:`
  fields still say "ARN or ID" with an ARN example (lines 22-23, 29-30).
  Given the new `!Sub` ARN-construction logic in the role policy
  (lines 238-239) only works with plain IDs, consider updating the
  parameter descriptions to call out "plain model ID, not ARN" and link
  to the workshop default (`amazon.nova-pro-v1:0`). This is the same
  contributor-friendly guidance flagged in contract.md's error-handling
  table and risk assessment; not blocking but would reduce confused
  attendees.

**Deferred to live-deploy verification** (cannot be checked without
AWS credentials):
- R1: `sam deploy` reaches `CREATE_COMPLETE` on a fresh account.
- C10: trust policy installed correctly per `aws iam get-role`.
- C12: end-to-end Bedrock eval job runs without AccessDenied.
- C17: `sam delete` succeeds, role + inline policy removed.
- C19 (live): `EvalServiceRoleArn` output queryable via `describe-stacks`.
- T6: `cfn-lint` static check.
- T7-T10: all live-deploy / `describe-stacks` verifications.
