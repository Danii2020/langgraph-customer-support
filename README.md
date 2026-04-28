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

### 🔭 Observability with LangSmith

[LangSmith](https://smith.langchain.com/) is Anthropic's observability platform for LLM applications. It records every step of the graph as a structured trace: you can see which node ran, how long it took, the exact prompt that reached Bedrock, the model's raw response, token counts, and any retriever queries — all in a browsable UI without adding any logging code.

**1. Get an API key**

Sign in at [https://smith.langchain.com/](https://smith.langchain.com/), open **Settings → API Keys**, and create a new key.

**2. Set the environment variables**

Add these four lines to your `.env` file:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_...      # your key from step 1
LANGSMITH_PROJECT=langgraph-gmail  # project bucket name in the UI
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

**3. Run the graph**

```bash
python main.py
```

**4. What you should see**

Open the `langgraph-gmail` project in the LangSmith UI. The newest run will contain:

- `node.load_email` — Gmail fetch span
- `node.categorize_email` — Bedrock categorizer span (with full prompt + structured output)
- `node.query_or_email` — RAG planner span (with tool-call decision)
- `retrieve` — retriever tool span with input query and returned documents (when applicable)
- `node.write_email_with_context` — Bedrock writer span (with full prompt + structured reply)
- `node.send_email` — Gmail send span
- `gmail.fetch_most_recent` and `gmail.send_reply` — Gmail API calls as child tool runs

**5. Turning it off**

Remove `LANGSMITH_API_KEY` from `.env`, or set `LANGSMITH_TRACING=false`. The graph runs exactly as before — no exceptions, no warnings, no extra latency.

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
