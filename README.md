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

For workshop simplicity we grant **`AdministratorAccess`** plus **`AmazonBedrockMarketplaceAccess`**. Do **not** use the root user.

In the AWS Console:

1. **IAM → Users → Create user**
2. User name: `workshop-admin` (any name is fine).
3. **Do not** check "Provide user access to the AWS Management Console" unless you also want console access.
4. **Next → Attach policies directly →** search and check **both**:
   - `AdministratorAccess` — broad permissions for the SAM stacks
   - `AmazonBedrockMarketplaceAccess` — required to subscribe to Bedrock-Marketplace-gated models (Claude 4.x, some Mistral/Cohere). Without it, the first invocation fails with `aws-marketplace:Subscribe` denied even though `AdministratorAccess` is attached, because some accounts have explicit Marketplace boundaries.
5. **Next → Create user**.
6. Open the new user → **Security credentials** tab → **Create access key**.
7. Choose **Command Line Interface (CLI)** → confirm the warning → **Create access key**.
8. **Copy or download the Access Key ID and Secret Access Key now** — the secret is only shown once.

### 1.3 Install AWS CLI v2

**macOS** (Homebrew):

```bash
brew install awscli
```

**Linux** (x86_64, official installer — requires `curl` and `unzip`):

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

For ARM-based Linux (e.g. Graviton / Raspberry Pi), replace `x86_64` with `aarch64` in the URL.

**Windows** (PowerShell, official MSI installer):

```powershell
msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi
```

Verify the install on any OS:

```bash
aws --version   # must show aws-cli/2.x or higher
```

For other installation paths, see the
[AWS CLI v2 install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).

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

**macOS** (Homebrew):

```bash
brew install aws-sam-cli
```

**Linux** (x86_64, official installer — requires `curl` and `unzip`):

```bash
curl -L "https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip" -o "aws-sam-cli.zip"
unzip aws-sam-cli.zip -d sam-installation
sudo ./sam-installation/install
```

**Windows**: download and run the official 64-bit MSI installer:
[AWS_SAM_CLI_64_PY3.msi](https://github.com/aws/aws-sam-cli/releases/latest/download/AWS_SAM_CLI_64_PY3.msi).
After the installer finishes, **open a new PowerShell or cmd window** so `sam` lands on `PATH`.

> Windows attendees may also need to enable long path support — see the
> [SAM CLI Windows install guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
> if `sam build` fails with path-length errors.

Verify the install on any OS:

```bash
sam --version   # must show 1.100 or higher
```

### 1.6 Install Python 3.13 and a virtualenv

The seed/upload helper scripts run locally. Python 3.13+ is required.

**macOS** (Homebrew):

```bash
brew install python@3.13
```

**Linux** (Ubuntu/Debian via the deadsnakes PPA — Python 3.13 is not yet in default repos on most LTS releases):

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.13 python3.13-venv
```

On Fedora/RHEL: `sudo dnf install -y python3.13`. Other distros: download from
[python.org/downloads](https://www.python.org/downloads/).

**Windows**: download the installer from
[python.org/downloads/windows](https://www.python.org/downloads/windows/)
and tick **"Add python.exe to PATH"** in the first installer screen.

Verify and create the virtualenv:

```bash
python3 --version   # must show 3.13.x  (use `python --version` on Windows)

# Create and activate a venv at the repo root
python3 -m venv .venv         # macOS / Linux
source .venv/bin/activate

# On Windows (PowerShell), activate with:
#   .venv\Scripts\Activate.ps1
# On Windows (cmd):
#   .venv\Scripts\activate.bat

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
| Amazon Nova Pro | `amazon.nova-pro-v1:0` | Eval generator (default `BedrockModelId`) |
| Meta Llama 3.1 70B Instruct | `meta.llama3-1-70b-instruct-v1:0` | Eval evaluator (default `EvaluatorModelId`) — see §3.2 for why |

The evaluator is a different model family from the generator on purpose — same-family judges introduce scoring bias. Enable model access for Llama 3.1 70B Instruct in **all three US regions** (`us-east-1`, `us-east-2`, `us-west-2`) since the workshop uses the `us.` cross-region inference profile.

If you plan to use a different generator/evaluator model, enable that model instead and override `BedrockModelId` / `EvaluatorModelId` in `evaluation/samconfig.toml`. Read §3.2 first — Bedrock RAG eval curates the evaluator allow-list and most newer Claudes are rejected.

> **Inference-profile-only models.** Newer models (e.g. `amazon.nova-2-lite-v1:0`, `amazon.nova-2-pro-v1:0`) **cannot** be invoked via the bare foundation-model ID — Bedrock returns `Invocation … with on-demand throughput isn't supported`. Use the system-defined cross-region inference profile ID instead (e.g. `us.amazon.nova-2-lite-v1:0`). The stack's `EvalServiceRole` is already configured to invoke inference profiles + their underlying foundation models in any region, so no template changes are needed.

> **Marketplace-subscribed models.** Anthropic Claude 4.x (and some Cohere/Mistral models) are sold through AWS Marketplace, not direct model access. On the Model access page they show a **"Subscribe in AWS Marketplace"** button instead of the usual checkbox. Click through, accept the EULA (free for Anthropic models on Bedrock), wait ~2 minutes for activation, then retry. Without the subscription, the first invocation fails with `aws-marketplace:ViewSubscriptions / aws-marketplace:Subscribe` denied — this is the gotcha that `AmazonBedrockMarketplaceAccess` on your IAM user (step 1.2) lets you click past. Do the subscription in **all three** US regions (`us-east-1`, `us-east-2`, `us-west-2`) if you're using a `us.` cross-region profile.

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

### 3.2 Wire the KB ID, prompt ID, and model IDs into the eval config

Edit `evaluation/samconfig.toml` and set `KnowledgeBaseId` (from step 2) and `PromptResourceId` (from step 3.1) in `parameter_overrides`:

```toml
parameter_overrides = "KnowledgeBaseId=\"<paste KnowledgeBaseId here>\" PromptResourceId=\"<paste prompt id here>\" BedrockModelId=\"us.amazon.nova-2-lite-v1:0\" EvaluatorModelId=\"us.meta.llama3-1-70b-instruct-v1:0\" NotificationEmail=\"<your-email>\" MaxPollingIterations=\"40\""
```

Also set `NotificationEmail` to an inbox you can check — SNS will email PASS/FAIL verdicts there.

#### Choosing `BedrockModelId` (generator) and `EvaluatorModelId` (judge)

The defaults above are intentional and battle-tested:

- **`BedrockModelId=us.amazon.nova-2-lite-v1:0`** — cheap, fast, current Nova-family generator. Inference-profile-only, hence the `us.` prefix. Swap freely; any current Bedrock generator works. If you swap in a **Claude 4.5+ model** (Sonnet 4.5, Haiku 4.5, Opus 4.5, Sonnet 4.6), note that the generator inference config in `evaluation/lambdas/start_eval_job/handler.py` sets `temperature` only (no `topP`) — Claude 4.5+ rejects both being specified together with `temperature and top_p cannot both be specified for this model`. The default config is portable across all current generator choices.
- **`EvaluatorModelId=us.meta.llama3-1-70b-instruct-v1:0`** — Llama 3.1 70B Instruct via the US cross-region inference profile. **Different family from the generator on purpose** (Meta judging Nova) to avoid same-family scoring bias in LLM-as-judge.

**About the evaluator allow-list.** Unlike the generator, the evaluator can't be any Bedrock model — Bedrock RAG eval gates the judge to a curated allow-list (so metric scoring stays calibrated) and the [public list](https://docs.aws.amazon.com/bedrock/latest/userguide/evaluation-kb.html) lags model releases by 12+ months. As of 2026-05 the realistic non-Amazon options for `RagEvaluation` jobs are:

| Evaluator | Status | Notes |
|---|---|---|
| `us.meta.llama3-1-70b-instruct-v1:0` | ✅ Default — works | Different family from Nova, alive, capable |
| `amazon.nova-pro-v1:0` | ✅ Works | Same family as Nova generator → bias risk; use only if Llama unavailable |
| `mistral.mistral-large-2402-v1:0` | ⚠️ Old (Feb 2024) | Last-resort cross-family option |
| `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | ⚠️ Likely EOL | Anthropic 3.x family deprecates aggressively |
| `us.anthropic.claude-3-7-sonnet-20250219-v1:0` | ❌ EOL (confirmed) | Returns "model version has reached the end of its life" |
| `us.anthropic.claude-opus-4-5-20251101-v1:0` and any Claude 4.x | ❌ Not on allow-list | Returns "does not have permission to call the model" |

Stick with the default Llama 3.1 unless you have a specific reason to change it. If the deploy reports it's also EOL, fall back to `amazon.nova-pro-v1:0` and acknowledge the same-family bias in your workshop narrative.

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
| `Invocation of model ID ... with on-demand throughput isn't supported` | The model is inference-profile-only (e.g. Nova 2 Lite/Pro, all Claude 4.x) | Switch the ID to the cross-region profile (e.g. `us.amazon.nova-2-lite-v1:0`) in `evaluation/samconfig.toml` |
| `The provided role ... does not have permission to call the model: <evaluator>` or `The requested evaluator model(s) ... are not supported` | **Allow-list rejection disguised as IAM.** Bedrock RAG eval curates the evaluator (judge) model list. Newer models (e.g. all Claude 4.x) are not on it. See the evaluator table in §3.2. | Use `us.meta.llama3-1-70b-instruct-v1:0` (default) or `amazon.nova-pro-v1:0`. The AWS docs list Llama 3.3, Mistral Large, and several Claudes — most are EOL or only valid for `ModelEvaluation` (not `RagEvaluation`). |
| `The model version: <evaluator> has reached the end of its life` | The allow-listed evaluator is EOL. AWS doesn't proactively prune the docs list — affects older Claudes especially (3.5 Sonnet, 3.7 Sonnet confirmed EOL as of 2026-05). | Switch to `us.meta.llama3-1-70b-instruct-v1:0` (cross-family default) or `amazon.nova-pro-v1:0`. See §3.2 for the full survivor list. |
| `Model access is denied due to ... aws-marketplace:ViewSubscriptions, aws-marketplace:Subscribe` | The chosen generator/evaluator is sold via AWS Marketplace (Claude 4.x especially), and the IAM user lacks Marketplace permissions OR the subscription hasn't been completed in the Bedrock console. | Attach `AmazonBedrockMarketplaceAccess` to your IAM user (§1.2). Then Bedrock console → Model access → click **"Subscribe in AWS Marketplace"** for the model and complete the (free) EULA. Wait ~2 minutes for activation. |
| `temperature and top_p cannot both be specified for this model` | You swapped the generator to a Claude 4.5+ model, which enforces XOR between the two params. | The Lambda config in `evaluation/lambdas/start_eval_job/handler.py` only sets `temperature` by default. If you've added a custom inference config that sets both, drop `topP` and keep `temperature`. |
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
