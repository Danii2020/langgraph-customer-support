# Contract: eval-bucket-autoprovision

## Interfaces

### CloudFormation resources (new)

Two new `AWS::S3::Bucket` resources in `evaluation/template.yaml`:

```yaml
# Eval bucket — hosts datasets, thresholds, and prompt templates.
# EventBridge notifications are enabled so PromptTemplateChangeRule
# can fire on PUTs under prompts/.
EvalBucket:
  Type: AWS::S3::Bucket
  Properties:
    BucketName: !Sub "${AWS::StackName}-eval-${AWS::AccountId}-${AWS::Region}"
    NotificationConfiguration:
      EventBridgeConfiguration:
        EventBridgeEnabled: true

# Results bucket — Bedrock writes RetrieveAndGenerate eval output here.
# No EventBridge notifications needed; Bedrock writes are not a trigger.
ResultsBucket:
  Type: AWS::S3::Bucket
  Properties:
    BucketName: !Sub "${AWS::StackName}-eval-results-${AWS::AccountId}-${AWS::Region}"
```

One new IAM role for the seed Lambda:

```yaml
SeedEvalAssetsFunctionRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub "${AWS::StackName}-seed-eval-assets-role"
    AssumeRolePolicyDocument:
      Version: "2012-10-17"
      Statement:
        - Effect: Allow
          Principal: { Service: lambda.amazonaws.com }
          Action: sts:AssumeRole
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    Policies:
      - PolicyName: SeedEvalAssetsPolicy
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
            - Sid: EvalBucketWriteAccess
              Effect: Allow
              Action:
                - s3:PutObject
                - s3:DeleteObject
                - s3:ListBucket
                - s3:GetObject
              Resource:
                - !GetAtt EvalBucket.Arn
                - !Sub "${EvalBucket.Arn}/*"
            - Sid: ResultsBucketEmptyOnDelete
              Effect: Allow
              Action:
                - s3:DeleteObject
                - s3:ListBucket
                - s3:GetObject
              Resource:
                - !GetAtt ResultsBucket.Arn
                - !Sub "${ResultsBucket.Arn}/*"
```

One new Lambda function:

```yaml
SeedEvalAssetsFunction:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: !Sub "${AWS::StackName}-seed-eval-assets"
    CodeUri: lambdas/seed_eval_assets/
    Handler: handler.handler
    Role: !GetAtt SeedEvalAssetsFunctionRole.Arn
    Description: >
      CloudFormation custom resource: uploads dataset, thresholds, and
      prompt template files to EvalBucket on stack Create; empties both
      EvalBucket and ResultsBucket on stack Delete.
```

One new custom resource:

```yaml
SeedEvalAssetsCustomResource:
  Type: AWS::CloudFormation::CustomResource
  DependsOn:
    - EvalBucket
    - ResultsBucket
  Properties:
    ServiceToken: !GetAtt SeedEvalAssetsFunction.Arn
    EvalBucketName: !Ref EvalBucket
    ResultsBucketName: !Ref ResultsBucket
    Region: !Ref AWS::Region
```

### CloudFormation outputs (new)

```yaml
EvalBucketName:
  Description: >
    Resolved eval bucket name (datasets, thresholds, prompts).
    Read by evaluation/scripts/upload_prompt_template.py to locate the
    bucket for the prompt-template-retrigger workshop demo step.
  Value: !Ref EvalBucket
  Export:
    Name: !Sub "${AWS::StackName}-EvalBucketName"

ResultsBucketName:
  Description: Resolved results bucket name (Bedrock eval job output).
  Value: !Ref ResultsBucket
  Export:
    Name: !Sub "${AWS::StackName}-ResultsBucketName"
```

**Public API note (G11 below).** The `EvalBucketName` output is a stable
contract — `upload_prompt_template.py` reads it by name. Do not rename or
remove this output without bumping the demo script in lockstep.

### CloudFormation parameters (removed)

The following three parameters are **removed** from
`evaluation/template.yaml`:

- `EvalBucketName` (was: required string)
- `ResultsBucketName` (was: required string)
- `PromptTemplateBucketName` (was: optional string, default `""`)

The `PromptTemplatePrefix` parameter is **retained** (still used by
`PromptTemplateChangeRule` to scope the trigger).

### Lambda handler API

The seed Lambda lives at
`evaluation/lambdas/seed_eval_assets/handler.py` and exposes:

```python
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    CloudFormation custom resource handler.

    Lifecycle:
      Create  -- upload SEED_FILES to EvalBucket at canonical keys; return
                 {"FilesUploaded": "<count>"}.
      Update  -- no-op if EvalBucketName and ResultsBucketName are unchanged;
                 otherwise re-upload to the new EvalBucket.
      Delete  -- empty EvalBucket and ResultsBucket (paginated) so CFN can
                 remove them; return {}.

    Always sends a CFN response to event["ResponseURL"] -- success or
    failure -- via send_cfn_response(). Never raises.

    ResourceProperties (from CloudFormation):
        {
          "EvalBucketName": "<bucket>",
          "ResultsBucketName": "<bucket>",
          "Region": "us-east-1"
        }
    """

def upload_seed_assets(s3_client: Any, bucket: str) -> list[str]:
    """
    Upload every (local_filename, s3_key) pair in SEED_FILES to bucket.
    Returns the list of S3 keys uploaded.
    Missing local files are silently skipped (logged via print).
    """

def empty_bucket(s3_client: Any, bucket: str) -> None:
    """
    Delete every object (and versions/delete-markers if versioning was
    enabled) under bucket. Idempotent: empty bucket is a no-op.
    Mirrors kb_provisioning/lambdas/seed_and_ingest/handler.py:empty_bucket.
    """

def send_cfn_response(
    event: dict[str, Any],
    context: Any,
    status: str,                        # "SUCCESS" or "FAILED"
    data: dict[str, Any] | None = None,
    physical_resource_id: str | None = None,
    reason: str | None = None,
) -> None:
    """
    PUT a JSON-encoded response body to event["ResponseURL"].
    Body shape: {Status, Reason, PhysicalResourceId, StackId, RequestId,
                 LogicalResourceId, Data}.
    Network failure is fatal (the handler caller wraps in try/except).
    """
```

### Module-level constants in `handler.py`

```python
# Directory packaged by sam build alongside handler.py. Populated by
# evaluation/scripts/prepare_lambda_assets.py before each sam build.
SEED_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "seed_assets")

# (local_filename, s3_key) pairs. Local filenames are looked up under
# SEED_ASSETS_DIR; s3_keys are written verbatim into the eval bucket.
# These S3 keys MUST match the values hard-coded into
# KbSyncCompletionRule.Input and PromptTemplateChangeRule.Input.
SEED_FILES: list[tuple[str, str]] = [
    ("evaluation_dataset.jsonl", "datasets/rag_eval.jsonl"),
    ("thresholds.json",          "baselines/thresholds.json"),
    ("kb_prompt_template.txt",   "prompts/kb_prompt_template.txt"),
]

# Tracked across Update; if any value changes the Lambda re-uploads.
_TRACKED_KEYS = ("EvalBucketName", "ResultsBucketName")
```

### Pre-build helper script API

```python
# evaluation/scripts/prepare_lambda_assets.py

def main() -> None:
    """
    Copy the three seed files from their canonical source locations into
    evaluation/lambdas/seed_eval_assets/seed_assets/ so sam build packages
    them with the Lambda function.

    Copy map (source -> dest, all under repo_root):
      evaluation/dataset/evaluation_dataset.jsonl ->
        evaluation/lambdas/seed_eval_assets/seed_assets/evaluation_dataset.jsonl
      evaluation/config/thresholds.json ->
        evaluation/lambdas/seed_eval_assets/seed_assets/thresholds.json
      evaluation/prompts/kb_prompt_template.txt ->
        evaluation/lambdas/seed_eval_assets/seed_assets/kb_prompt_template.txt

    Run before every sam build:
        python evaluation/scripts/prepare_lambda_assets.py

    Idempotent: rerunning overwrites the destination files with identical
    contents -- no side effects. Missing sources are warned but not fatal
    (matches kb_provisioning/scripts/prepare_lambda_assets.py:32-35).
    """
```

### Workshop demo script API (upgraded)

```python
# evaluation/scripts/upload_prompt_template.py
#
# Replaces the current positional-<bucket> script. New invocation:
#
#   # Happy-path workshop demo (no arguments needed):
#   python evaluation/scripts/upload_prompt_template.py
#
#   # Explicit overrides:
#   python evaluation/scripts/upload_prompt_template.py \
#       --stack-name rag-eval-pipeline \
#       --region us-east-1 \
#       --template evaluation/prompts/kb_prompt_template.txt \
#       --prefix prompts/
#
#   # Escape hatch (skip stack lookup):
#   python evaluation/scripts/upload_prompt_template.py \
#       --bucket my-eval-bucket
#
# Behavior:
#   1. Parse argparse args.
#   2. If --bucket is provided, use it verbatim and skip step 3.
#   3. Otherwise: call cloudformation.describe_stacks(StackName=args.stack_name);
#      read Outputs[].OutputKey == "EvalBucketName" -> OutputValue; use that.
#      Raise a friendly error if the stack does not exist or the output is
#      missing (with a hint to run `sam deploy` first).
#   4. boto3 s3.upload_file(args.template, bucket, "<prefix>kb_prompt_template.txt").
#   5. print(f"Uploaded to s3://{bucket}/{key}") and exit 0.
#
# Constraints:
#   - argparse only, no click/typer.
#   - boto3 only, no third-party HTTP libs.
#   - Default --stack-name = "rag-eval-pipeline" (matches
#     evaluation/samconfig.toml:11 `stack_name`).
#   - Default --region    = "us-east-1" (matches samconfig.toml:12).
#   - Default --prefix    = "prompts/" (matches the existing argument's
#     default and the canonical S3 prefix the Lambda seeds to).
#   - Default --template  = evaluation/prompts/kb_prompt_template.txt
#     (resolved relative to the script directory, matching the current
#     implementation at evaluation/scripts/upload_prompt_template.py:21-25).

def main() -> None:
    """argparse entrypoint. See module docstring for behavior contract."""

def resolve_eval_bucket(
    cfn_client: Any,
    stack_name: str,
) -> str:
    """
    Look up the EvalBucketName output of stack_name via DescribeStacks.

    Raises:
      RuntimeError: if the stack does not exist, with a one-line hint.
      KeyError:     if the stack exists but the EvalBucketName output is
                    not present (means an old stack or a deploy mid-flight).

    Pure function -- takes cfn_client as a parameter so unit tests can
    inject a MagicMock without monkeypatching boto3.
    """
```

### Data Models

#### CloudFormation custom resource event

```python
# Standard CFN custom resource event shape (sent by CloudFormation to the
# Lambda over a synchronous invoke):
CloudFormationCustomResourceEvent = {
    "RequestType":         "Create" | "Update" | "Delete",
    "ResponseURL":         str,  # pre-signed S3 URL for the response
    "StackId":             str,  # full CFN stack ARN
    "RequestId":           str,  # unique per CFN request
    "LogicalResourceId":   str,  # "SeedEvalAssetsCustomResource"
    "PhysicalResourceId":  str,  # provided on Update/Delete only
    "ResourceProperties": {
        "EvalBucketName":    str,
        "ResultsBucketName": str,
        "Region":            str,
    },
    # Update-only:
    "OldResourceProperties": dict | None,
}
```

#### CloudFormation custom resource response

```python
# JSON body PUT to ResponseURL:
CloudFormationCustomResourceResponse = {
    "Status":             "SUCCESS" | "FAILED",
    "Reason":             str,   # required if Status == "FAILED"
    "PhysicalResourceId": str,   # stable identifier for the resource
    "StackId":            str,
    "RequestId":          str,
    "LogicalResourceId":  str,
    "Data": {                    # surfaced via !GetAtt Custom.Foo on Create
        "FilesUploaded": str,    # str(int) — CFN coerces all Data values
                                 # to strings anyway
    },
}
```

### State Changes

CloudFormation owns all state. There is no in-process state outside the
Lambda execution context.

- **Create**: writes three S3 objects under `EvalBucket` at the canonical
  keys (`datasets/rag_eval.jsonl`, `baselines/thresholds.json`,
  `prompts/kb_prompt_template.txt`). No writes to `ResultsBucket`.
- **Update**: when `EvalBucketName` or `ResultsBucketName` change in the
  CFN diff, re-uploads the three seed objects to the new `EvalBucket`.
  (In practice this branch is exercised only if a future change replaces
  the bucket via `BucketName` modification.) Otherwise no-op.
- **Delete**: removes every object in both `EvalBucket` and
  `ResultsBucket`, including versions / delete-markers if versioning was
  ever enabled. No Bedrock or other side effects.
- **Workshop demo re-upload (out of band of CFN)**: when
  `upload_prompt_template.py` PUTs to
  `s3://<EvalBucket>/prompts/kb_prompt_template.txt`, the
  `EventBridgeEnabled: true` setting causes EventBridge to publish an
  "Object Created" event, which `PromptTemplateChangeRule` matches and
  forwards to `EvalPipelineStateMachine`. CloudFormation is not involved
  in this path.

### Template references that must change

The following lines in `evaluation/template.yaml` change from
`!Ref <parameter>` to a resource reference:

| Location (line in current file)                | Old reference          | New reference         |
|-----------------------------------------------|------------------------|-----------------------|
| `Globals.Function.Environment.EVAL_BUCKET_NAME` (line ~92) | `!Ref EvalBucketName`  | `!Ref EvalBucket`     |
| `LambdaExecutionRole.Policies.S3ReadPermissions.Resource` (lines 137-140) | `!Sub "arn:aws:s3:::${EvalBucketName}"` etc | `!GetAtt EvalBucket.Arn` + `!Sub "${EvalBucket.Arn}/*"` + `!GetAtt ResultsBucket.Arn` + `!Sub "${ResultsBucket.Arn}/*"` |
| `KbSyncCompletionRule.Targets[0].Input` (line 514-520) | `${EvalBucketName}` / `${ResultsBucketName}` in inline JSON | `${EvalBucket}` / `${ResultsBucket}` (since `!Sub` resolves `!Ref` for these resources to the bucket name) |
| `PromptTemplateChangeRule.EventPattern.detail.bucket.name` (line 545) | `!Ref PromptTemplateBucketName` | `!Ref EvalBucket` |
| `PromptTemplateChangeRule.Targets[0].Input` (lines 554-560) | `${EvalBucketName}` / `${ResultsBucketName}` | `${EvalBucket}` / `${ResultsBucket}` |

## Behavior Guarantees

1. **G1**: After `sam deploy` of a fresh stack on a fresh account, the
   eval bucket exists, the results bucket exists, and the three canonical
   S3 keys are populated with content byte-identical to the local source
   files under `evaluation/dataset/`, `evaluation/config/`, and
   `evaluation/prompts/`.
2. **G2**: After `sam deploy`, the eval bucket's
   `NotificationConfiguration.EventBridgeConfiguration.EventBridgeEnabled`
   is `true`; uploading any object with key matching
   `${PromptTemplatePrefix}*` triggers `EvalPipelineStateMachine` with no
   manual `aws s3api put-bucket-notification-configuration` call.
3. **G3**: The `EvalPipelineStateMachine` input JSON (from both
   EventBridge rules) contains the same four canonical S3 URIs it
   contained before this feature — only the bucket portion changes from a
   parameter-derived name to a CloudFormation-resolved name. Downstream
   Lambda handlers (`start_eval_job`, `parse_eval_results`) see no
   behavioral change.
4. **G4**: `sam delete` succeeds on a stack whose buckets contain
   arbitrary objects (including any `results/rag/*` data written by
   Bedrock during evaluation runs). No manual bucket emptying is
   required.
5. **G5**: Bucket names are deterministic per `(StackName, AccountId,
   Region)`. Two attendees running the same `sam deploy` in different
   accounts get different bucket names; two attempts to deploy the same
   stack twice into the same account/region get the same bucket name (and
   so the second deploy fails idempotently on the existing bucket — which
   is the correct CloudFormation behavior).
6. **G6**: The Lambda handler always sends a CFN response. Any exception
   inside `handler()` is caught and converted to a `Status: "FAILED"`
   response containing `f"{type(exc).__name__}: {exc}"` in the `Reason`
   field. `handler()` never raises, regardless of input.
7. **G7**: The `SeedEvalAssetsFunctionRole` cannot put or delete objects
   in any bucket other than `EvalBucket` and `ResultsBucket`. (Verified
   by the `Resource:` list in the IAM policy — no wildcards on the
   bucket portion.)
8. **G8**: `prepare_lambda_assets.py` is idempotent and side-effect-free
   beyond the three destination file writes. Rerunning it with the same
   source files produces byte-identical destination files.
9. **G9**: All three existing Lambda handler unit tests
   (`test_start_eval_job.py`, `test_check_eval_status.py`,
   `test_parse_eval_results.py`) continue to pass without modification —
   the migration does not change any handler code or contract.
10. **G10**: The `samconfig.toml` `parameter_overrides` line is
    self-contained for a fresh deploy. After this feature lands, a clean
    checkout of the repo with only `KnowledgeBaseId`, `EvalRoleArn`, model
    IDs, `NotificationEmail`, polling iterations, and
    `PromptTemplatePrefix` set (the existing six non-bucket parameters)
    is sufficient to deploy.
11. **G11**: `python evaluation/scripts/upload_prompt_template.py` with
    no positional arguments and default flags succeeds against a
    deployed stack named `rag-eval-pipeline` in `us-east-1`. It uploads
    `evaluation/prompts/kb_prompt_template.txt` to
    `s3://<EvalBucket>/prompts/kb_prompt_template.txt` and returns
    exit code 0. The upload causes a new
    `EvalPipelineStateMachine` execution to begin within ~30 seconds
    via `PromptTemplateChangeRule`.
12. **G12**: The CFN `Outputs.EvalBucketName.Export.Name` is
    `"${AWS::StackName}-EvalBucketName"` and the
    `Outputs.EvalBucketName.OutputKey` is `"EvalBucketName"`. These two
    identifiers are part of the public API of the stack and must not be
    renamed without bumping `upload_prompt_template.py` in the same
    commit.
13. **G13**: `evaluation/scripts/setup_s3.py` is deleted; no file by that
    name exists in the repository.

## Error Handling Contract

| Error Condition | Behavior | User Impact |
|---|---|---|
| Seed file missing from `SEED_ASSETS_DIR` at Lambda invocation time | Skip the missing file (logged via `print`); upload the rest | Stack `CREATE_COMPLETE`s but the eval bucket is missing the skipped file. Step Functions execution will fail later when `start_eval_job` reads the missing `prompt_template_s3_uri` (or `parse_eval_results` reads the missing `thresholds_s3_uri`). Diagnostic note: attendee forgot to run `prepare_lambda_assets.py` before `sam build`. |
| `s3:PutObject` denied on `EvalBucket` | Catch exception; send `Status: "FAILED"`, `Reason: "<ExcType>: <msg>"`; return normally | Stack rolls back to `CREATE_FAILED`. CFN events surface the reason. |
| `s3:ListBucket` denied on either bucket during Delete | Catch exception; send `Status: "FAILED"` | Stack hangs in `DELETE_FAILED`; manual remediation (delete role policy, retry delete) required. Documented in roadmap risk table. |
| `s3:DeleteObject` partial failure (e.g. bucket too large / paginated > 1000 objects per page) | Lambda paginates `list_objects_v2`; each page deletes in a single batch up to 1000 keys; loop continues to next page | Transparent; bucket fully emptied. |
| Bedrock writes a versioned object to `ResultsBucket` (theoretically) | `empty_bucket()` falls through to `list_object_versions` pagination and deletes versions + delete markers | Transparent; bucket fully emptied. |
| Network failure PUTting to `event["ResponseURL"]` | `urllib.request.urlopen` raises; the Lambda invocation fails; CFN times out after 1 hour | Stack hangs for 1 hour then rolls back with `CFN_TIMEOUT_OUT_OF_BAND`. Same failure mode as `kb_provisioning/` — documented constraint, not a regression. |
| `RequestType` not in `{Create, Update, Delete}` | Raise `ValueError`; caught by handler envelope; sends `Status: "FAILED"` | Stack rolls back; reason surfaces in CFN events. Should never happen in practice (CFN only sends those three values). |
| `upload_prompt_template.py` invoked before the stack is deployed | `resolve_eval_bucket()` raises `RuntimeError` with hint: "Stack '<name>' not found. Run `sam deploy` first or pass --bucket explicitly." Exit code != 0. | Attendee sees a friendly error, fixes the order, and reruns. |
| `upload_prompt_template.py` invoked against a stack that exists but lacks the `EvalBucketName` output (e.g. mid-deploy or old stack) | `resolve_eval_bucket()` raises `KeyError` mentioning `"EvalBucketName"`. Exit code != 0. | Attendee waits for `sam deploy` to finish, or upgrades their stack. |
| `upload_prompt_template.py` IAM denial on `cloudformation:DescribeStacks` | boto3 raises `ClientError`; the script does not catch it and exits with the boto3 traceback | Attendee sees stderr error; fix is to use AWS creds that include `cloudformation:DescribeStacks` (the workshop credentials already do). |

## Dependencies

### Internal module dependencies

- `evaluation/dataset/evaluation_dataset.jsonl` — source for the seed
  asset packaged into the Lambda; copied at build time by
  `prepare_lambda_assets.py`.
- `evaluation/config/thresholds.json` — source for the seed asset.
- `evaluation/prompts/kb_prompt_template.txt` — source for the seed
  asset and the runtime artifact uploaded by
  `upload_prompt_template.py` during the workshop demo.
- `evaluation/tests/conftest.py` — extended with a `make_cfn_event`
  factory mirroring `kb_provisioning/tests/conftest.py:35-68`. Existing
  fixtures (`sample_thresholds`, `mock_s3_client`, `mock_bedrock_client`,
  etc.) are not modified.

### External package dependencies

- Lambda runtime: `python3.13` (already in `Globals.Function.Runtime`).
- Lambda deps: `boto3` (provided by the Lambda runtime) and stdlib
  (`json`, `os`, `urllib.request`). No `requirements.txt` is added to
  the Lambda CodeUri — same pattern as the existing three Lambdas.
- `upload_prompt_template.py` deps: `boto3` (the attendee installs it
  with `pip install boto3` or via the workshop's existing venv). No
  third-party CLI libs.
- Test deps: `pytest>=8.0.0`, `pytest-mock>=3.12.0`, `pytest-cov>=5.0.0`
  — already in `evaluation/requirements-dev.txt`; no changes needed.

## Integration Points

- **CloudFormation custom resource lifecycle** — Create runs during
  stack `CREATE`, Update runs during stack `UPDATE` (no-op unless tracked
  properties change), Delete runs during stack `DELETE` and during stack
  `ROLLBACK_IN_PROGRESS` after a failed Create. The handler's exception
  envelope ensures rollback succeeds even if seed-data uploads partly
  fail.
- **EventBridge `PromptTemplateChangeRule`** — relies on the
  `EvalBucket.NotificationConfiguration.EventBridgeConfiguration` setting.
  Switching `EventPattern.detail.bucket.name` from `!Ref
  PromptTemplateBucketName` to `!Ref EvalBucket` retains the existing
  behavior for the bucket attendees actually use (which was, in 95%+ of
  workshops, the same bucket as `EvalBucketName`).
- **EventBridge `KbSyncCompletionRule`** — independent of the bucket
  change; the rule fires on a Bedrock event, not an S3 event. Its
  `Targets[0].Input` JSON does change (bucket names in URIs come from
  `!Sub "${EvalBucket}"` instead of `!Sub "${EvalBucketName}"`), but the
  output URIs are byte-identical when the same bucket name resolves.
- **`upload_prompt_template.py` → CloudFormation Outputs**. The demo
  script reads the `EvalBucketName` stack output via
  `cloudformation:DescribeStacks`. The export name and output key are
  contracts (see G12). This is the only attendee-facing read of the CFN
  outputs surface.
- **`upload_prompt_template.py` → EventBridge**. The script's
  `s3.upload_file()` causes S3 to emit an "Object Created" EventBridge
  event under the eval bucket. `PromptTemplateChangeRule` matches and
  triggers a Step Functions execution. The script does **not** wait for
  the execution to finish — it returns immediately after the upload
  succeeds. This is intentional: the workshop instructor switches to the
  Step Functions console to narrate the run.
- **`evaluation/samconfig.toml`** — the `parameter_overrides` line is
  shortened by dropping three keys. The remaining seven parameters
  (`KnowledgeBaseId`, `EvalRoleArn`, `BedrockModelId`,
  `EvaluatorModelId`, `NotificationEmail`, `MaxPollingIterations`,
  `PromptTemplatePrefix`) remain unchanged. The `stack_name` value
  (`"rag-eval-pipeline"`) is the implicit default
  `upload_prompt_template.py` uses for its `--stack-name` flag —
  keep these two values in sync.
- **`CLAUDE.md`** — the "Evaluation pipeline" command section is updated
  in two places:
  1. Replace the two existing setup commands (`setup_s3.py` and
     `upload_prompt_template.py <bucket>`) in the deploy workflow with a
     single `python evaluation/scripts/prepare_lambda_assets.py` line
     before `sam build`. Same shape as the existing
     `python kb_provisioning/scripts/prepare_lambda_assets.py` instruction.
  2. Add a new "Retrigger the pipeline" / "Workshop demo" subsection
     showing the new
     `python evaluation/scripts/upload_prompt_template.py` invocation
     with no arguments, with a one-line note that the script resolves
     the eval bucket from the CFN stack output.
- **`EvalRoleArn` parameter (no change)** — the Bedrock evaluation role
  passed via `EvalRoleArn` must already have access to read the eval
  dataset/prompts and write to the results bucket. This is a workshop
  prerequisite that survives this feature unchanged; document in
  `intent.md` "Non-Goals" that we are not auto-provisioning that role.
