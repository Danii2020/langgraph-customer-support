## LangGraph Automatic Customer Support Workflow

End‑to‑end automated email support pipeline using LangGraph, Amazon Bedrock (LLMs + Amazon Knowledge Bases), and the Gmail API. The graph:

- Loads the latest unread email from Gmail
- Classifies the email
- Optionally retrieves knowledge‑base context via Amazon Knowledge Bases (RAG)
- Writes a structured reply
- Sends the reply back in the same Gmail thread

---

### 🚀 Features

- **Node 1: Load Latest Email** — connects to Gmail and retrieves the most recent unread email
- **Node 2: Classify Email** — categorizes into `product_enquiry`, `customer_complaint`, `customer_feedback`, `unrelated`
- **Node 3: RAG + Reply Planning** — decides whether to call the retriever tool (for enquiries/complaints) and prepares context
- **Node 4: Write Reply with Context** — generates a professional reply using retrieved context when available
- **Node 5: Send Reply (Gmail API)** — sends a threaded reply using proper headers (`In-Reply-To`, `References`, `threadId`)

---

### 🧰 Prerequisites

- **Python**: 3.9+
- **AWS account with Amazon Bedrock access**:
  - Bedrock enabled in the target region (e.g. `us-east-2`)
  - Permission to call Bedrock models and Amazon Knowledge Bases
- **AWS credentials configured** on your machine, for example via:
  - Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, optional `AWS_SESSION_TOKEN`, `AWS_REGION`)
  - Or an AWS profile configured with the AWS CLI
- **Gmail OAuth client secret file**: `credentials.json` at the project root (will generate `token.json` on first run)
- **[UV](https://github.com/astral-sh/uv)** for virtualenv and dependency install

---

### ⚙️ Installation

1) **Create & activate a virtual environment**

```bash
uv venv
source .venv/bin/activate
```

2) **Install dependencies**

```bash
uv pip install -r requirements.txt
```

3) **Configure environment variables**

Create a `.env` file (for example by copying from a local template such as `.env.example`) and set at least:

```bash
AWS_ACCESS_KEY_ID=your_aws_access_key_id
AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
# Optional if you use temporary credentials (for example, via AWS SSO)
AWS_SESSION_TOKEN=your_optional_session_token
AWS_REGION=us-east-2
```

These variables are loaded via `python-dotenv` and used by `boto3` / `langchain_aws` to authenticate against Amazon Bedrock and Amazon Knowledge Bases.

4) **Prepare Gmail credentials**

- Place your OAuth client secret at the project root as `credentials.json`
- On first run, a browser window will open to authorize Gmail; a `token.json` will be created

---

### 🧭 How it works

**Graph construction and flow** (see `src/graph/email_graph.py`):

```1:33:src/graph/email_graph.py
from langgraph.graph import START, StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from ..utils.rag_utils import get_retriever_tool
from ..nodes import NODES
from ..state import GraphState


class EmailSupportGraph:
    def __init__(self):
        workflow = StateGraph(GraphState)
        workflow.add_node("load_email", NODES["email_listener"])
        workflow.add_node("categorize_email", NODES["email_categorizer"])
        workflow.add_node("query_or_email", NODES["query_or_email"])
        workflow.add_node("retrieve", ToolNode([get_retriever_tool()]))
        workflow.add_node("write_email_with_context", NODES["email_writer_with_context"])
        workflow.add_node("send_email", NODES["email_sender"])

        workflow.add_edge(START, "load_email")
        workflow.add_edge("load_email", "categorize_email")
        workflow.add_edge("categorize_email", "query_or_email")

        workflow.add_conditional_edges(
            "query_or_email",
            tools_condition,
            {
                "tools": "retrieve",
                END: "write_email_with_context"
            }
        )

        workflow.add_edge("retrieve", "write_email_with_context")
        workflow.add_edge("write_email_with_context", "send_email")
        workflow.add_edge("send_email", END)

        self.graph = workflow.compile()
```

- **LLMs via Amazon Bedrock**: the categorizer and writer agents use Bedrock models defined in `src/agents/bedrock.py` (for example, Anthropic Claude and Amazon Nova models).
- **RAG via Amazon Knowledge Bases**: the retriever tool is created in `src/utils/rag_utils.py` using `AmazonKnowledgeBasesRetriever`, which queries your configured Knowledge Base in Bedrock. No local vector DB (e.g. Chroma) is required.
- **Email sending**: the sender node posts a reply to the original thread using the Gmail API, preserving threading headers.

---

### 📝 Usage

#### Run locally with Python

Run the full workflow:

```bash
python main.py
```

What happens:

1) Fetch latest unread email from Gmail
2) Categorize it using an Amazon Bedrock model
3) If category is `product_enquiry` or `customer_complaint`, query your Amazon Knowledge Base via the retriever tool
4) Generate a reply email with context using an Amazon Bedrock model
5) Send the reply in the same Gmail thread

Note: On the first run, you will be prompted to authorize Gmail in the browser. Subsequent runs will reuse `token.json`.

#### Run via LangSmith Studio (LangGraph Studio)

You can also run and visualize this graph in LangSmith Studio using the LangGraph CLI.

- **Additional prerequisite**:
  - Install the LangGraph CLI with in-memory storage:

    ```bash
    uv add "langgraph-cli[inmem]"
    ```

- **Start the LangGraph dev server**:

  From the project root, run:

  ```bash
  langgraph dev
  ```

- Then open LangSmith Studio (LangGraph Studio) in your browser (the CLI will print the URL) to interactively run and debug the workflow.

---

### Provisioning the Knowledge Base (workshop)

This repo ships a SAM stack at `kb_provisioning/` that provisions the entire
Bedrock Knowledge Base in a single command — no console clicks required.

#### Pre-flight checklist

Complete these checks **before** the workshop starts. A failure at any step
blocks `sam deploy`.

1. **AWS CLI v2 installed**
   ```bash
   aws --version   # must show aws-cli/2.x or higher
   ```
   Install: `brew install awscli` or see https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

2. **SAM CLI >= 1.100 installed** (required for `AWS::S3Vectors::*` resource support)
   ```bash
   sam --version   # must show 1.100 or higher
   ```
   Install: `brew install aws-sam-cli` or see https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html

3. **AWS credentials configured locally**
   ```bash
   aws sts get-caller-identity --region us-east-1
   # Must return a valid Account and Arn. If this fails, run:
   aws configure           # long-lived access key
   # OR
   aws sso login           # IAM Identity Center / SSO
   ```
   This stack uses the standard AWS credential provider chain. It does **not**
   accept access keys as CloudFormation parameters and does **not** read
   `AWS_ACCESS_KEY_ID` from `.env`. Attendees who have not configured credentials
   before the workshop will be blocked at `sam deploy`.

4. **Titan v2 model access granted**
   In the AWS Console: **Amazon Bedrock -> Model access -> Manage model access**
   -> enable `Amazon Titan Text Embeddings V2` (`amazon.titan-embed-text-v2:0`)
   in `us-east-1` (or your chosen workshop region).
   This cannot be done from CloudFormation; it is a prerequisite.

#### Deploy the KB stack

```bash
# Step 0: copy seed data into the Lambda package
python kb_provisioning/scripts/prepare_lambda_assets.py

# Step 1: build + deploy (from repo root; samconfig pins region to us-east-1)
cd kb_provisioning
sam build
sam deploy --config-file samconfig.toml
```

After `sam deploy` returns, find the `KnowledgeBaseId` in the stack outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name kb-provisioning \
  --region us-east-1 \
  --query "Stacks[0].Outputs"
```

#### Wire the output into the LangGraph app and evaluation pipeline

1. Copy `KnowledgeBaseId` into `.env`:
   ```
   KNOWLEDGE_BASE_ID=<KnowledgeBaseId from stack output>
   AWS_REGION=us-east-1
   ```

2. Copy `KnowledgeBaseId` into `evaluation/samconfig.toml`'s `parameter_overrides`:
   ```
   KnowledgeBaseId="<same value>"
   ```

#### Region alignment

Both `kb_provisioning/samconfig.toml` and `evaluation/samconfig.toml` default to
`us-east-1`. Deploy both stacks to the **same region** — if they differ, the
evaluation pipeline's `KbSyncCompletionRule` EventBridge rule will never fire.

If you change the region, also update `region_name="us-east-2"` in
`src/agents/bedrock.py` and `region_name="us-east-1"` in the three eval Lambda
handlers under `evaluation/lambdas/`.

#### Teardown

```bash
cd kb_provisioning
sam delete --stack-name kb-provisioning --region us-east-1
```

The stack's custom resource Lambda empties the source S3 bucket before CFN
deletes it, so teardown completes cleanly.

#### Fallback (if the custom resource hits IAM issues)

```bash
# Deploy without auto-ingestion, then seed manually:
sam deploy --config-file samconfig.toml --parameter-overrides EnableAutoIngestion=false
python kb_provisioning/scripts/seed_and_ingest.py \
    --stack-name kb-provisioning \
    --region us-east-1
```

---

### 📚 Knowledge base (RAG)

- Backed by **Amazon Knowledge Bases for Amazon Bedrock**, configured in your AWS account.
- The app uses `AmazonKnowledgeBasesRetriever` (see `src/utils/rag_utils.py`) to query this Knowledge Base and retrieve relevant documents for each email.
- To update the knowledge base, manage your data sources and indexing directly from the AWS console for Amazon Knowledge Bases.

---

### 🔒 Gmail sending details

- Scope used: `https://www.googleapis.com/auth/gmail.modify`
- Replies include `In-Reply-To`, `References`, and `threadId` so they appear properly threaded
- Original sender address is extracted from headers and used for the reply destination

---

### 📖 References

Watch the YouTube video for a walkthrough: https://youtu.be/R4Lwz2ChKGQ

---

Enjoy building your automated customer support workflow! 🚀
