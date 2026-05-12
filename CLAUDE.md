# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

This repo contains three related Python projects:

1. **LangGraph email-support app** (root, `src/`, `main.py`) — runs locally, reads Gmail, replies via Bedrock + Knowledge Bases.
2. **RAG evaluation pipeline** (`evaluation/`) — an AWS SAM application (Lambdas + Step Functions + EventBridge + SNS) that auto-evaluates the Bedrock Knowledge Base used by app #1 whenever the KB is re-synced or the prompt template changes. The two share `KNOWLEDGE_BASE_ID` but are deployed independently.
3. **KB provisioning stack** (`kb_provisioning/`) — an AWS SAM application that provisions the Bedrock Knowledge Base (S3 Vectors store + Titan Text Embeddings V2), seeds it with workshop data, and starts the initial ingestion job in a single `sam deploy`. Produces the `KnowledgeBaseId` that apps #1 and #2 consume.

## Commands

### LangGraph app (root)

```bash
# Setup (UV-based; project requires python >= 3.13)
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Run the workflow once (fetch → categorize → RAG → reply → send)
python main.py

# Run in LangGraph Studio (graph entry: ./main.py:graph, env loaded from .env)
langgraph dev
```

`credentials.json` (Gmail OAuth client secret) must sit at the repo root. `token.json` is generated on first run and is git-ignored. The `.env` keys you need: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `LLM_WRITER`, `LLM_CATEGORIZER`, `KNOWLEDGE_BASE_ID` (see `.env.example`).

### Provisioning pipeline (`kb_provisioning/`)

```bash
# Dev/test deps
pip install -r kb_provisioning/requirements-dev.txt

# Run Lambda unit tests
pytest kb_provisioning/tests/                    # all
pytest kb_provisioning/tests/test_seed_and_ingest.py -v   # verbose

# Copy seed data into the Lambda package (run before every sam build)
python kb_provisioning/scripts/prepare_lambda_assets.py

# Build & deploy the SAM stack (parameters live in kb_provisioning/samconfig.toml)
cd kb_provisioning && sam build && sam deploy --config-file samconfig.toml

# Teardown
cd kb_provisioning && sam delete --stack-name kb-provisioning --region us-east-1

# Re-seed manually (fallback if EnableAutoIngestion=false)
python kb_provisioning/scripts/seed_and_ingest.py \
    --stack-name kb-provisioning --region us-east-1
```

### Evaluation pipeline (`evaluation/`)

```bash
# Dev/test deps
pip install -r evaluation/requirements-dev.txt

# Run Lambda unit tests
pytest evaluation/tests/                     # all
pytest evaluation/tests/test_parse_eval_results.py::test_name -v   # single test

# Copy seed files into the Lambda package (run before every sam build)
python evaluation/scripts/prepare_lambda_assets.py

# Build & deploy the SAM stack (parameters live in evaluation/samconfig.toml)
# The stack provisions EvalBucket and ResultsBucket automatically;
# no pre-existing S3 buckets are required.
cd evaluation && sam build && sam deploy --config-file samconfig.toml

# Teardown — sam delete empties both EvalBucket and ResultsBucket automatically
cd evaluation && sam delete --stack-name rag-eval-pipeline --region us-east-1

# Retrigger the pipeline (workshop demo): publish a new version of the
# Bedrock prompt. CreatePromptVersion is logged by CloudTrail, EventBridge
# routes it through PromptVersionPublishedRule, and a fresh
# EvalPipelineStateMachine execution starts within ~1-2 minutes.
aws bedrock-agent create-prompt-version --prompt-identifier <PromptResourceId> --region us-east-1
```

## Architecture

### LangGraph workflow (`src/graph/email_graph.py`)

Linear 6-node graph with one conditional branch:

```
START → load_email → categorize_email → query_or_email
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼ (tool call)                                  ▼ (no tool call)
                    retrieve ─────────► write_email_with_context ──► send_email → END
```

- `query_or_email` is the *router*: it's an LLM bound to the retriever tool that decides whether to call RAG. `tools_condition` (langgraph prebuilt) inspects the resulting `AIMessage`; if it contains tool calls, flow goes to `retrieve` (a `ToolNode` wrapping `AmazonKnowledgeBasesRetriever`), otherwise straight to `write_email_with_context`. After retrieval, control always merges back into `write_email_with_context`.
- `write_email_with_context` reads the last message from `state["messages"]` as RAG context and produces a structured `Email` (Pydantic) via `llm.with_structured_output(Email)`.
- `send_email` posts the reply via the Gmail API, preserving `In-Reply-To` / `References` / `threadId` so it threads correctly.

### State and type-narrowing (`src/state.py`, `src/nodes/email_writer.py`)

`GraphState["current_email"]` and `GraphState["email_response"]` are typed `Email | str` but in practice can be `dict | Email | str` (LangGraph Studio can inject dicts). The writer node `_get_email_data` normalizes incoming dicts into `Email` instances and writes them back into state — mirror this pattern in any new node that consumes `current_email`. The downstream `email_sender_node` only sends if both `current_email` and `email_response` are concrete `Email` instances.

### Agent factories (`src/agents/`)

- `bedrock.py` constructs two `ChatBedrock` clients (`llm_writer`, `llm_categorizer`) from env vars `LLM_WRITER` / `LLM_CATEGORIZER` and a hardcoded `region_name="us-east-2"`. If you change AWS region for the app, change it here too.
- `email_writer._create_email_writer_chain(use_rag, use_structured_output)` is the shared chain builder. `query_or_email()` returns the RAG-bound, free-form variant; `write_email_with_context()` returns the non-tool, structured-output variant. The two share the same prompt template (`EMAIL_WRITER_PROMPT`).
- `AGENT_REGISTRY` (`src/agents/__init__.py`) instantiates the chains at import time — the Bedrock clients are constructed eagerly, so importing `src.agents` requires valid AWS credentials.

### Prompts and the Cellfone SA convention (`src/prompts/tasks.py`)

`EMAIL_WRITER_TASK` hardcodes the company name **"Cellfone SA"**, sender address **`eedani116@gmail.com`**, and instructs the model to **reply in Spanish**. If you're rebranding or generalizing the workflow, this is the file to change — these are not configurable via env.

### RAG retriever (`src/utils/rag_utils.py`)

Module-level construction of `AmazonKnowledgeBasesRetriever` and `create_retriever_tool`. `KNOWLEDGE_BASE_ID` and `AWS_REGION` are read at import time. The tool name is `retrieve_prodcuts_and_services_information` (note the typo — the LLM is bound to that exact name; renaming requires updating any prompt that references it).

### Gmail integration (`src/utils/gmail_utils.py`)

- Scope: `gmail.modify`. The `get_most_recent_email()` query is `after:<today>` — if no email arrived today, it returns `""` (the empty-state branch the writer node handles).
- Replies are constructed with a **new** `Message-ID` header, `In-Reply-To: <original>`, `References: <original-references> <original-message-id>`, plus `threadId` in the API body. If the original lacked a `Message-ID`, a synthetic `<{gmail-id}@gmail.com>` is fabricated.

### Provisioning pipeline (`kb_provisioning/`)

The SAM template (`kb_provisioning/template.yaml`) provisions:

- **`KnowledgeBaseRole`** — IAM role trusted by `bedrock.amazonaws.com`; grants `bedrock:InvokeModel` (Titan v2), `s3:GetObject`/`s3:ListBucket` on the source bucket, and `s3vectors:*` on the vector bucket and index.
- **`SourceBucket`** — S3 bucket with EventBridge notifications enabled (so the evaluation pipeline's `KbSyncCompletionRule` receives ingestion-complete events).
- **`VectorBucket` + `VectorIndex`** — `AWS::S3Vectors::VectorBucket` and `AWS::S3Vectors::Index` with 1024-dimension `float32` vectors and `COSINE` distance (Titan v2 defaults).
- **`KnowledgeBase`** — `AWS::Bedrock::KnowledgeBase` backed by the S3 Vectors index, using Titan Text Embeddings V2.
- **`KnowledgeBaseDataSource`** — `AWS::Bedrock::DataSource` pointing at `s3://{SourceBucket}/data/`. `VectorIngestionConfiguration` omitted to inherit Bedrock's default chunking.
- **`SeedAndIngestFunction`** + **`SeedAndIngestCustomResource`** (conditional on `EnableAutoIngestion=true`) — a CloudFormation custom resource Lambda that uploads `src/data/policies.txt` and `src/data/data.txt` to the source bucket and calls `bedrock-agent:StartIngestionJob` on stack `Create`; empties the source bucket on stack `Delete` so CFN can remove it.

Stack output `KnowledgeBaseId` is consumed by `.env` key `KNOWLEDGE_BASE_ID` (LangGraph app) and `evaluation/samconfig.toml` `parameter_overrides` key `KnowledgeBaseId` (eval pipeline). Cross-stack coupling is human-mediated copy/paste. Both stacks must be deployed to the same region for `KbSyncCompletionRule` to receive events.

### Evaluation pipeline (`evaluation/`)

The SAM template (`evaluation/template.yaml`) provisions:

- **`EvalServiceRole`** — IAM role trusted by `bedrock.amazonaws.com`; grants `s3:GetObject`/`s3:ListBucket` on `EvalBucket`, `s3:PutObject`/`s3:GetObject` on `ResultsBucket`, `bedrock:InvokeModel` on the configured generator and evaluator models, and `bedrock:Retrieve`/`bedrock:RetrieveAndGenerate` on the configured Knowledge Base. Auto-provisioned by the stack — no pre-existing IAM role is required. Attendee prep is reduced to four parameters: `KnowledgeBaseId`, `NotificationEmail`, `BedrockModelId`, `EvaluatorModelId`.
- **Three Lambdas** (`lambdas/start_eval_job`, `check_eval_status`, `parse_eval_results`) — each has a thin `handler.py` and is imported by tests directly via `evaluation/tests/`.
- **A Step Functions state machine** that orchestrates: `StartRetrieveAndGenerateJob` → 5-minute initial wait → 30-second poll loop (max iterations from `MaxPollingIterations`, default 40 ≈ ~25 min) → `ParseEvalResults` → SNS notify (PASS/FAIL).
- **Two S3 buckets** (`EvalBucket` for datasets/thresholds/prompt templates, `ResultsBucket` for Bedrock eval output) — provisioned by the stack itself with auto-generated globally-unique names. A `SeedEvalAssetsCustomResource` Lambda uploads the three seed files on stack Create and empties both buckets on stack Delete.
- **Two EventBridge rules** that trigger the state machine: `KbSyncCompletionRule` (on `aws.bedrock` "Bedrock Knowledge Base Data Source Sync" + status `COMPLETE`) and `PromptVersionPublishedRule` (CloudTrail-based: `source: aws.bedrock`, `detail-type: "AWS API Call via CloudTrail"`, `eventName: CreatePromptVersion`, filtered by `requestParameters.promptIdentifier == PromptResourceId`). Note: `CreatePromptVersion` is invoked via the boto3 `bedrock-agent` client but CloudTrail logs it under `eventSource: bedrock.amazonaws.com` (hence the `aws.bedrock` source). `AWS API Call via CloudTrail` events only reach EventBridge when a CloudTrail trail captures them in the region, so the stack also provisions `EventBridgeManagementTrail` + `TrailLogBucket` + its bucket policy. The KB prompt template lives in Bedrock Prompt Management (created by `create_eval_prompt.py`), not in S3.

The pipeline calls `bedrock.create_evaluation_job` with `applicationType="RagEvaluation"` and the five Builtin metrics: `Faithfulness`, `Correctness`, `Completeness`, `Helpfulness`, `LogicalCoherence`. `parse_eval_results` averages each metric across `conversationTurns[*].results[*]`, normalizes names (`Builtin.LogicalCoherence` → `logical_coherence`), and compares against `evaluation/config/thresholds.json` — a metric passes iff `score >= threshold`, and the verdict passes iff every metric passes.

### Region note

The app uses `us-east-2` (hardcoded in `src/agents/bedrock.py` and `src/utils/rag_utils.py` falls back to `us-east-1`). The evaluation Lambdas hardcode `region_name="us-east-1"`, and `evaluation/samconfig.toml` deploys to `us-east-1`. If you move the Knowledge Base, update both sides.
