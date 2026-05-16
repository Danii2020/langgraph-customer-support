# Intent: eval-role-autoprovision

## Problem Statement

After `eval-bucket-autoprovision` shipped (specs at
`/Users/danielerazo/python/langgraph-gmail/.claude/specs/eval-bucket-autoprovision/`),
the `evaluation/` SAM stack provisions and seeds its own `EvalBucket` and
`ResultsBucket`. That removed the bucket pre-flight ritual, but a single
manual step still stands between a fresh-account attendee and a clean
one-command deploy:

> The attendee must pre-create an IAM role in the AWS Console (or via CLI),
> grant it the right trust policy (`Service: bedrock.amazonaws.com`), grant
> it the right inline policy (S3 read on the eval bucket, S3 write on the
> results bucket, `bedrock:InvokeModel` on the generator/evaluator models,
> `bedrock:Retrieve` + `bedrock:RetrieveAndGenerate` on the Knowledge Base),
> and then paste its ARN into `evaluation/samconfig.toml` as `EvalRoleArn`.

That role is then consumed by `bedrock:CreateEvaluationJob`
(`evaluation/lambdas/start_eval_job/handler.py:131-133`) as the `roleArn`
parameter — Bedrock assumes it on the attendee's behalf to run the
`RETRIEVE_AND_GENERATE` evaluation job.

The same shape of problem (pre-provision-and-paste) was solved twice
already in this repo: `kb_provisioning/template.yaml` inlines its own
`KnowledgeBaseRole` for Bedrock; `eval-bucket-autoprovision` inlined the
buckets. This feature does the same thing for the evaluation-job service
role and finishes the workshop's "one command to deploy" goal for the
`evaluation/` stack.

Affected:
- **Workshop attendees** — every minute spent in the IAM console picking
  permissions is a minute lost from the evaluation concepts being taught,
  and the failure modes (wrong trust principal, missing `Resource:` ARN,
  typo'd model ARN) are the slowest to diagnose.
- **Workshop instructors** — "what permissions does the role need?"
  questions during the workshop window have the highest support cost
  because they require explaining IAM trust policies, Bedrock service
  authentication, and the role-vs-user model.
- **Future workshop forks** — every new attendee account is a fresh manual
  setup, and any forked workshop currently inherits the same manual step.

## Goals

1. `sam deploy` of the `evaluation/` stack succeeds on a fresh AWS account
   with **no** prerequisite IAM role creation. The attendee touches only
   `KnowledgeBaseId`, `NotificationEmail`, and the two model IDs in
   `samconfig.toml`.
2. The Bedrock evaluation-job service role is a CloudFormation-managed
   `AWS::IAM::Role` resource named `EvalServiceRole` inside
   `evaluation/template.yaml`, following the established
   `${AWS::StackName}-<purpose>-role` naming convention.
3. The role's trust policy permits `bedrock.amazonaws.com` to assume it,
   gated by the `aws:SourceAccount` confused-deputy condition recommended
   by AWS.
4. The role's inline policy grants the **minimum-privilege** set required
   by `CreateEvaluationJob` for a `RagEvaluation` job:
   - `s3:GetObject` + `s3:ListBucket` on `EvalBucket` (for dataset,
     thresholds, prompt template).
   - `s3:PutObject` + `s3:GetObject` on `ResultsBucket` (for the eval
     output under `results/rag/`).
   - `bedrock:InvokeModel` on the generator and evaluator model ARNs
     constructed from `BedrockModelId` and `EvaluatorModelId`.
   - `bedrock:Retrieve` + `bedrock:RetrieveAndGenerate` on the Knowledge
     Base ARN constructed from `KnowledgeBaseId`.
5. The `EvalRoleArn` template parameter is **removed**. All five
   references in `evaluation/template.yaml` switch from `!Ref EvalRoleArn`
   to `!GetAtt EvalServiceRole.Arn`.
6. The `EvalRoleArn="..."` entry is removed from
   `evaluation/samconfig.toml` `parameter_overrides`.
7. A new `EvalServiceRoleArn` stack output (with export name
   `${AWS::StackName}-EvalServiceRoleArn`) is added for diagnostic and
   future cross-stack-reference parity with the other outputs.
8. `CLAUDE.md`'s "Evaluation pipeline" section no longer references a
   pre-provisioned role; attendee prep is reduced to the four configurable
   parameters (`KnowledgeBaseId`, `NotificationEmail`, `BedrockModelId`,
   `EvaluatorModelId`).
9. No changes to the three existing Lambda handlers
   (`start_eval_job`, `check_eval_status`, `parse_eval_results`) or their
   unit tests. The handlers read `EVAL_ROLE_ARN` from the Lambda
   environment; swapping the source from a `!Ref` parameter to a
   `!GetAtt` resource is transparent.

## Success Criteria

- [ ] A fresh AWS account with no pre-existing IAM roles for Bedrock eval
      jobs can run `python evaluation/scripts/prepare_lambda_assets.py`
      followed by `cd evaluation && sam build && sam deploy --config-file
      samconfig.toml` (with `KnowledgeBaseId`, `NotificationEmail`,
      `BedrockModelId`, `EvaluatorModelId` filled in) and reach
      `CREATE_COMPLETE`.
- [ ] After `CREATE_COMPLETE`, the stack exposes an `EvalServiceRoleArn`
      output whose value matches `aws iam get-role --role-name
      <stack>-eval-service-role`.
- [ ] The role's trust policy contains exactly one statement, with
      `Principal: {Service: "bedrock.amazonaws.com"}`,
      `Action: "sts:AssumeRole"`, and a
      `Condition: {StringEquals: {"aws:SourceAccount": "<account-id>"}}`.
- [ ] The role's inline policy grants exactly the four permission groups
      listed in Goal 4, scoped to the resources listed there. No
      `Resource: "*"` on S3, no `bedrock:*` wildcards on model invocation.
- [ ] An end-to-end Step Functions execution (triggered by either
      `KbSyncCompletionRule` or `PromptTemplateChangeRule`) creates a
      Bedrock evaluation job, the job runs to completion, and the
      `parse_eval_results` Lambda reads the output from `ResultsBucket`
      without permission errors.
- [ ] `evaluation/samconfig.toml` `parameter_overrides` no longer contains
      `EvalRoleArn`; remaining keys are `KnowledgeBaseId`, `BedrockModelId`,
      `EvaluatorModelId`, `NotificationEmail`, `MaxPollingIterations`,
      `PromptTemplatePrefix` (six keys total).
- [ ] All existing `evaluation/tests/` Lambda unit tests still pass
      unmodified (the previous feature's 107-test baseline stays at 107
      green; the three handler-test files
      `test_start_eval_job.py`, `test_check_eval_status.py`,
      `test_parse_eval_results.py` are untouched).
- [ ] `sam delete --stack-name rag-eval-pipeline --region us-east-1`
      succeeds without IAM cleanup remnants — the role and its inline
      policy are removed by CloudFormation as part of stack delete.
- [ ] `sam validate -t evaluation/template.yaml` (and ideally
      `cfn-lint`) passes after the changes.
- [ ] `CLAUDE.md` no longer mentions pre-creating an IAM role for the
      evaluation pipeline.

## Non-Goals

- We are **not** preserving `EvalRoleArn` as an optional override
  parameter. The workshop is a fresh install every time; carrying a
  "bring your own role" branch would add a `Condition:` block, a second
  IAM role artifact, and a non-trivial conditional in five other
  references — for zero workshop value. The escape hatch for advanced
  users is to fork the template and re-introduce the parameter locally.
  (Symmetric with the `eval-bucket-autoprovision` decision to not
  preserve `EvalBucketName` as an override.)
- We are **not** changing the three existing Lambda handlers
  (`start_eval_job`, `check_eval_status`, `parse_eval_results`) or their
  unit tests. They read `EVAL_ROLE_ARN` from `os.environ`; the migration
  is transparent.
- We are **not** auto-provisioning a permissions boundary or attaching an
  IAM-condition policy to constrain the role beyond its inline policy.
  The inline policy itself is minimum-privilege; adding a permissions
  boundary on top would not change the role's effective permissions.
- We are **not** adding `aws:SourceArn` to the trust-policy condition.
  The evaluation-job ARN is not known at role-creation time (the job is
  created at workflow run time inside the
  `evaluation/lambdas/start_eval_job/handler.py` flow), and scoping to
  `arn:aws:bedrock:${AWS::Region}:${AWS::AccountId}:evaluation-job/*`
  would require verifying that Bedrock populates `aws:SourceArn` with
  that exact shape on every assume-role call — Bedrock evaluation-job
  documentation is not explicit about this. We choose the
  `aws:SourceAccount`-only guard as the workshop default; document the
  ARN-scoped variant as an optional hardening in roadmap.md "Design
  Decisions" so a future contributor can promote it once we have
  empirical confirmation.
- We are **not** writing a new unit test file for handler logic
  (`start_eval_job/handler.py` is unchanged). The audit relies on
  `sam validate` (template correctness) and the existing handler tests
  (regression coverage). This is a deliberate choice consistent with
  the previous feature's pattern: the auditor's compliance verification
  + `sam validate` is the working norm here.
- We are **not** building IAM tests with `iam:SimulatePrincipalPolicy`
  or `aws iam simulate-custom-policy`. The policy surface is small
  enough to verify by inspection (audit.md C2-C9) and end-to-end via the
  manual smoke test (audit.md T7).
- We are **not** introducing a `bedrock-runtime:*` permission. The
  evaluation job is created via `bedrock:CreateEvaluationJob` and
  internally uses `bedrock-agent`-style RAG retrieval; the role does not
  need `bedrock-runtime` permissions for the application path
  (the LangGraph app at the repo root uses `bedrock-runtime` via
  `ChatBedrock` but runs under separate credentials).
- We are **not** auto-deriving model ARNs from a CloudFormation custom
  resource. The `!Sub` foundation-model ARN construction
  (Constraints below) is the simplest contract that works for the
  workshop default (`amazon.nova-pro-v1:0`).

## Constraints

- **Role lifecycle coupled to the stack.** `sam delete` removes the role
  and its inline policy. For a workshop this is correct; any future
  production fork that re-uses the role for human/CLI experiments must
  set `DeletionPolicy: Retain` on the role and explicitly remove the
  inline policy on stack delete. Document this in roadmap.md so a future
  contributor does not strip the auto-creation path "for safety" and
  break the workshop teardown story.
- **Model ARN construction for foundation models.** `BedrockModelId` and
  `EvaluatorModelId` are documented as "ARN or ID" in the template
  parameter descriptions today, but `samconfig.toml` ships the workshop
  default as the plain ID `amazon.nova-pro-v1:0`. We construct the policy
  resource via
  `!Sub "arn:${AWS::Partition}:bedrock:${AWS::Region}::foundation-model/${BedrockModelId}"`
  (and symmetrically for `EvaluatorModelId`). This works for plain
  foundation-model IDs in any partition (commercial / govcloud /
  cn-north). It does **not** work for cross-region inference profiles
  (`arn:.../inference-profile/...`) or application inference profiles
  (`arn:.../application-inference-profile/...`); attendees who want
  those must (a) pass the full ARN as `BedrockModelId` and the `!Sub`
  will produce a double-prefixed value that breaks the policy, or (b)
  fork the template to expand the `Resource:` list. Document the
  workshop default as the supported path; flag the ARN/profile case in
  the parameter description so attendees see it at deploy time.
- **Knowledge Base ARN construction.** `KnowledgeBaseId` is always a
  bare ID (not an ARN). We build the ARN via
  `!Sub "arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:knowledge-base/${KnowledgeBaseId}"`.
  Same partition-portable pattern as the model ARN.
- **Bucket ARNs via `!GetAtt`.** Since `EvalBucket` and `ResultsBucket`
  are now CFN resources (from the previous feature), reference them via
  `!GetAtt EvalBucket.Arn` / `!GetAtt ResultsBucket.Arn` and
  `!Sub "${EvalBucket.Arn}/*"` for object-level perms. Never write
  `arn:aws:s3:::<bucket>` literals.
- **Minimum-privilege.** Inline-policy resource lists are explicit ARNs
  (no `Resource: "*"`). Actions are explicit (no `s3:*`, no `bedrock:*`).
  This matches the convention in `kb_provisioning/template.yaml`'s
  `KnowledgeBaseRole` (every action listed verbatim).
- **Trust-policy condition.** Use `aws:SourceAccount: ${AWS::AccountId}`
  inside `StringEquals`. This is the AWS-recommended confused-deputy
  guard for service-linked roles. We deliberately do **not** add
  `aws:SourceArn` (see Non-Goals); revisit only after empirical
  verification that Bedrock populates it during evaluation-job
  assume-role.
- **Region/partition portability.** Use `${AWS::Region}` and
  `${AWS::Partition}` in `!Sub` patterns instead of hardcoding
  `us-east-1` or `aws`. The `samconfig.toml` deploys to `us-east-1`
  today, but the template surface should not encode that assumption.
- **Region/model interplay.** Plain model IDs like `amazon.nova-pro-v1:0`
  resolve to a foundation-model ARN scoped to `${AWS::Region}` (the
  deploy region). For Bedrock to invoke the model successfully, the
  model must be enabled in that region. The samconfig ships
  `us-east-1` and Nova Pro is available there; if a future config moves
  to a region where Nova Pro is not enabled, the eval job will fail at
  invocation time with an `AccessDeniedException`. Document this in
  intent.md constraints (here) so a future contributor knows the failure
  mode.
- **`IAMResource` clause: list vs scalar.** AWS IAM accepts both a string
  and a list for `Resource:`. We use a list everywhere for consistency
  with `kb_provisioning/template.yaml` and to make adding a second
  resource (e.g. a second model ARN, a second bucket) a one-line diff.
- **Lambda handler invariant.** `start_eval_job/handler.py` reads
  `os.environ["EVAL_ROLE_ARN"]` indirectly via the event payload (the
  Step Functions task wires it via the state machine `Parameters`
  substitution). The state machine wires it from
  `${EvalRoleArn}` in the `DefinitionString` substitution map. Today
  that map keys on `!Ref EvalRoleArn`; this feature changes it to
  `!GetAtt EvalServiceRole.Arn`. The Lambda sees a different string
  value at runtime but the handler does not inspect the ARN's shape —
  it just passes it to `bedrock.create_evaluation_job(roleArn=...)`.
  Verify this invariant in the contract (G2 below).
- **`PassEvalRolePermission` policy on `LambdaExecutionRole` (line ~150).**
  The Lambda execution role today has an inline statement
  `iam:PassRole` scoped to `!Ref EvalRoleArn`. After this change, the
  scope becomes `!GetAtt EvalServiceRole.Arn`. The action and the
  intent (let the Lambda pass this specific role to Bedrock) are
  unchanged; only the target resource ref changes.
- **No new third-party Python deps.** This is a pure-template change
  + samconfig + CLAUDE.md docs. The Lambda CodeUris are untouched.
- **CloudFormation `CAPABILITY_NAMED_IAM` already set.** The samconfig
  already declares
  `capabilities = "CAPABILITY_IAM CAPABILITY_NAMED_IAM"` (line 13), so
  the new named role (`${AWS::StackName}-eval-service-role`) deploys
  without re-prompting.

## Prior Art

- **`kb_provisioning/template.yaml:111-153`** — the
  `KnowledgeBaseRole` is the most direct architectural template for
  this feature. It has the same trust-policy shape
  (`Principal: {Service: bedrock.amazonaws.com}`), the same inline-policy
  layout (one PolicyDocument with multiple `Sid`-tagged statements),
  the same naming convention (`${AWS::StackName}-kb-role`), and the
  same minimum-privilege philosophy (explicit resources, no wildcards
  on S3 buckets, explicit action lists). Mirror it for
  `EvalServiceRole`.
- **`evaluation/template.yaml:84-128`** — the existing
  `LambdaExecutionRole` shows the conventions for inline-policy `Sid`
  naming (`BedrockEvalJobPermissions`, `S3ReadPermissions`,
  `SNSPublishPermissions`, `PassEvalRolePermission`). Apply the same
  Sid-per-permission-group pattern to the new `EvalServiceRole`.
- **`.claude/specs/eval-bucket-autoprovision/intent.md`** — the
  immediately-preceding feature establishes the precedent of removing a
  required `parameter_overrides` key and inlining the resource into the
  template. Same tradeoff (workshop coupling vs production
  flexibility); same resolution (couple, document, recommend retain on
  fork). The auto-provision pattern is now the established norm for
  this stack.
- **`evaluation/lambdas/start_eval_job/handler.py:131-133`** — the
  Bedrock `CreateEvaluationJob` call site that consumes `roleArn`. This
  is the only place in the codebase that uses the role; nothing else
  references it.
- **`evaluation/template.yaml:71` (`EVAL_ROLE_ARN` env var) and `:482`
  (`EvalRoleArn` in the state machine DefinitionString substitution
  map)** — the two non-IAM references that must be updated. Plus the
  parameter declaration at `:18-22`, the LambdaExecutionRole
  `PassEvalRolePermission` at `:124-128`, and the samconfig override
  at `samconfig.toml:22`. Five references total.
- **AWS docs**:
  [Service roles for Amazon Bedrock model evaluation jobs](https://docs.aws.amazon.com/bedrock/latest/userguide/model-evaluation-security-iam.html)
  — the authoritative spec for the trust policy and the required
  permissions. The `aws:SourceAccount` confused-deputy guard is the
  recommended pattern there. The list of permissions in Goal 4 above is
  derived from this doc plus inspection of `start_eval_job/handler.py`
  to confirm which Bedrock APIs the role's policy must cover for a
  `RETRIEVE_AND_GENERATE` job specifically.
- **`evaluation/lambdas/start_eval_job/handler.py:131-181`** — the
  `create_evaluation_job` request body shows that the role must be able
  to read the dataset from `EvalBucket`, write to `output_s3_uri` in
  `ResultsBucket`, invoke the `modelArn` (generator) and
  `evaluatorModelConfig.bedrockEvaluatorModels[].modelIdentifier`
  (evaluator), and run RAG retrieval against the
  `knowledgeBaseConfiguration.knowledgeBaseId`. This grounds the four
  permission groups in Goal 4.
