## LangGraph Customer Support Workshop

This repository ships three projects that work together:

1. **LangGraph email-support app** (`src/`, `main.py`) — runs locally, reads Gmail, replies via Bedrock + Knowledge Bases.
2. **KB Provisioning stack** (`kb_provisioning/`) — one-command SAM deploy that creates an Amazon Bedrock Knowledge Base (S3 Vectors + Titan v2), seeds it with workshop data, and starts the initial ingestion.
3. **RAG Evaluation pipeline** (`evaluation/`) — SAM stack with Lambdas + Step Functions + EventBridge + SNS that auto-evaluates the Knowledge Base every time it is re-synced or the prompt template changes.

This README walks workshop attendees through everything needed to run **stacks #2 and #3** end-to-end, starting from a brand-new AWS account.

---

## Workshop Quick Start

The happy path is:

1. Install prerequisites (AWS CLI, SAM CLI, Python 3.13).                            *(§1.1–1.6)*
2. Create an IAM user with `AdministratorAccess` and configure credentials locally.  *(§1.2–1.4)*
3. Enable Bedrock model access (Titan v2 + the generator/evaluator models).          *(§1.7)*
4. Deploy the **KB Provisioning** stack and copy `KnowledgeBaseId` into the eval config. *(§2 → `make kb`)*
5. Create the Bedrock-managed eval prompt and copy `PromptResourceId` into the eval config. *(§3.1 → `make prompt`)*
6. (Optional) Stage assets for the manual Bedrock-eval workshop demo.                *(§3.3 → `make manual-assets`)*
7. Deploy the **Evaluation Pipeline** stack and confirm the SNS email subscription.  *(§3.4–3.5 → `make eval`)*
8. Re-trigger the eval pipeline by publishing a new prompt version.                  *(§4 → `make trigger`)*
9. Tear both stacks down at the end of the workshop.                                 *(§5 → `make teardown`)*

Each step is detailed below.

### Fast path with `make`

A `Makefile` at the repo root wraps every multi-step recipe in this README into a single command. Use it after you finish the first-time prerequisites (steps 1.1–1.8 below). Run `make` (or `make help`) to list available targets:

```bash
make install         # pip install dev/test deps for both stacks
make kb              # prepare + build + deploy the KB provisioning stack         (§2)
make prompt          # create / update the Bedrock-managed eval prompt            (§3.1)
make manual-assets   # provision the workshop bucket for the manual-eval demo     (§3.3, optional)
make eval            # prepare + build + deploy the evaluation pipeline stack     (§3.4)
make trigger         # publish a new prompt version -> re-fires the eval pipeline (§4)
make test            # run pytest across both stacks                              (§7)
make teardown        # delete both stacks in the safe order (eval first, then KB) (§5)
make teardown-eval   # delete only the evaluation stack
make teardown-kb     # delete only the KB provisioning stack
```

`make` is a convenience layer, not a replacement for the README — every target maps 1:1 to the explicit `python` / `sam` commands documented in the corresponding section. Override defaults at the CLI (e.g. `make eval REGION=us-west-2 EVAL_STACK=my-eval-pipeline`).

> Between `make kb` and `make eval`, you still need to paste the `KnowledgeBaseId` from the KB stack output into `evaluation/samconfig.toml`. Between `make prompt` and `make eval`, you still need to paste the `PromptResourceId` the script prints into the same file. Those copy/paste steps are intentional — both IDs are generated at deploy time.

---

## 1. Prerequisites

### 1.1 AWS account

You need an AWS account where you can create IAM users and enable Bedrock model access. A personal sandbox account is ideal. Corporate accounts with restrictive SCPs may block parts of the deploy — request `AdministratorAccess` if so.

### 1.2 Create an IAM user with admin permissions

For workshop simplicity we grant **`AdministratorAccess`**. Do **not** use the root user.

In the AWS Console:

1. **IAM → Users → Create user**
2. User name: `workshop-admin` (any name is fine).
3. **Do not** check "Provide user access to the AWS Management Console" unless you also want console access.
4. **Next → Attach policies directly → search and check `AdministratorAccess` → Next → Create user**.
5. Open the new user → **Security credentials** tab → **Create access key**.
6. Choose **Command Line Interface (CLI)** → confirm the warning → **Create access key**.
7. **Copy or download the Access Key ID and Secret Access Key now** — the secret is only shown once.

### 1.3 Install AWS CLI v2

```bash
# macOS
brew install awscli

# Linux / Windows: follow https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

aws --version   # must show aws-cli/2.x or higher
```

### 1.4 Configure AWS credentials locally

Run `aws configure` and paste in the access key and secret you copied in step 1.2:

```bash
aws configure
# AWS Access Key ID [None]:     <paste Access Key ID>
# AWS Secret Access Key [None]: <paste Secret Access Key>
# Default region name [None]:   us-east-1
# Default output format [None]: json
```

Verify the credentials work:

```bash
aws sts get-caller-identity --region us-east-1
# Should return your Account, UserId, and the workshop-admin Arn.
```

Both SAM stacks use the standard AWS credential provider chain. They do **not** read `AWS_ACCESS_KEY_ID` from `.env` and do **not** accept access keys as CloudFormation parameters — `aws configure` is required.

### 1.5 Install SAM CLI (>= 1.100)

SAM CLI 1.100+ is required for the `AWS::S3Vectors::*` resources used by the KB stack.

```bash
# macOS
brew install aws-sam-cli

# Linux / Windows: follow https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html

sam --version   # must show 1.100 or higher
```

### 1.6 Install Python 3.13 and a virtualenv

The seed/upload helper scripts run locally. Python 3.13+ is required.

```bash
# macOS
brew install python@3.13

python3 --version   # must show 3.13.x

# Create and activate a venv at the repo root
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

Install dev/test dependencies for both stacks.

**Shortcut:** `make install`.

```bash
pip install -r kb_provisioning/requirements-dev.txt
pip install -r evaluation/requirements-dev.txt
```

### 1.7 Enable Bedrock model access

Model access is granted **per-account, per-region** and **cannot** be set from CloudFormation. Do this once in the console, in the same region you will deploy the stacks (default: `us-east-1`).

AWS Console → **Amazon Bedrock → Model access → Manage model access** → enable:

| Model | Model ID | Used by |
|---|---|---|
| Amazon Titan Text Embeddings V2 | `amazon.titan-embed-text-v2:0` | KB ingestion (embeddings) |
| Amazon Nova Pro | `amazon.nova-pro-v1:0` | Eval generator + evaluator (default) |

If you plan to use a different generator/evaluator model, enable that model instead and override `BedrockModelId` / `EvaluatorModelId` in `evaluation/samconfig.toml`.

> **Inference-profile-only models.** Newer models (e.g. `amazon.nova-2-lite-v1:0`, `amazon.nova-2-pro-v1:0`) **cannot** be invoked via the bare foundation-model ID — Bedrock returns `Invocation … with on-demand throughput isn't supported`. Use the system-defined cross-region inference profile ID instead (e.g. `us.amazon.nova-2-lite-v1:0`). The stack's `EvalServiceRole` is already configured to invoke inference profiles + their underlying foundation models in any region, so no template changes are needed.

Without model access, the KB stack will reach `CREATE_FAILED` with an `AccessDeniedException` during ingestion, and the eval pipeline will fail at `StartRetrieveAndGenerateJob`.

### 1.8 Clone this repository

```bash
git clone <this-repo-url>
cd langgraph-gmail
```

---

## 2. Deploy the KB Provisioning stack

This single deploy creates the source S3 bucket, the S3 Vectors bucket + index, the Bedrock Knowledge Base, the data source, and a custom-resource Lambda that uploads `src/data/*.txt` and starts the initial ingestion job.

**Shortcut:** `make kb` runs all three commands below in order.

```bash
# Step 0: copy seed data into the Lambda package (run before every sam build)
python kb_provisioning/scripts/prepare_lambda_assets.py

# Step 1: build the SAM app
cd kb_provisioning
sam build

# Step 2: deploy (parameters are pre-filled in samconfig.toml; defaults are us-east-1)
sam deploy --config-file samconfig.toml
```

The deploy takes ~3–7 minutes. When it returns, capture the stack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name kb-provisioning \
  --region us-east-1 \
  --query "Stacks[0].Outputs"
```

You will see `KnowledgeBaseId`, `DataSourceId`, `SourceBucketName`, and `VectorBucketName`. **Copy the `KnowledgeBaseId` value** — the eval pipeline needs it.

### Verify the ingestion job

```bash
aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id <KnowledgeBaseId> \
  --data-source-id <DataSourceId> \
  --region us-east-1
```

The job should transition to `COMPLETE` within 1–3 minutes.

### Re-seed manually (fallback)

If the auto-ingestion custom resource fails (rare; usually IAM friction in a restricted account), re-deploy without it and seed manually:

```bash
sam deploy --config-file samconfig.toml --parameter-overrides EnableAutoIngestion=false

python kb_provisioning/scripts/seed_and_ingest.py \
  --stack-name kb-provisioning \
  --region us-east-1
```

To re-sync after adding new files to `src/data/`:

```bash
python kb_provisioning/scripts/seed_and_ingest.py \
  --stack-name kb-provisioning \
  --region us-east-1 \
  --data-dir src/data/
```

---

## 3. Deploy the Evaluation pipeline

### 3.1 Create the Bedrock-managed prompt

The KB prompt now lives in Bedrock Prompt Management (not in S3), so eval runs can be triggered by publishing a new prompt version from the console. Create the prompt resource once before deploying the eval stack:

**Shortcut:** `make prompt`.

```bash
python evaluation/scripts/create_eval_prompt.py
```

The script reads `evaluation/prompts/kb_prompt_template.txt`, rewrites `$search_results$` / `$query$` to Prompt Management's `{{search_results}}` / `{{query}}` syntax, creates a prompt named `rag-eval-kb-prompt`, and publishes version 1. **It prints the prompt ID at the end — copy it; the next step needs it.**

Re-running the script is idempotent: if the prompt already exists, its DRAFT is updated with the current template text and a new version is published (this is exactly how `make trigger` re-fires the pipeline later).

### 3.2 Wire the KB ID and prompt ID into the eval config

Edit `evaluation/samconfig.toml` and set `KnowledgeBaseId` (from step 2) and `PromptResourceId` (from step 3.1) in `parameter_overrides`:

```toml
parameter_overrides = "KnowledgeBaseId=\"<paste KnowledgeBaseId here>\" PromptResourceId=\"<paste prompt id here>\" BedrockModelId=\"amazon.nova-pro-v1:0\" EvaluatorModelId=\"amazon.nova-pro-v1:0\" NotificationEmail=\"<your-email>\" MaxPollingIterations=\"40\""
```

Also set `NotificationEmail` to an inbox you can check — SNS will email PASS/FAIL verdicts there.

### 3.3 (Workshop demo) Stage assets for a manual Bedrock evaluation job

Before deploying the automated pipeline, the workshop walks through creating a Bedrock evaluation job by hand from the console. Run the helper below to provision a dedicated workshop bucket (`workshop-rag-eval-<account-id>-<region>`), upload the evaluation dataset, prompt template, and thresholds file, and pre-create a `results/` folder for the eval job's output:

**Shortcut:** `make manual-assets`.

```bash
python evaluation/scripts/setup_manual_eval_assets.py
```

The script prints the three S3 URIs to plug into the Bedrock console (dataset, prompt template, output prefix). It is idempotent and independent of the SAM stack — the eval pipeline below still provisions and seeds its own `EvalBucket`/`ResultsBucket`. Skip this step if you are not running the manual-eval portion of the workshop.

### 3.4 Build and deploy

**Shortcut:** `make eval` runs all three commands below in order.

```bash
# Step 0: copy seed files into the Lambda package (dataset + thresholds)
python evaluation/scripts/prepare_lambda_assets.py

# Step 1: build
cd evaluation
sam build

# Step 2: deploy (uses evaluation/samconfig.toml)
sam deploy --config-file samconfig.toml
```

The stack provisions `EvalBucket`, `ResultsBucket`, **and a CloudTrail trail** (with its own `TrailLogBucket`) automatically — no pre-existing buckets or trails needed. CloudTrail is required because "AWS API Call via CloudTrail" events only reach EventBridge when a trail captures them in the region; fresh sandbox accounts have no trail, so `PromptVersionPublishedRule` would never fire without this. On `Create`, the `SeedEvalAssetsCustomResource` Lambda uploads the dataset and thresholds into `EvalBucket`. The prompt template is **not** uploaded — it lives in the Bedrock-managed prompt you created in step 3.1.

The first eval run does **not** start automatically on deploy. Trigger one with section 4 below (publish a new prompt version) or by re-syncing the Knowledge Base.

### 3.5 Confirm the SNS email subscription

AWS sends a confirmation email to `NotificationEmail` immediately after the stack is created. **Click the "Confirm subscription" link in that email**, or you will not receive PASS/FAIL notifications.

### 3.6 Watch the first eval run

```bash
# List recent Step Functions executions
aws stepfunctions list-executions \
  --state-machine-arn $(aws cloudformation describe-stacks \
      --stack-name rag-eval-pipeline \
      --region us-east-1 \
      --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
      --output text) \
  --region us-east-1 \
  --max-items 5
```

A full run takes ~10–25 minutes (5 min initial wait + 30 s polling loop until the Bedrock evaluation job completes). The final SNS email contains the PASS/FAIL verdict and per-metric scores (`Faithfulness`, `Correctness`, `Completeness`, `Helpfulness`, `LogicalCoherence`).

---

## 4. Re-trigger the evaluation pipeline (workshop demo)

The canonical demo: edit the Bedrock-managed prompt and publish a new version. CloudTrail logs the `CreatePromptVersion` API call, EventBridge routes it through `PromptVersionPublishedRule`, and a fresh eval run starts within ~1–2 minutes (CloudTrail propagation latency).

**Option A — Bedrock console (recommended for the workshop):**

1. Bedrock console → **Prompt management** → open `rag-eval-kb-prompt`.
2. Edit the DRAFT (the prompt text uses `{{search_results}}` / `{{query}}` here).
3. Click **Save draft**, then **Create version**.

**Option B — CLI:**

```bash
# Edit the source-of-truth template, push it to the Bedrock prompt's DRAFT, and publish.
$EDITOR evaluation/prompts/kb_prompt_template.txt
python evaluation/scripts/create_eval_prompt.py
```

**Option C — `make trigger`:** the shortcut for Option B above. Edit `evaluation/prompts/kb_prompt_template.txt` first if you want a meaningful change; otherwise `make trigger` still publishes a new version (the template content can be identical to the previous version), which is enough to fire the rule.

The Lambda pulls the just-published version's text via `bedrock-agent:GetPrompt`, rewrites `{{var}}` back to `$var$` (the syntax the RAG evaluation API requires), and starts the eval job.

> **CloudTrail dependency.** `PromptVersionPublishedRule` only matches "AWS API Call via CloudTrail" events when a CloudTrail trail is capturing management events in `us-east-1`. The eval stack provisions one for you (`<stack>-eventbridge-trail`), so this is hands-off in a fresh sandbox account. If your account has org-level SCPs that suppress CloudTrail or that block the stack from creating one, the rule won't fire — verify with `aws cloudtrail list-trails --region us-east-1`.

Other ways to trigger a run:

- **Re-sync the KB** (e.g. drop a new file in `src/data/` and run `seed_and_ingest.py` — the `KbSyncCompletionRule` fires on Bedrock's `Sync` complete event).
- **Manually start the state machine** from the Step Functions console with an empty payload `{}`.

---

## 5. Teardown

Tear down in **reverse order** (eval first, then KB) so the eval pipeline doesn't lose its KB mid-run.

**Shortcut:** `make teardown` (eval, then KB). You can also delete one stack at a time with `make teardown-eval` or `make teardown-kb`.

```bash
# Evaluation pipeline — sam delete empties EvalBucket + ResultsBucket + TrailLogBucket automatically
cd evaluation
sam delete --stack-name rag-eval-pipeline --region us-east-1

# KB provisioning — custom-resource Lambda empties the source bucket before CFN deletes it
cd ../kb_provisioning
sam delete --stack-name kb-provisioning --region us-east-1
```

If a stack is stuck, check CloudWatch Logs for the custom-resource Lambdas (`seed-and-ingest` for KB, `seed-eval-assets` for eval).

---

## 6. Common errors

| Error | Likely cause | Fix |
|---|---|---|
| `Unable to locate credentials` | `aws configure` not run | Re-run step 1.4 |
| `AccessDeniedException` from Bedrock | Model access not granted | Bedrock console → Model access → enable Titan v2 + Nova Pro |
| `Invocation of model ID ... with on-demand throughput isn't supported` | The model is inference-profile-only (e.g. Nova 2 Lite/Pro) | Switch the ID to the cross-region profile (e.g. `us.amazon.nova-2-lite-v1:0`) in `evaluation/samconfig.toml` |
| `BucketAlreadyExists` | Another stack used the same name | Override `SourceBucketName` or `VectorBucketName` in `kb_provisioning/samconfig.toml` |
| `InvalidLocationConstraint` | S3 Vectors not available in chosen region | Use `us-east-1` |
| `ValidationException` on KB create | Region mismatch between `region` and `EmbeddingModelArn` | Keep both on `us-east-1` |
| `KnowledgeBaseId is required` from eval Lambda | `KnowledgeBaseId` left blank in `evaluation/samconfig.toml` | Paste the value from the KB stack output (step 2) |
| `Parameter PromptResourceId has no default value` on `sam deploy` | `PromptResourceId` left blank in `evaluation/samconfig.toml` | Run `create_eval_prompt.py` (step 3.1) and paste the printed ID |
| `AccessDeniedException` on `bedrock:GetPrompt` from start-eval-job Lambda | `PromptResourceId` points at a prompt in a different account/region | Re-create the prompt in `us-east-1` with `create_eval_prompt.py --region us-east-1` |
| New prompt version published, but no eval run starts | CloudTrail trail not created (e.g. blocked by an SCP) | Run `aws cloudtrail list-trails --region us-east-1` — must include `<stack>-eventbridge-trail` |
| SNS emails never arrive | Subscription not confirmed | Click the AWS confirmation email from step 3.5 |
| Eval pipeline idle after KB re-sync | KB and eval stacks deployed to different regions | Re-deploy both to the same region |

---

## 7. Running tests (optional)

Both stacks ship pytest suites that run against mocked AWS clients (no live AWS calls).

**Shortcut:** `make test` runs both suites.

```bash
# From the repo root, with the venv activated:
pytest kb_provisioning/tests/   -v
pytest evaluation/tests/        -v
```

---

## Reference: running the LangGraph email app locally

If you also want to run the email-support app that consumes the Knowledge Base, see the original setup below.

### Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
```

Create a `.env` file (copy `.env.example`) with at minimum:

```bash
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
LLM_WRITER=...
LLM_CATEGORIZER=...
KNOWLEDGE_BASE_ID=<paste from kb_provisioning stack output>
```

Place your Gmail OAuth client secret at `credentials.json` in the repo root. A `token.json` will be generated on first run.

### Run

```bash
# Full workflow once
python main.py

# Or in LangGraph Studio
uv add "langgraph-cli[inmem]"
langgraph dev
```

### Graph

```
START → load_email → categorize_email → query_or_email
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼ (tool call)                                  ▼ (no tool call)
                    retrieve ─────────► write_email_with_context ──► send_email → END
```

See `src/graph/email_graph.py` for the construction and `CLAUDE.md` for the architecture deep-dive.

---

## References

Walkthrough video: https://youtu.be/R4Lwz2ChKGQ
