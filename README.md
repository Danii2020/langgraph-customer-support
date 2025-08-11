## LangGraph Automatic Customer Support Workflow

End‑to‑end automated email support pipeline using LangGraph, a RAG tool over a Chroma vector store, and the Gmail API. The graph now:

- Loads the latest unread email from Gmail
- Classifies the email
- Optionally retrieves knowledge‑base context via RAG
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

- Python 3.9+
- OpenAI API key
- Gmail OAuth client secret file: `credentials.json` (will generate `token.json` on first run)
- [UV](https://github.com/astral-sh/uv) for virtualenv and dependency install

Optional but recommended:
- Update the knowledge base at `src/data/data.txt` (used by RAG)

---

### ⚙️ Installation

1) Create & activate a virtual environment

```bash
uv venv
source .venv/bin/activate
```

2) Install dependencies

```bash
uv pip install -r requirements.txt
```

3) Configure environment

- Set your OpenAI key in `.env`:

```
OPENAI_API_KEY=sk-...
```

4) Prepare Gmail credentials

- Place your OAuth client secret at the project root as `credentials.json`
- On first run, a browser window will open to authorize Gmail; a `token.json` will be created

5) (Optional) Edit the knowledge base

- Update `src/data/data.txt` with product/service information
- The Chroma DB persists at `./chroma_db` and is built automatically from `data.txt`

---

### 🧭 How it works

Graph construction and flow:

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

- The RAG tool is created in `src/utils/rag_utils.py` using Chroma and OpenAI embeddings. It indexes `src/data/data.txt` and exposes a retriever tool to the agent.
- The writer agent creates the reply, optionally leveraging retrieved context, and outputs a structured `Email` object.
- The sender node posts a reply to the original thread using the Gmail API, preserving threading headers.

---

### 📝 Usage

Run the full workflow:

```bash
python main.py
```

What happens:

1) Fetch latest unread email from Gmail
2) Categorize it
3) If category is `product_enquiry` or `customer_complaint`, query the knowledge base via the retriever tool
4) Generate a Spanish reply email with context
5) Send the reply in the same Gmail thread

Note: On the first run, you will be prompted to authorize Gmail in the browser. Subsequent runs will reuse `token.json`.

---

### 📚 Knowledge base (RAG)

- Data source: `src/data/data.txt`
- Vector store: Chroma at `./chroma_db` (auto‑persisted)
- You can refresh the KB by editing `data.txt` and deleting `./chroma_db` before the next run

---

### 🔒 Gmail sending details

- Scope used: `https://www.googleapis.com/auth/gmail.modify`
- Replies include `In-Reply-To`, `References`, and `threadId` so they appear properly threaded
- Original sender address is extracted from headers and used for the reply destination

---

### 📖 References

Watch the YouTube video for a walkthrough: `https://youtu.be/R4Lwz2ChKGQ`

---

Enjoy building your automated customer support workflow! 🚀
