# Contract: KB Provisioning

## Interfaces

### CloudFormation Stack Inputs (Parameters)

These are declared in `kb_provisioning/template.yaml` and surfaced to attendees via `kb_provisioning/samconfig.toml`'s `parameter_overrides` (same pattern as `evaluation/samconfig.toml`).

| Name | Type | Default | Description |
|---|---|---|---|
| `KnowledgeBaseName` | String | `workshop-kb` | Bedrock KB display name. Must be unique within the account/region. Used as the suffix base for resource names. |
| `SourceBucketName` | String | `""` (empty → auto-generate) | Optional override for the source S3 bucket name. If empty, the stack uses `${AWS::StackName}-source-${AWS::AccountId}-${AWS::Region}`. |
| `VectorBucketName` | String | `""` (empty → auto-generate) | Optional override for the S3 Vectors bucket name. If empty, the stack uses `${AWS::StackName}-vectors-${AWS::AccountId}-${AWS::Region}`. Must be 3–63 chars, lowercase + digits + `-`. |
| `VectorIndexName` | String | `workshop-kb-index` | S3 Vectors index name (scoped within the vector bucket). |
| `EmbeddingModelArn` | String | `arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0` | Embedding model ARN. The default targets Titan v2 in `us-east-1`. If the attendee changes `region` in `samconfig.toml`, they must override this parameter to match. |
| `SourceDataPrefix` | String | `data/` | S3 key prefix under the source bucket where the seed Lambda uploads `policies.txt` and `data.txt`, and which the Bedrock DataSource scans via `InclusionPrefixes`. |
| `EmbeddingDimension` | Number | `1024` | Vector dimension. Must match the embedding model. Titan v2 = 1024. |
| `DistanceMetric` | String | `COSINE` | One of `COSINE`, `EUCLIDEAN`, `DOT_PRODUCT`. Titan v2 recommends `COSINE`. |
| `EnableAutoIngestion` | String | `true` | If `true`, the seed-and-ingest custom resource runs on stack `Create` and starts an ingestion job. If `false`, attendees must trigger ingestion manually via `kb_provisioning/scripts/seed_and_ingest.py`. |

### CloudFormation Stack Outputs

These are declared with `Export.Name: !Sub "${AWS::StackName}-<key>"` (same convention as `evaluation/template.yaml`'s outputs) so they are addressable both via `aws cloudformation describe-stacks --query "Stacks[0].Outputs"` and via `Fn::ImportValue` if anyone ever wants to import them.

| Output | Description | Consumer |
|---|---|---|
| `KnowledgeBaseId` | The Bedrock KB ID (e.g. `NTVUJCX7AH`). | Pasted into `.env` as `KNOWLEDGE_BASE_ID`. Pasted into `evaluation/samconfig.toml`'s `parameter_overrides` as `KnowledgeBaseId="..."`. |
| `KnowledgeBaseArn` | Full ARN of the KB. | For `iam:PassRole`-style policies; not used by the workshop happy path. |
| `DataSourceId` | The Bedrock DataSource ID. | Used by `aws bedrock-agent start-ingestion-job` if attendees want to re-sync after dropping new files. |
| `SourceBucketName` | Resolved source bucket name. | Used by `aws s3 cp` if attendees want to upload additional data. |
| `SourceBucketArn` | Source bucket ARN. | For diagnostic / IAM debugging. |
| `VectorBucketArn` | S3 Vectors bucket ARN. | For diagnostic / IAM debugging. |
| `IndexArn` | S3 Vectors index ARN. | For diagnostic / IAM debugging. |
| `KnowledgeBaseRoleArn` | ARN of the KB execution role. | For diagnostic / IAM debugging. |
| `Region` | The deploy region. | Reminder for attendees of which region to put in `.env` as `AWS_REGION`. |

### CloudFormation Resources (logical IDs)

```
KnowledgeBaseRole              :: AWS::IAM::Role
SourceBucket                   :: AWS::S3::Bucket
VectorBucket                   :: AWS::S3Vectors::VectorBucket
VectorIndex                    :: AWS::S3Vectors::Index
KnowledgeBase                  :: AWS::Bedrock::KnowledgeBase
KnowledgeBaseDataSource        :: AWS::Bedrock::DataSource
SeedAndIngestFunctionRole      :: AWS::IAM::Role          # only if EnableAutoIngestion=true
SeedAndIngestFunction          :: AWS::Serverless::Function
SeedAndIngestCustomResource    :: AWS::CloudFormation::CustomResource
```

### Resource Shapes (verbatim from the brief; do not re-derive)

```yaml
VectorBucket:
  Type: AWS::S3Vectors::VectorBucket
  Properties:
    VectorBucketName: !If [HasVectorBucketName, !Ref VectorBucketName, !Sub "${AWS::StackName}-vectors-${AWS::AccountId}-${AWS::Region}"]

VectorIndex:
  Type: AWS::S3Vectors::Index
  Properties:
    VectorBucketName: !GetAtt VectorBucket.VectorBucketName    # OR VectorBucketArn
    IndexName: !Ref VectorIndexName
    Dimension: !Ref EmbeddingDimension                          # 1024 for Titan v2
    DistanceMetric: !Ref DistanceMetric                         # COSINE
    DataType: float32

KnowledgeBase:
  Type: AWS::Bedrock::KnowledgeBase
  Properties:
    Name: !Ref KnowledgeBaseName
    RoleArn: !GetAtt KnowledgeBaseRole.Arn
    KnowledgeBaseConfiguration:
      Type: VECTOR
      VectorKnowledgeBaseConfiguration:
        EmbeddingModelArn: !Ref EmbeddingModelArn
    StorageConfiguration:
      Type: S3_VECTORS
      S3VectorsConfiguration:
        IndexArn: !GetAtt VectorIndex.IndexArn

KnowledgeBaseDataSource:
  Type: AWS::Bedrock::DataSource
  Properties:
    Name: !Sub "${KnowledgeBaseName}-data-source"
    KnowledgeBaseId: !Ref KnowledgeBase
    DataSourceConfiguration:
      Type: S3
      S3Configuration:
        BucketArn: !GetAtt SourceBucket.Arn
        InclusionPrefixes:
          - !Ref SourceDataPrefix
    # VectorIngestionConfiguration intentionally omitted to inherit Bedrock's
    # default chunking (FIXED_SIZE, ~300 tokens, 20% overlap).
```

### IAM: KnowledgeBaseRole

Trust policy:
```yaml
AssumeRolePolicyDocument:
  Version: "2012-10-17"
  Statement:
    - Effect: Allow
      Principal:
        Service: bedrock.amazonaws.com
      Action: sts:AssumeRole
```

Inline policy `KnowledgeBaseAccess`:
```yaml
- Sid: InvokeEmbeddingModel
  Effect: Allow
  Action: bedrock:InvokeModel
  Resource: !Ref EmbeddingModelArn

- Sid: ReadSourceBucket
  Effect: Allow
  Action:
    - s3:GetObject
    - s3:ListBucket
  Resource:
    - !GetAtt SourceBucket.Arn
    - !Sub "${SourceBucket.Arn}/*"

- Sid: VectorIndexAccess
  Effect: Allow
  Action:
    - s3vectors:GetVectors
    - s3vectors:PutVectors
    - s3vectors:QueryVectors
    - s3vectors:DeleteVectors
    - s3vectors:GetIndex
    - s3vectors:ListIndexes
  Resource:
    - !GetAtt VectorBucket.VectorBucketArn
    - !GetAtt VectorIndex.IndexArn
```

> **Verify during implementation**: the exact `s3vectors:*` action list against current AWS docs. The list above reflects the brief but the executor must confirm before commit.

### Lambda: seed_and_ingest (CloudFormation custom resource)

Path: `kb_provisioning/lambdas/seed_and_ingest/handler.py`. Runtime `python3.13`. Dependencies: `boto3`, `urllib` (stdlib). The Lambda packaging includes the seed files (`policies.txt`, `data.txt`) copied into the Lambda code directory at `sam build` time via a script-driven prep step in `kb_provisioning/scripts/prepare_lambda_assets.py`, OR sourced from S3 if a build-time upload step is preferred. The roadmap chooses the simpler approach: copy files into `kb_provisioning/lambdas/seed_and_ingest/seed_data/` before `sam build`.

```python
# kb_provisioning/lambdas/seed_and_ingest/handler.py
import json
import os
import urllib.request
from typing import Any
import boto3

SEED_DATA_DIR = os.path.join(os.path.dirname(__file__), "seed_data")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    CloudFormation custom resource that:
      1. On Create: uploads every file in SEED_DATA_DIR to s3://{SourceBucket}/{SourceDataPrefix}.
      2. On Create: calls bedrock-agent:StartIngestionJob for the KB+DataSource.
      3. On Update: no-op unless ResourceProperties changed (compare to OldResourceProperties).
      4. On Delete: empties the source bucket so the bucket can be deleted by CFN.
                    Does NOT call StopIngestionJob — Bedrock terminates it on KB delete.

    Sends a SUCCESS or FAILED response back to the pre-signed CFN URL via urllib.
    Failure to send a response is fatal (CFN times out after 1 hour); always wrap
    the entire body in try/except and emit FAILED on any exception.

    ResourceProperties (from CloudFormation):
    {
        "SourceBucketName": "...",
        "SourceDataPrefix": "data/",
        "KnowledgeBaseId": "...",
        "DataSourceId": "...",
        "Region": "us-east-1"
    }

    Output Data (returned to CloudFormation):
    {
        "IngestionJobId": "...",
        "FilesUploaded": "2"
    }
    """
    ...


def upload_seed_data(s3_client: Any, bucket: str, prefix: str) -> list[str]:
    """Upload every file under SEED_DATA_DIR. Returns the list of S3 keys uploaded."""
    ...


def start_ingestion(bedrock_agent: Any, kb_id: str, ds_id: str) -> str:
    """Call StartIngestionJob and return the ingestion job ID. Does NOT wait for completion."""
    ...


def empty_bucket(s3_client: Any, bucket: str) -> None:
    """Delete every object (and version, if versioned) in the bucket. Used on Delete."""
    ...


def send_cfn_response(
    event: dict[str, Any],
    context: Any,
    status: str,                 # "SUCCESS" | "FAILED"
    data: dict[str, Any] | None = None,
    physical_resource_id: str | None = None,
    reason: str | None = None,
) -> None:
    """PUT the JSON-encoded response body to event['ResponseURL']. Network failures here are fatal."""
    ...
```

### Stack Lifecycle Behavior

| Event | What runs | Effect |
|---|---|---|
| `sam deploy` (first time, `EnableAutoIngestion=true`) | All resources create. Custom resource fires on `Create`. | KB exists; source bucket has 2 files; ingestion job has been **started** (likely still `IN_PROGRESS` when stack returns). |
| `sam deploy` (no parameter changes) | CFN no-op for the KB and DataSource. Custom resource sees `Update` with identical properties → returns `SUCCESS` without re-uploading or re-ingesting. | No effect. |
| `sam deploy` (changing `EmbeddingModelArn` or `EmbeddingDimension`) | CFN replaces the index and KB. | Manual cleanup of the old vector data may be needed; document as "prefer `sam delete` then `sam deploy`". |
| `sam delete` | Custom resource fires on `Delete` and empties the source bucket. CFN then deletes bucket, KB, DataSource, index, vector bucket, role. | Stack returns to zero billable resources. |

### "Single Command" Surface

> **Prerequisite — AWS credentials must already be configured locally.** Before any of the commands below, attendees must have run `aws configure` (or `aws sso login`) on their own machine and verified with `aws sts get-caller-identity --region us-east-1` that a valid `Account` + `Arn` is returned. This stack uses the standard AWS credential provider chain — it does **not** accept access keys as parameters, does **not** read `AWS_ACCESS_KEY_ID` from `.env`, and the workshop facilitator does **not** distribute credentials. Attendees who have not set this up before the workshop will be blocked at `sam deploy`.

Workshop-attendee commands from a clean checkout, both options documented:

**Option 1 — fully automated (target UX, requires custom resource Lambda to work):**
```bash
cd kb_provisioning
sam build
sam deploy --config-file samconfig.toml
# (samconfig provides a NotificationEmail-style default for any required params)
```
After `sam deploy` returns, copy the `KnowledgeBaseId` output from the console output (or via `aws cloudformation describe-stacks`) into `.env` and `evaluation/samconfig.toml`.

**Option 2 — fallback if the custom resource hits IAM friction:**
```bash
cd kb_provisioning
sam build
sam deploy --config-file samconfig.toml --parameter-overrides EnableAutoIngestion=false
python scripts/seed_and_ingest.py \
    --stack-name <stack-name> \
    --region <region>
```

## Behavior Guarantees

1. **Idempotent re-deploy**: `sam deploy` with unchanged parameters does not start a new ingestion job and does not re-upload seed files. Verified by the custom resource's `RequestType == "Update"` branch comparing `ResourceProperties` to `OldResourceProperties` — only fire if at least one tracked property changed.
2. **Output stability**: `KnowledgeBaseId` does not change across no-op re-deploys. Stack-export name `${AWS::StackName}-KnowledgeBaseId` is stable.
3. **Region locality**: every resource is created in the deploy region. The seed Lambda's `boto3.client(...)` calls all pass `region_name=os.environ["AWS_REGION"]` (set by Lambda runtime to the function's region); we never cross regions.
4. **Default chunking inherited**: `AWS::Bedrock::DataSource.VectorIngestionConfiguration` is omitted, so Bedrock applies its default (FIXED_SIZE, ~300 tokens, ~20% overlap). This is intentional per the user brief.
5. **Bucket cleanup on delete**: the source S3 bucket is emptied by the custom resource's `Delete` handler before CFN tries to delete the bucket. Without this, `sam delete` would fail with `BucketNotEmpty`. The vector bucket's deletability is handled by CFN; if S3 Vectors requires emptying first, the seed Lambda must be extended (verify during implementation).
6. **No silent failure on missing model access**: if Titan v2 is not enabled in the account, `StartIngestionJob` will fail. The custom resource captures the Bedrock error message verbatim into the CFN `Reason`, so the stack creation fails with a readable error rather than a successful deploy + broken KB.
7. **No cross-stack coupling**: this stack does not import or read anything from `evaluation/`'s stack outputs, and `evaluation/`'s stack does not depend on this one. The cross-stack data path is human-mediated copy/paste.

## Error Handling Contract

| Error Condition | Behavior | User Impact |
|---|---|---|
| Titan v2 model access not granted in the account | `bedrock-agent:StartIngestionJob` returns `AccessDeniedException`. Custom resource sends `FAILED` with the boto3 error message in `Reason`. | Stack rolls back (unless `disable_rollback = true` in samconfig). Attendee sees the actionable error in the CFN events tab and grants model access via Bedrock console → Model access. |
| S3 Vectors not GA in the chosen region | `AWS::S3Vectors::VectorBucket` create fails with `InvalidLocationConstraint` or service-not-available. | Stack rollback. Attendee re-deploys with `region = "us-east-1"` (the documented default). |
| Source / vector bucket name collision (already taken) | `AWS::S3::Bucket` create fails with `BucketAlreadyExists`. | Stack rollback. Attendee overrides `SourceBucketName` / `VectorBucketName` parameter and redeploys. |
| Embedding dimension mismatch (e.g. attendee sets `EmbeddingDimension=512` but uses Titan v2) | Index creates fine; KB create or first ingestion fails when Bedrock writes vectors with mismatched dimension. | Stack rollback at KB or ingestion stage. Documented in roadmap risks. |
| Region mismatch between `samconfig.toml` `region` and `EmbeddingModelArn`'s region | `bedrock:InvokeModel` returns `ValidationException`. | Ingestion fails. Custom resource emits `FAILED`. Document the parameter-override pattern. |
| Custom resource Lambda times out (>15 min) | CFN waits the full 1-hour custom-resource timeout. | Stack stuck; attendee aborts via `aws cloudformation cancel-update-stack` (Update) or `sam delete --no-prompts` (Create). The `StartIngestionJob` we make is async (we don't wait for completion), so a 15-min timeout should be ample. |
| Concurrent re-deploy (`sam deploy` while previous deploy still in progress) | CFN returns `ResourceInUseException` immediately. | Attendee waits for the in-flight stack op to finish. |
| Attendee runs `sam delete` while an ingestion job is still in progress | KB delete cancels the ingestion job. Custom resource `Delete` empties the bucket regardless of job state. | Clean teardown. |

## Dependencies

### Internal (other parts of this repo)
- `src/data/policies.txt`, `src/data/data.txt` — read at `sam build` time by `kb_provisioning/scripts/prepare_lambda_assets.py` and copied into `kb_provisioning/lambdas/seed_and_ingest/seed_data/` for packaging.
- No runtime dependency on `src/`. Provisioning does not import any project Python module.

### External (AWS services)
- `cloudformation` — orchestration.
- `bedrock-agent` — `CreateKnowledgeBase`, `CreateDataSource`, `StartIngestionJob`.
- `bedrock` — `InvokeModel` (used by the KB at ingestion time, via the role we create).
- `s3` — source bucket + object ops.
- `s3vectors` — vector bucket + index.
- `iam` — KB role + Lambda role.
- `lambda` + `cloudformation custom resource` — seed-and-ingest.

### External (Python packages)
- Lambda runtime: `boto3` (built into AWS Lambda Python 3.13 runtime).
- Local seed-and-ingest fallback script (`kb_provisioning/scripts/seed_and_ingest.py`): `boto3` (already in the project's `requirements.txt` at version `1.40.26`).
- Tests: `pytest`, `pytest-mock`, `pytest-cov` (already in `evaluation/requirements-dev.txt`; reuse the same file or create `kb_provisioning/requirements-dev.txt` with identical contents).

### External (CLI)
- AWS SAM CLI (attendees install separately; same precondition as `evaluation/`).
- AWS CLI v2 (for `aws cloudformation describe-stacks` to read outputs).

## Integration Points

### Producer side (this stack outputs)
- Stack output `KnowledgeBaseId` ↔ `.env` key `KNOWLEDGE_BASE_ID` ↔ `os.environ.get("KNOWLEDGE_BASE_ID", "")` in `src/utils/rag_utils.py:10` (passed to `AmazonKnowledgeBasesRetriever`).
- Stack output `KnowledgeBaseId` ↔ `evaluation/samconfig.toml`'s `parameter_overrides` key `KnowledgeBaseId` ↔ `evaluation/template.yaml` Parameter `KnowledgeBaseId` ↔ `Globals.Function.Environment.Variables.KNOWLEDGE_BASE_ID` ↔ `KbSyncCompletionRule`'s `EventPattern.detail.knowledgeBaseId` filter.
- Stack output `Region` ↔ `.env` key `AWS_REGION` ↔ `src/utils/rag_utils.py:12`'s `os.environ.get("AWS_REGION", "us-east-1")`.

### Consumer side (this stack reads)
- `src/data/*.txt` — read once at packaging time (NOT at deploy time and NOT at runtime). The Lambda code dir contains a snapshot.

### Sibling-stack orthogonality
- This stack and `evaluation/` share no CloudFormation resources, no IAM roles, no S3 buckets, no Lambda functions. The only shared concept is the `KnowledgeBaseId` value, which is a string copied by the human between two `samconfig.toml` files and one `.env` file.
- Both stacks must be deployed to the same region for the `evaluation/` `KbSyncCompletionRule` to receive sync events from this KB. Region mismatch is a silent failure (rule never matches) — call it out in the README.
