# Contract: LangSmith Observability

This contract defines the externally-observable behavior of the LangSmith
integration. Every guarantee here traces back to a goal in `intent.md`.

## Required Environment Variables

| Variable | Required? | Default | Purpose |
|---|---|---|---|
| `LANGSMITH_TRACING` | Yes (for tracing on) | unset (treated as off) | Master switch. `"true"` enables export; anything else disables. |
| `LANGSMITH_API_KEY` | Yes (for tracing on) | unset | API key from https://smith.langchain.com/settings. If unset, tracing is silently disabled. |
| `LANGSMITH_PROJECT` | Optional | `"langgraph-gmail"` | Name shown in the LangSmith UI. Each value creates a separate project bucket. |
| `LANGSMITH_ENDPOINT` | Optional | `"https://api.smith.langchain.com"` | Override only for self-hosted LangSmith or the EU region (`https://eu.api.smith.langchain.com`). |

Notes on naming:
- LangSmith historically used `LANGCHAIN_*` prefixes (`LANGCHAIN_TRACING_V2`,
  `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT`, `LANGCHAIN_ENDPOINT`). The
  current `langsmith>=0.3` SDK accepts both forms. **This project standardizes
  on the `LANGSMITH_*` prefix** for consistency with the existing
  `LANGSMITH_API_KEY` already present in `.env`.

## Public API

### Module: `src/observability/langsmith_setup.py` (NEW)

```python
def configure_langsmith() -> bool:
    """
    Idempotently configure LangSmith tracing from environment variables.

    Behavior:
    - If LANGSMITH_TRACING is not "true" (case-insensitive) OR
      LANGSMITH_API_KEY is missing/empty, this is a no-op and returns False.
    - Otherwise, ensures LANGSMITH_PROJECT defaults to "langgraph-gmail"
      and LANGSMITH_ENDPOINT defaults to the public LangSmith URL, then
      returns True.

    Side effects:
    - May set os.environ["LANGSMITH_PROJECT"] and
      os.environ["LANGSMITH_ENDPOINT"] to defaults if unset, so that any
      LangChain / LangGraph module imported AFTER this call uses them.

    Guarantee:
    - Never raises. Network is not contacted by this function; the LangChain
      runtime contacts LangSmith lazily on the first traced run.
    - Calling this function multiple times in the same process is safe.
    """

def is_tracing_enabled() -> bool:
    """Return True iff LangSmith tracing is currently active for this process."""
```

### Module: `src/observability/__init__.py` (NEW)

Re-exports `configure_langsmith`, `is_tracing_enabled`, and `traceable`
(directly from `langsmith`). `langsmith` is a hard transitive dep via
`langchain-core`, so no import fallback is needed.

### Module: `main.py` (MODIFIED)

```python
# At the very top of main.py, BEFORE any `from src...` import that pulls
# in LangChain or LangGraph:
from src.observability import configure_langsmith
configure_langsmith()
```

The contract: `configure_langsmith()` MUST be invoked before
`EmailSupportGraph` is imported, otherwise the LangChain auto-tracing
instrumentation is loaded with the env vars already missing and downstream
nodes will not be exported.

### Decorated Gmail and node functions (MODIFIED)

The following functions gain a `@traceable` decorator from `langsmith`:

| Symbol | File | `name=` in LangSmith | `run_type` |
|---|---|---|---|
| `get_most_recent_email` | `src/utils/gmail_utils.py` | `gmail.fetch_most_recent` | `tool` |
| `send_reply_email` | `src/utils/gmail_utils.py` | `gmail.send_reply` | `tool` |
| `email_listener_node` | `src/nodes/email_listener.py` | `node.load_email` | `chain` |
| `email_categorizer_node` | `src/nodes/email_categorizer.py` | `node.categorize_email` | `chain` |
| `query_or_email_node` | `src/nodes/email_writer.py` | `node.query_or_email` | `chain` |
| `email_writer_with_context_node` | `src/nodes/email_writer.py` | `node.write_email_with_context` | `chain` |
| `email_sender_node` | `src/nodes/email_sender.py` | `node.send_email` | `chain` |

Rationale for explicit node decoration even though LangGraph auto-traces
nodes: with `@traceable` we control the **display name** in the UI, get a
stable run_type, and can attach metadata (see below).

### Metadata Enrichment

Every traced function above attaches the following metadata when available:

| Key | Source | Example |
|---|---|---|
| `email_id` | `state["current_email"].id` | `"19abf9..."` |
| `email_category` | `state["email_category"]` | `"product_enquiry"` |
| `thread_id` | `state["current_email"].thread_id` | `"19abf9..."` |

Implementation note for the executor: use the `metadata=` argument to
`@traceable` for static keys and the `langsmith.run_helpers.get_current_run_tree()`
pattern (or simply put values in the function's return dict) for per-run
keys. The contract only requires that `email_category` is visible in the
LangSmith UI for any run that produced one — the exact mechanism is
flexible.

## Data Models

No new pydantic models. No changes to `GraphState` or `Email`.

## State Changes

No changes to `GraphState`. LangSmith run-context is stored in
LangChain's contextvars, not in the LangGraph state.

## Behavior Guarantees

1. **G1 — Auto-tracing**: When `LANGSMITH_TRACING=true` and a valid
   `LANGSMITH_API_KEY` are set, every invocation of `EmailSupportGraph().graph`
   produces a top-level run in the LangSmith project named by
   `LANGSMITH_PROJECT` (default `"langgraph-gmail"`).
2. **G2 — Node visibility**: That top-level run contains child runs for
   each of the six graph nodes, named per the table above.
3. **G3 — LLM visibility**: Each LLM call inside a node (Bedrock
   categorizer, Bedrock writer with structured output, Bedrock writer with
   tool binding) appears as a `llm` child run with full prompt and response.
4. **G4 — Tool visibility**: Calls to the
   `retrieve_prodcuts_and_services_information` retriever tool appear as
   `tool` child runs with the input query and retrieved documents.
5. **G5 — Gmail visibility**: `get_most_recent_email` and `send_reply_email`
   appear as `tool` child runs in the same trace tree as their parent node.
6. **G6 — Graceful degradation**: If `LANGSMITH_API_KEY` is unset, or
   `LANGSMITH_TRACING` is not `"true"`, no run is exported, no exception
   is raised, no warning is printed, and `main.py` completes with the same
   stdout it produced before this feature.
7. **G7 — Idempotency**: `configure_langsmith()` may be called multiple
   times in the same process without side effects beyond the first call.
8. **G8 — No latency tax when off**: When tracing is disabled, `@traceable`
   decorators add at most a no-op function-call wrapper — no network, no
   thread, no batching.
9. **G9 — Project defaulting**: If `LANGSMITH_TRACING=true` and
   `LANGSMITH_API_KEY` is set but `LANGSMITH_PROJECT` is unset,
   `configure_langsmith()` sets it to `"langgraph-gmail"` so that traces
   never land in LangSmith's `default` project.
10. **G10 — Studio compatibility**: `langgraph dev` (LangGraph Studio)
    must continue to work. Because `langgraph.json` declares `env: ".env"`,
    setting the LangSmith vars in `.env` is sufficient.

## Error Handling Contract

| Error Condition | Behavior | User Impact |
|---|---|---|
| `LANGSMITH_API_KEY` unset | `configure_langsmith()` returns `False`; no env mutation; no traces exported. | App runs normally; no LangSmith UI run. |
| `LANGSMITH_TRACING` is `"false"` / `"0"` / unset | Same as above. | Same. |
| `LANGSMITH_API_KEY` is invalid (rejected by server) | LangSmith client logs at WARNING-level on first export attempt; runs are dropped. | App runs normally; no LangSmith UI run; viewer sees a single warning. |
| `LANGSMITH_ENDPOINT` is unreachable (network failure) | LangSmith client retries internally then drops the run; LangChain never raises into user code. | App runs normally; trace may be incomplete. |
| `configure_langsmith()` called after LangChain modules are already imported | LangChain may have already cached the absence of the env vars; behavior is undefined for runs in that process. | This is a developer-error contract violation; documented in the module docstring as "call this first". |

## Dependencies

### Internal
- New module `src/observability/` — depended on by `main.py` only at startup.
- Decorated functions retain their existing internal dependencies; the
  decorator is a thin wrapper.

### External (already in `requirements.txt` / `pyproject.toml`)
- `langsmith==0.3.45` (transitively via `langchain-core==0.3.68`)
- `langchain==0.3.25`
- `langchain-core==0.3.68`
- `langgraph==0.4.8`
- `python-dotenv==1.1.0`

`pyproject.toml` SHOULD gain `"langsmith>=0.3.45"` as an explicit dependency
(rather than relying on the transitive pin) so future `uv lock` resolves
keep it pinned. This is a one-line edit to the `dependencies` array.

## Integration Points

- **`main.py`**: Add the two-line `configure_langsmith()` setup at the very
  top, before importing `EmailSupportGraph`.
- **`src/agents/bedrock.py`** and **`src/utils/rag_utils.py`**: Both already
  call `load_dotenv()`. No change required, but the executor must verify
  that `main.py` runs `configure_langsmith()` **before** these modules are
  imported (they are reached transitively via `EmailSupportGraph`).
- **`src/nodes/*.py`**: Each node function gets a `@traceable` decorator.
  No change to function bodies, signatures, or return values.
- **`src/utils/gmail_utils.py`**: `get_most_recent_email` and
  `send_reply_email` get `@traceable` decorators with `run_type="tool"`.
- **`.env.example`**: Add `LANGSMITH_TRACING`, ensure
  `LANGSMITH_API_KEY` documented, add `LANGSMITH_PROJECT`,
  `LANGSMITH_ENDPOINT`, each with a one-line `#` comment.
- **`README.md`**: Add a "LangSmith setup" subsection under
  "Configure environment variables" or as its own top-level subsection,
  matching the existing emoji-headed style (e.g., "### Observability with
  LangSmith").
- **`langgraph.json`**: No change required. It already loads `.env`.

## Pedagogical Comment Contract

Comments must be added at the following load-bearing moments and **only**
these. Do not comment trivial lines (variable assignments, obvious returns,
etc.).

| Location | Comment must explain |
|---|---|
| `main.py` import-order block | Why `configure_langsmith()` runs **before** any `src.graph` / `src.agents` import — i.e., LangChain reads tracing env vars at module import time. |
| `src/observability/langsmith_setup.py` `configure_langsmith` body | What "tracing enabled" actually requires (both `LANGSMITH_TRACING=true` and a non-empty `LANGSMITH_API_KEY`). Why we set `LANGSMITH_PROJECT` default. |
| First `@traceable` usage in `src/nodes/email_listener.py` | One short comment: "@traceable wraps this node so it appears as its own span in the LangSmith trace tree." (Subsequent `@traceable` usages do **not** need to repeat this.) |
| `.env.example` LangSmith block | One `#` line per variable, explaining its purpose in plain English. |
| `README.md` "LangSmith setup" section | Full prose; written for a tutorial viewer who has never seen LangSmith. |

Comments anywhere else are at the executor's discretion but should be
sparing.
