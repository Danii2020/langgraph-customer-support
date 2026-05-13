# KB Provisioning — Workshop Quick Start

This SAM stack provisions a fully functional Amazon Bedrock Knowledge Base
in a single `sam deploy`. It is the first thing workshop attendees deploy.

## Prerequisites

Before running `sam deploy`, verify every item in this checklist.

### 1. AWS CLI v2

```bash
aws --version   # must show aws-cli/2.x
```

Install:

- **macOS**: `brew install awscli`
- **Linux** (x86_64):
  ```bash
  curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
  unzip awscliv2.zip && sudo ./aws/install
  ```
- **Windows** (PowerShell):
  ```powershell
  msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi
  ```

Full reference:
[AWS CLI v2 install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).

### 2. SAM CLI >= 1.100

```bash
sam --version   # must show 1.100 or higher
```

`AWS::S3Vectors::*` resource support requires SAM CLI 1.100+.

Install:

- **macOS**: `brew install aws-sam-cli`
- **Linux** (x86_64):
  ```bash
  curl -L "https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip" -o "aws-sam-cli.zip"
  unzip aws-sam-cli.zip -d sam-installation && sudo ./sam-installation/install
  ```
- **Windows**: download and run the 64-bit MSI:
  [AWS_SAM_CLI_64_PY3.msi](https://github.com/aws/aws-sam-cli/releases/latest/download/AWS_SAM_CLI_64_PY3.msi).
  Open a new shell after install so `sam` is on `PATH`.

Full reference:
[SAM CLI install guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).

### 3. AWS credentials configured

```bash
aws sts get-caller-identity --region us-east-1
# Must return a valid Account and Arn.
```

If the above fails, configure credentials first:

```bash
aws configure           # long-lived access key + secret
# OR
aws sso login           # IAM Identity Center / SSO
```

This stack uses the standard AWS credential provider chain. It does **not**
accept `AWS_ACCESS_KEY_ID` as a CloudFormation parameter and does **not** read
it from `.env`. Attendees who skip this step will be blocked at `sam deploy`.

For personal AWS accounts, the IAM user created via `aws configure` typically
has `AdministratorAccess` already. For corporate accounts with restrictive SCPs,
request `AdministratorAccess` or the specific permissions listed in
`intent.md`'s "Attendee Setup Prerequisites" section.

### 4. Titan v2 model access granted

In the AWS Console:
**Amazon Bedrock -> Model access -> Manage model access**
-> enable **Amazon Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`)
in `us-east-1` (or your chosen region).

This cannot be done from CloudFormation. If model access is not granted, the
stack will reach `CREATE_FAILED` with an `AccessDeniedException` from Bedrock
during the ingestion step — the error message in the CFN events tab will be
actionable.

## Deploy

```bash
# From the repository root:

# Step 0: copy the workshop data files into the Lambda package
python kb_provisioning/scripts/prepare_lambda_assets.py

# Step 1: change into the provisioning directory
cd kb_provisioning

# Step 2: build
sam build

# Step 3: deploy (parameters are pre-filled in samconfig.toml)
sam deploy --config-file samconfig.toml
```

The default `samconfig.toml` targets `us-east-1` and uses auto-generated
globally-unique bucket names. No edits required for the workshop happy path.

The deploy takes approximately 3–7 minutes (dominated by Bedrock KB creation
and ingestion startup).

## Copy the output into your environment

After `sam deploy` returns:

```bash
aws cloudformation describe-stacks \
  --stack-name kb-provisioning \
  --region us-east-1 \
  --query "Stacks[0].Outputs"
```

1. Copy `KnowledgeBaseId` into `.env` in the repo root:
   ```
   KNOWLEDGE_BASE_ID=<KnowledgeBaseId value>
   AWS_REGION=us-east-1
   ```

2. Copy `KnowledgeBaseId` into `evaluation/samconfig.toml`'s `parameter_overrides`:
   ```
   KnowledgeBaseId="<same value>"
   ```

## Verify the ingestion job

The ingestion job is started asynchronously. Check its status:

```bash
# Get DataSourceId from outputs, then:
aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id <KnowledgeBaseId> \
  --data-source-id <DataSourceId> \
  --region us-east-1
```

The job typically transitions to `COMPLETE` within 1–3 minutes of stack creation.

## Teardown

```bash
cd kb_provisioning
sam delete --stack-name kb-provisioning --region us-east-1
```

The custom resource Lambda empties the source S3 bucket before CloudFormation
attempts to delete it, so teardown completes without manual intervention.

## Fallback: manual seed + ingest

If the custom resource Lambda fails (e.g. IAM friction in a restricted account),
re-deploy without auto-ingestion and run the seed script manually:

```bash
# Re-deploy with auto-ingestion disabled:
sam deploy --config-file samconfig.toml \
  --parameter-overrides EnableAutoIngestion=false

# Then seed and start ingestion manually:
python scripts/seed_and_ingest.py \
  --stack-name kb-provisioning \
  --region us-east-1
```

## Re-syncing after adding new documents

Drop files into `src/data/` and run:

```bash
python kb_provisioning/scripts/seed_and_ingest.py \
  --stack-name kb-provisioning \
  --region us-east-1 \
  --data-dir src/data/
```

No re-deploy required.

## Common errors

| Error | Likely cause | Fix |
|---|---|---|
| `AccessDeniedException` during ingestion | Titan v2 model access not granted | Bedrock console -> Model access -> enable Titan v2 |
| `BucketAlreadyExists` | Another stack used the same name | Override `SourceBucketName` or `VectorBucketName` parameter |
| `InvalidLocationConstraint` | S3 Vectors not available in chosen region | Change `region` in `samconfig.toml` to `us-east-1` |
| `ValidationException` during KB create | Region mismatch between `region` and `EmbeddingModelArn` | Override `EmbeddingModelArn` to match your region |
| Stack stuck for >15 min | Custom resource timed out | `sam delete --no-prompts`; check CloudWatch logs for the `seed-and-ingest` Lambda |

## Region alignment

Both `kb_provisioning/samconfig.toml` and `evaluation/samconfig.toml` default
to `us-east-1`. Deploy both stacks to the **same region**. A mismatch causes
the evaluation pipeline's `KbSyncCompletionRule` EventBridge rule to silently
never fire — the eval pipeline will look idle even after successful ingestion.
