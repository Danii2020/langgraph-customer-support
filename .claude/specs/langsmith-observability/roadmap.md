# Roadmap: LangSmith Observability

## Implementation Phases

### Phase 1: Foundation — Observability module and env wiring
**Goal**: Stand up the `src/observability/` package and the
`configure_langsmith()` entry point with full graceful-degradation
behavior. After this phase, the app still works exactly as before; nothing
is traced yet, but the plumbing exists.

**Dependencies**: None.
**Estimated complexity**: Low.

1. Create directory `src/observability/`.
2. Create `src/observability/langsmith_setup.py` implementing
   `configure_langsmith() -> bool` and `is_tracing_enabled() -> bool`
   per `contract.md`. Add the load-bearing comments mandated in the
   "Pedagogical Comment Contract".
3. Create `src/observability/__init__.py` that re-exports
   `configure_langsmith`, `is_tracing_enabled`, and `traceable` (directly
   from `langsmith`). `langsmith` is a hard transitive dep via
   `langchain-core`, so no import fallback is needed.
4. Update `pyproject.toml` `dependencies` array to add
   `"langsmith>=0.3.45"` explicitly (next to the existing `langchain` /
   `langgraph` entries) for resolver clarity.
5. Smoke-check: `python -c "from src.observability import configure_langsmith; print(configure_langsmith())"`
   should print `True` or `False` based on the current `.env` contents and
   never raise.

### Phase 2: Core Logic — Wire `configure_langsmith()` into the entry point
**Goal**: Make the env-var-based auto-tracing actually fire on real graph
runs. After this phase, with valid creds, `python main.py` produces a
LangSmith run with auto-traced LangChain/LangGraph internals visible.

**Dependencies**: Phase 1.
**Estimated complexity**: Low.

1. Modify `main.py`:
   - Add `from src.observability import configure_langsmith` and call
     `configure_langsmith()` **at the very top of the file**, before the
     existing `from src.graph.email_graph import EmailSupportGraph` and
     `from src.state import Email` imports.
   - Add the explanatory comment specified in the Pedagogical Comment
     Contract about import order.
2. Manually verify with the project's current `.env` (which already has
   `LANGSMITH_API_KEY`) that `python main.py` runs a graph and that a run
   appears in the LangSmith UI under the project named by
   `LANGSMITH_PROJECT` (default `langgraph-gmail` after this phase).
3. Manually verify the off-path: temporarily comment `LANGSMITH_API_KEY` in
   `.env` and confirm `python main.py` still runs and exits cleanly.

### Phase 3: Integration — Decorate nodes and Gmail I/O
**Goal**: Add `@traceable` decorators to the seven targeted functions so
the trace tree shows pretty, named spans for nodes and Gmail I/O instead
of generic `RunnableLambda` entries.

**Dependencies**: Phase 2.
**Estimated complexity**: Medium (touches 5 files).

1. In `src/nodes/email_listener.py`, decorate `email_listener_node` with
   `@traceable(name="node.load_email", run_type="chain")`. Add the single
   comment mandated by the Pedagogical Comment Contract.
2. In `src/nodes/email_categorizer.py`, decorate `email_categorizer_node`
   with `@traceable(name="node.categorize_email", run_type="chain")`.
3. In `src/nodes/email_writer.py`, decorate both `query_or_email_node`
   (`name="node.query_or_email"`) and `email_writer_with_context_node`
   (`name="node.write_email_with_context"`) with `run_type="chain"`.
4. In `src/nodes/email_sender.py`, decorate `email_sender_node` with
   `@traceable(name="node.send_email", run_type="chain")`.
5. In `src/utils/gmail_utils.py`, decorate `get_most_recent_email` with
   `@traceable(name="gmail.fetch_most_recent", run_type="tool")` and
   `send_reply_email` with `@traceable(name="gmail.send_reply", run_type="tool")`.
6. Import `traceable` from `src.observability` (NOT directly from
   `langsmith`) so the graceful-degradation pass-through path is used when
   `langsmith` is unavailable.
7. Verify a full run in LangSmith now shows the seven named spans plus the
   underlying LLM and tool calls.

### Phase 4: Developer surface — `.env.example` and README
**Goal**: Make the integration discoverable and usable for a tutorial
viewer who has never used LangSmith.

**Dependencies**: Phase 3.
**Estimated complexity**: Low.

1. Update `/Users/danielerazo/python/langgraph-gmail/.env.example`:
   - Keep existing variables intact.
   - Add a `# --- LangSmith observability ---` block with:
     - `LANGSMITH_TRACING=true`
     - `LANGSMITH_API_KEY=YOUR-KEY` (already present; group it under the new block and add a one-line comment)
     - `LANGSMITH_PROJECT=langgraph-gmail`
     - `LANGSMITH_ENDPOINT=https://api.smith.langchain.com`
   - Each variable gets one `#`-prefixed plain-English comment line above it.
2. Update `/Users/danielerazo/python/langgraph-gmail/README.md`:
   - Add a new subsection (matching the existing `### 🧰 Prerequisites` /
     `### ⚙️ Installation` emoji-headed style) titled
     `### 🔭 Observability with LangSmith`, placed after the "Run via
     LangSmith Studio (LangGraph Studio)" block since both topics are
     related.
   - Section must contain, in order:
     1. One-paragraph "what is LangSmith" explainer.
     2. "Get an API key" step pointing to `https://smith.langchain.com/`.
     3. The four env vars with a fenced bash block, mirroring the existing
        AWS env-var block for consistency.
     4. "Run the graph" — pointer back to `python main.py`.
     5. "What you should see" — bullet list naming the seven spans
        (`node.load_email`, etc.) and the LLM / retriever child runs.
     6. "Turning it off" — note that unsetting `LANGSMITH_API_KEY` or
        setting `LANGSMITH_TRACING=false` disables tracing without code
        changes.
   - Tone matches the existing README: short, action-oriented, fenced
     code blocks, light emoji.

### Phase 5: Testing & Validation — Smoke test
**Goal**: Lock the graceful-degradation guarantee and the
`configure_langsmith()` contract behind an automated test, plus a
documented manual smoke test for tracing.

**Dependencies**: Phase 4.
**Estimated complexity**: Low.

1. Create `tests/test_observability/test_langsmith_setup.py` with:
   - `test_configure_langsmith_returns_false_when_api_key_missing` —
     monkeypatch `LANGSMITH_API_KEY` to empty string; assert returns `False`
     and `is_tracing_enabled()` returns `False`.
   - `test_configure_langsmith_returns_true_and_sets_project_default` —
     both vars set, `LANGSMITH_PROJECT` unset; assert `True` and
     `os.environ["LANGSMITH_PROJECT"] == "langgraph-gmail"`.
   - `test_configure_langsmith_is_idempotent` — call twice, assert no
     exception and same return value.
2. Document a manual smoke test in `roadmap.md` (this file, see below)
   that the tutorial walks through on camera:
   - Set the four env vars.
   - Run `python main.py`.
   - Open LangSmith UI, confirm a run named after the graph entry exists
     in the `langgraph-gmail` project, and the seven spans are present.
3. Run the full pytest suite to confirm no regression.

## Manual Smoke Test (for the YouTube recording)

1. Visit `https://smith.langchain.com/` and create an API key.
2. Edit `.env`:
   ```
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY=lsv2_pt_...
   LANGSMITH_PROJECT=langgraph-gmail
   LANGSMITH_ENDPOINT=https://api.smith.langchain.com
   ```
3. Send a test email to the configured Gmail account.
4. Run `python main.py`.
5. In the LangSmith UI, open the `langgraph-gmail` project. The newest run
   should show the seven named spans, the Bedrock LLM calls with full
   prompt/response, and the retriever tool call when applicable.
6. Comment out `LANGSMITH_API_KEY` in `.env`, re-run `python main.py`,
   confirm it completes with no errors and no new run appears in the UI.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Env vars read before `configure_langsmith()` runs | Med | High (no traces) | Place `configure_langsmith()` as the **first** non-stdlib import in `main.py`; cover with the comment specified in the contract; document in module docstring. |
| Real LangSmith API key already present in committed `.env` | High | High (secret leak) | Spec explicitly notes `.env` should not be committed; `.gitignore` already excludes it; tutorial flow uses `.env.example` with placeholder. The executor should NOT touch the real `.env`. |
| Tracing introduces latency on hot path | Low | Low | `langsmith` batches and ships in a background thread; G8 mandates near-zero overhead when off. |
| LangSmith UI changes UI labels (run names) | Low | Low | We control display via explicit `name=` strings, so renames in upstream LangChain runtime don't affect our nodes. |
| Studio (`langgraph dev`) double-traces or ignores env | Low | Low | `langgraph.json` already declares `env: ".env"`; manually verify in Phase 2. |
| `requires-python = ">=3.13"` mismatch with reader's local env | Med | Low | Already a project-wide constraint; README's installation section already covers it. |

## File Change Map

- `src/observability/__init__.py` — CREATE — re-exports `configure_langsmith`, `is_tracing_enabled`, and `traceable` (directly from `langsmith`).
- `src/observability/langsmith_setup.py` — CREATE — implements `configure_langsmith()` and `is_tracing_enabled()` per contract; contains the load-bearing comments.
- `main.py` — MODIFY — add the import-order block calling `configure_langsmith()` before any `src.graph` / `src.state` import.
- `src/nodes/email_listener.py` — MODIFY — `@traceable` decorator on `email_listener_node`; one comment.
- `src/nodes/email_categorizer.py` — MODIFY — `@traceable` decorator on `email_categorizer_node`.
- `src/nodes/email_writer.py` — MODIFY — `@traceable` decorators on `query_or_email_node` and `email_writer_with_context_node`.
- `src/nodes/email_sender.py` — MODIFY — `@traceable` decorator on `email_sender_node`.
- `src/utils/gmail_utils.py` — MODIFY — `@traceable` decorators on `get_most_recent_email` and `send_reply_email`.
- `pyproject.toml` — MODIFY — add `"langsmith>=0.3.45"` to `dependencies`.
- `.env.example` — MODIFY — add `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`; keep `LANGSMITH_API_KEY`; group under a `# --- LangSmith observability ---` header with one-line comments.
- `README.md` — MODIFY — add `### 🔭 Observability with LangSmith` subsection per Phase 4 step 2.
- `tests/test_observability/__init__.py` — CREATE — empty package marker.
- `tests/test_observability/test_langsmith_setup.py` — CREATE — five unit tests per Phase 5 step 1.

Files explicitly NOT modified:
- `src/graph/email_graph.py` — no change; LangGraph auto-traces nodes once `LANGSMITH_TRACING=true`.
- `src/agents/*.py` — no change; LangChain auto-traces LLM and structured-output chains.
- `src/utils/rag_utils.py` — no change; the retriever tool is auto-traced as a `tool` run.
- `src/state.py`, `src/structured_outputs.py`, `src/prompts/*` — no change.
- `langgraph.json` — no change; already loads `.env`.
- `.env` — no change (executor MUST NOT modify the developer's real `.env`).
