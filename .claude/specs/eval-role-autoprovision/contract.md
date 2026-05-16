# Contract: eval-role-autoprovision

## Interfaces

### CloudFormation resource (new)

One new `AWS::IAM::Role` resource in `evaluation/template.yaml`,
inserted in the `Resources:` block alongside the other roles (next to
`LambdaExecutionRole` / `StepFunctionsExecutionRole` /
`EventBridgeInvocationRole` makes for the cleanest diff). The role
follows the established pattern from
`kb_provisioning/template.yaml:111-153`:

```yaml
EvalServiceRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub "${AWS::StackName}-eval-service-role"
    AssumeRolePolicyDocument:
      Version: "2012-10-17"
      Statement:
        - Effect: Allow
          Principal:
            Service: bedrock.amazonaws.com
          Action: sts:AssumeRole
          Condition:
            StringEquals:
              aws:SourceAccount: !Sub "${AWS::AccountId}"
    Policies:
      - PolicyName: EvalServicePolicy
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
            - Sid: ReadEvalBucket
              Effect: Allow
              Action:
                - s3:GetObject
                - s3:ListBucket
              Resource:
                - !GetAtt EvalBucket.Arn
                - !Sub "${EvalBucket.Arn}/*"

            - Sid: WriteResultsBucket
              Effect: Allow
              Action:
                - s3:PutObject
                - s3:GetObject
              Resource:
                - !Sub "${ResultsBucket.Arn}/*"

            - Sid: InvokeBedrockModels
              Effect: Allow
              Action:
                - bedrock:InvokeModel
              Resource:
                - !Sub "arn:${AWS::Partition}:bedrock:${AWS::Region}::foundation-model/${BedrockModelId}"
                - !Sub "arn:${AWS::Partition}:bedrock:${AWS::Region}::foundation-model/${EvaluatorModelId}"

            - Sid: RetrieveFromKnowledgeBase
              Effect: Allow
              Action:
                - bedrock:Retrieve
                - bedrock:RetrieveAndGenerate
              Resource:
                - !Sub "arn:${AWS::Partition}:bedrock:${AWS::Region}:${AWS::AccountId}:knowledge-base/${KnowledgeBaseId}"
```

Notes on the chosen shape:

- `RoleName` is explicit (named role) — matches the convention in
  `evaluation/template.yaml` for all four other IAM roles
  (`LambdaExecutionRole`, `StepFunctionsExecutionRole`,
  `EventBridgeInvocationRole`, `SeedEvalAssetsFunctionRole`) and works
  with the `CAPABILITY_NAMED_IAM` capability already declared in
  `samconfig.toml:13`.
- The trust statement is a list (`Statement: [...]`) even with a single
  element, matching `kb_provisioning/template.yaml:117`.
- The `aws:SourceAccount` condition is the AWS-recommended
  confused-deputy guard for Bedrock service roles. We deliberately omit
  `aws:SourceArn` (see intent.md "Non-Goals"); revisit only with
  empirical verification.
- `ReadEvalBucket` lists both `${EvalBucket.Arn}` (for `s3:ListBucket`)
  and `${EvalBucket.Arn}/*` (for `s3:GetObject`). `s3:ListBucket` is a
  bucket-level permission and IAM rejects object-level ARNs there;
  `s3:GetObject` requires `/*`. Both must appear in the Resource list
  for the statement to authorize both actions correctly.
- `WriteResultsBucket` lists only `${ResultsBucket.Arn}/*` because the
  Bedrock evaluation job writes objects but does not need
  `s3:ListBucket` to do so. `s3:GetObject` is kept for the rare case
  where Bedrock reads back its own output (e.g. job-restart scenarios);
  this matches the minimum-privilege guidance in the AWS Bedrock service
  role docs.
- The model ARN pattern uses `::foundation-model/<id>` (note the empty
  account-id between the colons — foundation models are an AWS-global
  resource, not account-scoped).
- The knowledge-base ARN pattern uses
  `:${AWS::AccountId}:knowledge-base/<id>` — KBs are account-scoped.
- `${AWS::Partition}` is used everywhere for partition portability
  (commercial / govcloud / cn-north).

### CloudFormation parameter (removed)

The following parameter is **removed** from `evaluation/template.yaml`:

- `EvalRoleArn` (was: required string at lines 18-22)

No new parameters are introduced. The four model/KB/account/region
substitutions used by the new role come from existing parameters
(`KnowledgeBaseId`, `BedrockModelId`, `EvaluatorModelId`) and the
intrinsic pseudo-parameters (`${AWS::Region}`, `${AWS::AccountId}`,
`${AWS::Partition}`).

### CloudFormation output (new)

```yaml
EvalServiceRoleArn:
  Description: >
    ARN of the Bedrock evaluation-job service role. Bedrock assumes this
    role when running RagEvaluation jobs created by start_eval_job.
    Provided for diagnostic visibility and future cross-stack references.
  Value: !GetAtt EvalServiceRole.Arn
  Export:
    Name: !Sub "${AWS::StackName}-EvalServiceRoleArn"
```

The output mirrors the shape of `KnowledgeBaseRoleArn` in
`kb_provisioning/template.yaml:357-361`. The export name uses the same
`${AWS::StackName}-<OutputKey>` convention as the other outputs in
`evaluation/template.yaml` (`StateMachineArn`, `SnsTopicArn`,
`EvalBucketName`, `ResultsBucketName`).

### Template references that must change

The following five references in `evaluation/template.yaml` change from
`!Ref EvalRoleArn` to `!GetAtt EvalServiceRole.Arn`:

| #  | Location (line in current file) | Old reference | New reference |
|----|---------------------------------|---------------|---------------|
| 1  | `Parameters.EvalRoleArn` (lines 18-22) | parameter declaration | removed |
| 2  | `Globals.Function.Environment.Variables.EVAL_ROLE_ARN` (line 71) | `!Ref EvalRoleArn` | `!GetAtt EvalServiceRole.Arn` |
| 3  | `LambdaExecutionRole.Policies.PassEvalRolePermission.Resource` (line 128) | `!Ref EvalRoleArn` | `!GetAtt EvalServiceRole.Arn` |
| 4  | `EvalPipelineStateMachine.DefinitionString` `!Sub` map (line 552) | `EvalRoleArn: !Ref EvalRoleArn` | `EvalRoleArn: !GetAtt EvalServiceRole.Arn` |
| 5  | `evaluation/samconfig.toml:22` `parameter_overrides` | `EvalRoleArn="..."` | removed |

Reference 4 is the only one where the substitution-map *key* stays
identical (`EvalRoleArn`) — the inline state-machine JSON at
template.yaml:361 references `${EvalRoleArn}` and does not need to
change. Only the right-hand side of the `!Sub` map entry changes.

### Lambda handler API (unchanged — explicit non-change for traceability)

The handler at `evaluation/lambdas/start_eval_job/handler.py` is
**not modified** by this feature. The relevant signature is reproduced
here for traceability:

```python
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Starts a Bedrock Knowledge Base RETRIEVE_AND_GENERATE evaluation job.

    Reads `role_arn` from event["eval_config"]["role_arn"], which is
    populated by the Step Functions state machine from the `${EvalRoleArn}`
    substitution variable. Passes role_arn unchanged to
    bedrock.create_evaluation_job(roleArn=role_arn, ...).

    No validation of role_arn's shape; the handler is agnostic to whether
    role_arn came from a CloudFormation Parameter !Ref or a !GetAtt
    on an in-stack IAM resource. See contract guarantee G2 below.
    """
```

The existing test file `evaluation/tests/test_start_eval_job.py` already
covers the `role_arn` propagation path; no new tests are required.

### Data Models

#### Trust policy (after this change)

```python
TrustPolicy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {
                    "aws:SourceAccount": "<account-id>"
                }
            },
        }
    ],
}
```

Exactly one statement, no `aws:SourceArn` (intentional — see
intent.md Non-Goals).

#### Inline policy (after this change)

```python
InlinePolicy = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ReadEvalBucket",
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:ListBucket"],
            "Resource": ["<EvalBucketArn>", "<EvalBucketArn>/*"],
        },
        {
            "Sid": "WriteResultsBucket",
            "Effect": "Allow",
            "Action": ["s3:PutObject", "s3:GetObject"],
            "Resource": ["<ResultsBucketArn>/*"],
        },
        {
            "Sid": "InvokeBedrockModels",
            "Effect": "Allow",
            "Action": ["bedrock:InvokeModel"],
            "Resource": [
                "arn:aws:bedrock:<region>::foundation-model/<BedrockModelId>",
                "arn:aws:bedrock:<region>::foundation-model/<EvaluatorModelId>",
            ],
        },
        {
            "Sid": "RetrieveFromKnowledgeBase",
            "Effect": "Allow",
            "Action": ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
            "Resource": [
                "arn:aws:bedrock:<region>:<account>:knowledge-base/<KnowledgeBaseId>"
            ],
        },
    ],
}
```

Exactly four statements. No `Action: "*"`. No `Resource: "*"`. No
`Resource: "arn:aws:s3:::*"` or similar wildcards on bucket paths.

### State Changes

CloudFormation owns all state. No in-process state.

- **Create**: CFN creates the `EvalServiceRole` IAM role with its trust
  policy and inline policy. No external side effects beyond IAM.
- **Update**: CFN diffs the role properties; common diffs are a change
  to `BedrockModelId`, `EvaluatorModelId`, or `KnowledgeBaseId`, which
  cause an in-place update of the inline policy's `Resource:` list. A
  rename of `${AWS::StackName}` would force-replace the role (CFN
  rebuilds it).
- **Delete**: CFN deletes the inline policy attached to the role,
  detaches any (none, by construction) managed policies, and deletes
  the role. The role has no associated instance profiles. Deletion is
  blocking on any in-flight Bedrock evaluation jobs that were created
  with this role's ARN; if such a job exists, `iam:DeleteRole` will
  fail with `DeleteConflict`. This is acceptable workshop behavior
  (attendees rarely `sam delete` mid-eval) and matches the IAM
  service's default behavior; document the failure mode in
  roadmap.md risk table.

### `samconfig.toml` change

Before:

```toml
parameter_overrides = "KnowledgeBaseId=\"...\" EvalRoleArn=\"arn:aws:iam::...:role/...\" BedrockModelId=\"...\" EvaluatorModelId=\"...\" NotificationEmail=\"...\" MaxPollingIterations=\"40\" PromptTemplatePrefix=\"prompts/\""
```

After:

```toml
parameter_overrides = "KnowledgeBaseId=\"...\" BedrockModelId=\"...\" EvaluatorModelId=\"...\" NotificationEmail=\"...\" MaxPollingIterations=\"40\" PromptTemplatePrefix=\"prompts/\""
```

Exactly the `EvalRoleArn=\"...\"` token (including the leading or
trailing space, whichever appears) is removed. All other
`parameter_overrides` keys are untouched.

## Behavior Guarantees

1. **G1**: After `sam deploy` of a fresh stack on a fresh account, an
   IAM role exists at name `${AWS::StackName}-eval-service-role`. Its
   trust policy permits `bedrock.amazonaws.com` to assume it, gated by
   `aws:SourceAccount: ${AWS::AccountId}`. Its inline policy
   `EvalServicePolicy` grants exactly the four statements described in
   the InlinePolicy data model above.
2. **G2**: The three existing Lambda handlers
   (`start_eval_job`, `check_eval_status`, `parse_eval_results`)
   continue to function without modification. The
   `EVAL_ROLE_ARN` environment variable still resolves at Lambda
   container startup to a valid IAM role ARN string; the handler does
   not inspect the ARN's syntactic shape. The Step Functions state
   machine still receives an `${EvalRoleArn}` substitution value;
   downstream `eval_config.role_arn` flows through to
   `bedrock.create_evaluation_job(roleArn=...)` byte-identical in
   shape (just with a different value).
3. **G3**: `Bedrock:CreateEvaluationJob` calls made by
   `start_eval_job/handler.py` succeed end-to-end. Bedrock assumes
   the role, reads the dataset / thresholds / prompt template from
   `EvalBucket`, writes evaluation output to
   `ResultsBucket/results/rag/`, invokes the generator model
   (`BedrockModelId`) and the evaluator model (`EvaluatorModelId`)
   in `${AWS::Region}`, and retrieves from the Knowledge Base
   (`KnowledgeBaseId`) — all without `AccessDeniedException` errors
   from the role's policy.
4. **G4**: The role cannot read or write any S3 bucket other than
   `EvalBucket` and `ResultsBucket`. (Verified by the explicit
   `Resource:` lists in the policy — no wildcards on bucket portion.)
5. **G5**: The role cannot invoke any Bedrock foundation model other
   than the two configured via `BedrockModelId` and `EvaluatorModelId`.
   In particular, it cannot invoke models in other regions (the
   `${AWS::Region}` baked into the ARN at deploy time pins the
   permitted region).
6. **G6**: The role cannot retrieve from any Knowledge Base other than
   the one configured via `KnowledgeBaseId`.
7. **G7**: The role cannot be assumed by any principal that is not
   `bedrock.amazonaws.com`, AND cannot be assumed even by Bedrock on
   behalf of a different AWS account (the `aws:SourceAccount` guard).
8. **G8**: `sam delete` removes the role atomically with the stack.
   No manual `aws iam delete-role` step is required, assuming no
   in-flight evaluation jobs hold the role. (If an in-flight job
   does exist, `DELETE_FAILED` surfaces in CFN events with the IAM
   `DeleteConflict` reason; attendee waits for the job to finish and
   retries `sam delete`.)
9. **G9**: `evaluation/samconfig.toml` `parameter_overrides` after
   this feature lands contains exactly six keys: `KnowledgeBaseId`,
   `BedrockModelId`, `EvaluatorModelId`, `NotificationEmail`,
   `MaxPollingIterations`, `PromptTemplatePrefix`. The
   `EvalRoleArn=...` token does not appear.
10. **G10**: The `EvalServiceRoleArn` output is queryable via
    `aws cloudformation describe-stacks --query
    'Stacks[0].Outputs[?OutputKey==\`EvalServiceRoleArn\`].OutputValue'`
    and the value matches
    `aws iam get-role --role-name <stack>-eval-service-role --query
    'Role.Arn'`.
11. **G11**: All 107 existing unit tests in `evaluation/tests/`
    continue to pass without modification. The three new feature
    tests added by `eval-bucket-autoprovision`
    (`test_seed_eval_assets.py`, `test_upload_prompt_template.py`,
    plus regression handlers) are unaffected. No new test file is
    added by this feature.
12. **G12**: The `CLAUDE.md` "Evaluation pipeline" section after this
    change makes no mention of pre-creating an IAM role. Searching
    for `"role"` in that section returns only references to the
    auto-provisioned `EvalServiceRole` (or no references — both are
    acceptable).
13. **G13**: `sam validate -t evaluation/template.yaml` (run from the
    `evaluation/` directory) returns exit code 0 after the change.

## Error Handling Contract

| Error Condition | Behavior | User Impact |
|---|---|---|
| Attendee passes a foundation-model ARN (e.g. `arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0`) as `BedrockModelId` instead of a plain ID | `!Sub` produces a doubled prefix (`arn:aws:bedrock:us-east-1::foundation-model/arn:aws:bedrock:us-east-1::foundation-model/...`), which is a syntactically-valid ARN that does not match any real model | `bedrock:InvokeModel` denied at job runtime. Bedrock evaluation job fails with `AccessDeniedException`. Step Functions `StartRetrieveAndGenerateJob` task retries 2x then routes to `PrepareFailureMessage`; attendee sees a FAILED SNS notification with the underlying Bedrock error. Mitigation: update the parameter description to call out "plain model ID, not ARN" for the workshop default. |
| Attendee passes a cross-region inference profile ID (e.g. `us.amazon.nova-pro-v1:0`) as `BedrockModelId` | `!Sub` produces `arn:aws:bedrock:<region>::foundation-model/us.amazon.nova-pro-v1:0` which is not a real ARN; `bedrock:InvokeModel` permission does not cover the actual inference-profile call | Same outcome as the ARN-as-ID case: `AccessDeniedException` at job runtime. Workshop attendees on the default `amazon.nova-pro-v1:0` are unaffected; advanced users must fork. |
| Attendee passes a `KnowledgeBaseId` that does not exist in the deploy account/region | Role creation succeeds (CFN does not validate KB existence at role-create time). `bedrock:CreateEvaluationJob` fails with `ResourceNotFoundException` from `start_eval_job/handler.py` before any role assumption | Step Functions `StartRetrieveAndGenerateJob` retries 2x and then routes to `PrepareFailureMessage`. Attendee sees SNS failure with `ResourceNotFoundException` reason. Same failure mode as today. |
| Bedrock evaluation job is in `IN_PROGRESS` at `sam delete` time | IAM `DeleteRole` fails with `DeleteConflict` because the job has the role assumed | `DELETE_FAILED` stack state. Attendee waits for the eval job to finish (or cancels it via `bedrock:StopEvaluationJob`), then retries `sam delete`. Documented in roadmap risk table. |
| Existing stack with `EvalRoleArn` parameter is updated to the new template | The `EvalRoleArn` parameter no longer exists; CFN drift if the user passes it as `--parameter-overrides EvalRoleArn=...` | `sam deploy` rejects the parameter override with "Parameter EvalRoleArn does not exist". Attendee removes the override from `samconfig.toml` (Phase 3 of roadmap covers this) and retries. |
| Network/IAM eventual-consistency delay between role creation and first `CreateEvaluationJob` call | IAM creates the role asynchronously; the first Bedrock call may hit `iam:GetRole` before propagation completes | `bedrock:CreateEvaluationJob` returns `ValidationException: roleArn is invalid`. Step Functions retry policy (2 attempts, backoff 2.0, interval 10s) covers the typical 1-3s IAM propagation window. No code change needed; the existing retry config is sufficient. Documented in roadmap risk table. |

## Dependencies

### Internal module dependencies

- `evaluation/template.yaml` — the template being modified.
- `evaluation/samconfig.toml` — the parameter-overrides file.
- `CLAUDE.md` — the documentation file at repo root.
- `evaluation/lambdas/start_eval_job/handler.py` — **unchanged**;
  consumer of the `EVAL_ROLE_ARN` env var.
- `evaluation/tests/test_start_eval_job.py` — **unchanged**;
  regression coverage for the consumer.
- `evaluation/lambdas/seed_eval_assets/`,
  `evaluation/scripts/prepare_lambda_assets.py`,
  `evaluation/scripts/upload_prompt_template.py` — **unchanged**;
  produced by the previous feature.

### External package dependencies

None. This feature is template + samconfig + CLAUDE.md only. No
Python imports change; no `requirements*.txt` files change.

### CloudFormation features used

- Intrinsic functions: `!Sub`, `!GetAtt`, `!Ref`.
- Intrinsic pseudo-parameters: `AWS::Region`, `AWS::AccountId`,
  `AWS::Partition`, `AWS::StackName`.
- IAM role with inline policy (no managed policies; no permissions
  boundary).
- No conditions, no transforms beyond `AWS::Serverless-2016-10-31`
  already declared.

## Integration Points

- **`bedrock:CreateEvaluationJob` (consumed by `start_eval_job`).**
  Bedrock assumes `EvalServiceRole` to run the job. The role's S3
  permissions cover the four canonical S3 URIs (`datasets/rag_eval.jsonl`,
  `baselines/thresholds.json`, `prompts/kb_prompt_template.txt`,
  `results/rag/`). The role's Bedrock permissions cover the generator
  model, the evaluator model, and KB retrieval.
- **Step Functions state machine (`EvalPipelineStateMachine`).** The
  `DefinitionString` substitution map now sources `EvalRoleArn` from
  `!GetAtt EvalServiceRole.Arn` instead of `!Ref EvalRoleArn`. The
  state machine JSON itself is unchanged.
- **Lambda execution role (`LambdaExecutionRole`).** Its
  `PassEvalRolePermission` inline statement now scopes `iam:PassRole`
  to `!GetAtt EvalServiceRole.Arn`. The permission is still required
  because `start_eval_job/handler.py` passes the role ARN to
  `bedrock.create_evaluation_job`, which counts as a `PassRole` action.
- **CloudFormation stack outputs.** `EvalServiceRoleArn` joins the
  existing six outputs (`StateMachineArn`, `SnsTopicArn`,
  `StartEvalJobFunctionArn`, `CheckEvalStatusFunctionArn`,
  `ParseEvalResultsFunctionArn`, `EvalBucketName`, `ResultsBucketName`)
  as the eighth output of the stack.
- **`samconfig.toml` parameter overrides.** Shortened from seven keys
  to six. The remaining keys feed the new `EvalServiceRole`'s policy
  resources (`BedrockModelId`, `EvaluatorModelId`, `KnowledgeBaseId`)
  and unrelated stack inputs (`NotificationEmail`,
  `MaxPollingIterations`, `PromptTemplatePrefix`).
- **`CLAUDE.md` "Evaluation pipeline" section.** Drop the
  pre-create-the-role guidance (the section already mentions only
  `KnowledgeBaseId` and seed assets; if any IAM-role wording exists in
  the broader doc, sweep it). Confirm no `EvalRoleArn` references
  remain.
- **No integration with `kb_provisioning/`.** The KB provisioning stack
  has its own `KnowledgeBaseRole` (a different role for a different
  purpose — KB ingestion vs evaluation). The two roles are
  independent; this feature does not touch `kb_provisioning/`.
- **No integration with the LangGraph app (root).** The application at
  `main.py` / `src/` uses its own AWS credentials (from `.env`) and
  does not assume any IAM role. The `EvalServiceRole` is exclusively
  consumed by Bedrock during evaluation-job execution.
