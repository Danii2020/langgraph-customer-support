# Intent: KB Provisioning

## Problem Statement
Workshop attendees (45–60 minute time budget) currently have to click through the AWS Console to create an Amazon Bedrock Knowledge Base, an S3 bucket for source documents, an S3 Vectors vector bucket and index, an IAM role for the KB, then upload the source data files (`src/data/policies.txt`, `src/data/data.txt`) and trigger the first ingestion job. Each console click is a chance to misconfigure the KB (wrong region, wrong embedding model, wrong dimension, missing `s3vectors:*` permissions), and the cumulative friction either eats the entire workshop slot or leaves attendees with a broken KB that the existing LangGraph app (`main.py`) and the `evaluation/` SAM pipeline cannot consume.

The goal is to replace all of that with a single `sam deploy` invocation that produces a working `KnowledgeBaseId` ready to drop into `.env` (consumed by `src/utils/rag_utils.py` and `src/agents/bedrock.py`) and into `evaluation/samconfig.toml`'s `parameter_overrides` (consumed by the eval pipeline's `KnowledgeBaseId` parameter).

## Goals
1. Provision a fully functional Amazon Bedrock Knowledge Base (Titan Text Embeddings V2 + S3 Vectors store) in a single SAM stack at `kb_provisioning/`.
2. Auto-seed the KB's source S3 bucket with `src/data/policies.txt` and `src/data/data.txt` and start the initial ingestion job during stack creation, so the KB is queryable immediately after `sam deploy` returns.
3. Surface a `KnowledgeBaseId` stack output that maps 1:1 to the `KNOWLEDGE_BASE_ID` env var consumed by `src/utils/rag_utils.py`, `src/agents/bedrock.py`, and to the `KnowledgeBaseId` parameter in `evaluation/samconfig.toml`.
4. Mirror the conventions of the existing `evaluation/` SAM application (directory layout, `template.yaml` + `samconfig.toml` pattern, Lambda + tests pattern, `Globals.Function` env-var pattern, `parameter_overrides` string format) so the two stacks feel like siblings.
5. Keep this stack independent of the `evaluation/` stack — separate `template.yaml`, separate `samconfig.toml`, separate stack name, separate lifecycle (one-shot at workshop start vs. event-driven on each KB sync).

## Success Criteria
- [ ] From a clean checkout, an attendee runs at most two commands (`sam build && sam deploy --config-file samconfig.toml`) from `kb_provisioning/` and gets a working KB.
- [ ] `sam deploy` completes (CREATE_COMPLETE) in under ~10 minutes on a typical workshop AWS account.
- [ ] After deploy, `aws bedrock-agent get-knowledge-base --knowledge-base-id <output>` returns `status: ACTIVE`.
- [ ] After deploy, `aws bedrock-agent list-ingestion-jobs --knowledge-base-id <output> --data-source-id <output>` shows at least one ingestion job in `COMPLETE` state.
- [ ] Pasting the `KnowledgeBaseId` output into `.env` (as `KNOWLEDGE_BASE_ID=...`) and running `python main.py` exercises the retriever tool against the new KB without code changes to `src/`.
- [ ] Pasting the same `KnowledgeBaseId` into `evaluation/samconfig.toml`'s `parameter_overrides` and running `sam deploy --config-file evaluation/samconfig.toml` produces a working eval pipeline whose `KbSyncCompletionRule` matches future syncs of this KB.
- [ ] All custom-resource Lambdas (seed-and-ingest) have unit tests under `kb_provisioning/tests/` following the import-by-absolute-path pattern in `evaluation/tests/`.
- [ ] `sam delete --stack-name <stack>` removes every resource the stack created (KB, DataSource, S3 source bucket after emptying it, S3 Vectors bucket+index, IAM role) without leaving orphaned billable resources.

## Non-Goals
- Modifying `src/` or `main.py`. The app continues to read `KNOWLEDGE_BASE_ID` and `AWS_REGION` from `.env`; provisioning does not touch the LangGraph runtime.
- Modifying `evaluation/template.yaml`, `evaluation/samconfig.toml`, or any `evaluation/` Lambda. The eval stack continues to take `KnowledgeBaseId` as an input parameter; provisioning produces the value but does not orchestrate the eval deploy.
- Automating the cross-stack handoff (e.g., importing `kb_provisioning`'s output into `evaluation/`'s parameters). Attendees copy/paste once. CloudFormation cross-stack imports are intentionally avoided to keep the two stacks independently deployable and destroyable.
- Granting Bedrock model access in the AWS account. If Titan v2 access is not enabled, the stack will fail at ingestion time; we document this as a precondition rather than handling it.
- Multi-region replication, KMS-managed customer keys, VPC endpoints, or production-grade hardening. This is a workshop stack.
- Supporting embedding models other than Titan Text Embeddings V2 in the workshop happy path. Other models are technically reachable via the `EmbeddingModelArn` parameter but only Titan v2 is on the supported matrix for the workshop.
- Making the source documents configurable beyond a directory and an inclusion prefix. Attendees use the bundled `src/data/*` files; bring-your-own-data is a stretch goal.

## Attendee Setup Prerequisites

Attendees are responsible for having a working AWS CLI on their own machine before the workshop starts. The provisioning stack assumes — and the workshop facilitator must communicate — the following:

- **AWS credentials configured locally**: `aws configure` (long-lived access key + secret) or `aws sso login` (IAM Identity Center) is already done. SAM CLI uses the standard AWS credential provider chain; this stack does not accept credentials as parameters and never reads `AWS_ACCESS_KEY_ID` from `.env`.
- **Pre-flight check**: attendees run `aws sts get-caller-identity --region us-east-1` and confirm a valid `Account` / `Arn` response before invoking `sam deploy`. A failure here blocks the entire workshop slot.
- **AWS CLI v2 + SAM CLI installed**: SAM CLI v1.100+ is required for `AWS::S3Vectors::*` resource support. Document the install commands in the README (`brew install aws-sam-cli` or equivalent).
- **IAM permissions on the attendee's principal**: the principal that runs `sam deploy` must be able to create everything in this stack. At minimum:
  - `cloudformation:*` on the stack
  - `iam:CreateRole`, `iam:PutRolePolicy`, `iam:PassRole`, `iam:DeleteRole`, `iam:DeleteRolePolicy`, `iam:GetRole` (named IAM roles, hence `CAPABILITY_NAMED_IAM`)
  - `s3:CreateBucket`, `s3:PutBucketNotification`, `s3:DeleteBucket`, `s3:PutBucketPolicy`
  - `s3vectors:CreateVectorBucket`, `s3vectors:CreateIndex`, `s3vectors:DeleteVectorBucket`, `s3vectors:DeleteIndex`, `s3vectors:GetVectorBucket`, `s3vectors:GetIndex`
  - `bedrock:CreateKnowledgeBase`, `bedrock:CreateDataSource`, `bedrock:DeleteKnowledgeBase`, `bedrock:DeleteDataSource`, `bedrock:StartIngestionJob`, `bedrock:GetKnowledgeBase`, `bedrock:GetDataSource`
  - `lambda:CreateFunction`, `lambda:DeleteFunction`, `lambda:InvokeFunction`, `lambda:GetFunction` (for the seed-and-ingest custom resource)
  - For attendees on a corporate AWS account with restrictive SCPs, `AdministratorAccess` is the path of least resistance; for personal accounts, the IAM user created via `aws configure` typically has it already.
- **Bedrock model access**: separate from credentials. Attendees must enable Titan Text Embeddings V2 (`amazon.titan-embed-text-v2:0`) in the AWS Console under **Bedrock → Model access → Manage model access** in the same region as the stack (`us-east-1` by default). This cannot be granted from CloudFormation; surface it as a documented precondition with a screenshot in the workshop README.

This stack is BYO-account: each attendee deploys into their own AWS account with their own credentials. Shared workshop accounts are not supported in the happy path because the bucket name patterns (`${AWS::StackName}-source-${AWS::AccountId}-${AWS::Region}`) would collide if multiple attendees use the same account+stack-name pair.

## Constraints
- **Tooling parity**: AWS SAM CLI + CloudFormation. No Terraform, no CDK. Match the existing `evaluation/` workflow.
- **Python runtime**: Lambda functions (custom resource) must use `python3.13` to match `Globals.Function.Runtime` in `evaluation/template.yaml` and the project's `requires-python = ">=3.13"` in `pyproject.toml`.
- **Lambda dependencies**: only `boto3` (already in the Lambda runtime). The custom resource Lambda is not allowed to require pip-installed packages — `evaluation/`'s Lambdas follow the same rule.
- **Region alignment**: the workshop must use a single region for all three components (LangGraph app's hardcoded `us-east-2`, eval pipeline's `us-east-1`, this stack). The default is `us-east-1` because S3 Vectors, Bedrock KB, and Titan v2 are all GA there as of 2026-05-09. Attendees who pick a different region must (a) update `samconfig.toml`'s `region`, (b) edit `region_name="us-east-2"` in `src/agents/bedrock.py`, (c) edit `evaluation/samconfig.toml`'s `region` and the hardcoded `region_name="us-east-1"` in the three eval Lambda handlers.
- **Globally-unique resource names**: bucket names must be globally unique across S3. Use `${AWS::StackName}-source-${AWS::AccountId}-${AWS::Region}` and `${AWS::StackName}-vectors-${AWS::AccountId}-${AWS::Region}` patterns to minimize collision risk.
- **Idempotency**: re-running `sam deploy` against an existing stack must be a no-op for the KB / DataSource / vector index. The seed-and-ingest custom resource must only fire on `Create` of the resource (not on `Update` unless inputs changed) to avoid runaway ingestion jobs.
- **Bedrock model access**: Titan v2 (`amazon.titan-embed-text-v2:0`) must be enabled in the target account/region before deploy. We cannot grant this from CloudFormation; document it as a precondition.
- **Capabilities flag**: stack creates a named IAM role, so `samconfig.toml` must include `capabilities = "CAPABILITY_IAM CAPABILITY_NAMED_IAM"` (same as `evaluation/samconfig.toml`).

## Prior Art
- `evaluation/template.yaml` — reference for SAM resource conventions (Parameters, Globals, named IAM roles, Outputs with `Export.Name`, `!Sub` substitution patterns).
- `evaluation/samconfig.toml` — reference for `parameter_overrides` string format, `s3_prefix`, `disable_rollback`, and the `[default.global.parameters]` region pin.
- `evaluation/lambdas/start_eval_job/handler.py` — reference for boto3-only Lambda style (top-of-file `boto3.client()` is avoided in favor of in-handler clients to make tests easier).
- `evaluation/tests/test_start_eval_job.py` — reference for the `importlib.util.spec_from_file_location` test loader pattern that lets multiple `handler.py` files coexist as test modules.
- `evaluation/scripts/setup_s3.py` — reference for boto3 upload pattern; the seed step inside the custom resource Lambda is morally identical (download from a build-time location, upload to the source bucket).
- `src/utils/rag_utils.py` — the consumer of `KNOWLEDGE_BASE_ID`; defines the contract the stack output must satisfy.
- `src/agents/bedrock.py` — confirms the embedding-model-vs-runtime split (Titan v2 is on the `bedrock` service for KB, while the LangGraph app talks to `bedrock-runtime` for chat completions).
- `evaluation/template.yaml`'s `KbSyncCompletionRule` — confirms the EventBridge `aws.bedrock` "Bedrock Knowledge Base Data Source Sync" event is what gets emitted on ingestion completion; if the KB is created in a different region than the eval pipeline, that rule will never fire.
- AWS CloudFormation reference for `AWS::S3Vectors::VectorBucket`, `AWS::S3Vectors::Index`, `AWS::Bedrock::KnowledgeBase`, `AWS::Bedrock::DataSource` (resource shapes provided in the task brief; do not re-derive).
