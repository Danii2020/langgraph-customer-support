# Intent: LangSmith Observability

## Problem Statement
The `langgraph-gmail` customer-support workflow runs as an opaque pipeline:
emails arrive, an LLM categorizes them, a RAG step optionally pulls Knowledge
Base context, and another LLM drafts and sends a reply. Today, when something
misbehaves (wrong category, hallucinated reply, slow Bedrock call, broken
retriever), the only signal is a `print(...)` line or a stack trace. There is
no per-run timeline, no view of token usage, no view of the prompt that
actually reached the model, and no way to compare runs over time.

This feature plugs LangSmith into the existing LangGraph pipeline so that
every graph execution produces a rich, browsable trace in the LangSmith UI:
node-by-node timing, full prompt/response payloads, tool calls (the
`AmazonKnowledgeBasesRetriever` retriever tool), token counts, and errors.

## Audience
1. **Tutorial viewers** following the YouTube companion video for this
   project. They are LangGraph learners; the integration must be small,
   explicit, and the README must walk them through it end to end.
2. **Project maintainers** (the repo owner and future contributors) who need
   real production-style observability when iterating on prompts, swapping
   Bedrock models, or debugging Gmail-specific edge cases.

## Goals
1. Auto-trace every node and every LLM/tool call in the existing
   `EmailSupportGraph` to LangSmith with zero changes to graph topology.
2. Make the LangSmith project name configurable via env var so the same
   codebase can write to `langgraph-gmail-dev`, `langgraph-gmail-prod`, etc.
3. Decorate the non-LangChain seams (Gmail fetch, Gmail send, email parsing)
   with `@traceable` so the Gmail I/O also shows up in the trace tree, not
   just the LLM portion.
4. Fail open: if `LANGSMITH_API_KEY` is unset or `LANGSMITH_TRACING` is
   `false`, the app must run end to end with no behavioral difference and no
   crash, no warning spam, and no extra latency.
5. Update the developer surface (`.env.example`, `README.md`) so a tutorial
   viewer can clone, set three env vars, and immediately see traces.
6. Keep the implementation pedagogically clean: comments must explain the
   load-bearing moments (env-var-before-import ordering, what `@traceable`
   does, what `LANGSMITH_PROJECT` controls in the UI) without
   commenting trivial lines.

## Success Criteria
- [ ] Running `python main.py` with valid LangSmith env vars produces a run
      in the configured LangSmith project that shows nodes `load_email`,
      `categorize_email`, `query_or_email`, `retrieve`, `write_email_with_context`,
      `send_email` in order.
- [ ] The trace shows the full prompt sent to Bedrock and the structured
      output returned for both the categorizer and the writer.
- [ ] The retriever tool call (`retrieve_prodcuts_and_services_information`)
      appears as a child run with its query and retrieved documents.
- [ ] Gmail I/O (`get_most_recent_email`, `send_reply_email`) appear as
      `@traceable`-wrapped runs in the same trace tree.
- [ ] Running `python main.py` with `LANGSMITH_API_KEY` unset (or
      `LANGSMITH_TRACING=false`) completes the pipeline with no exception
      raised by LangSmith code paths.
- [ ] `.env.example` lists all four LangSmith variables with safe placeholder
      values and short inline comments.
- [ ] `README.md` contains a "LangSmith setup" section that a viewer can
      follow without prior LangSmith knowledge.
- [ ] At least one smoke test (or a documented manual smoke-test recipe in
      the README / spec) verifies traces appear for one full graph run.

## Non-Goals
- Custom LangSmith dashboards, alerts, or monitors.
- LangSmith **evaluations** / datasets / regression harnesses (the existing
  `evaluation/` AWS-SAM stack is out of scope; this spec only adds tracing).
- Replacing or removing the existing OpenTelemetry env vars
  (`OTEL_TRACES_EXPORTER`, `OTEL_METRICS_EXPORTER`) currently in `.env`.
- A LangSmith `Client(...)` wrapper for programmatic run inspection beyond
  what is needed for graceful-degradation checks.
- Self-hosted LangSmith deployment guides; we assume the public
  `https://api.smith.langchain.com` endpoint by default.
- Changing prompts, models, or graph behavior in any way.

## Constraints
- **Compatibility**: Must work with `langgraph==0.4.8`, `langchain==0.3.25`,
  `langchain-aws==0.2.28`, `langchain-core==0.3.68`, `langsmith==0.3.45`
  (already pinned in `requirements.txt`). No version bumps unless required
  for a documented bug fix.
- **Python**: `>=3.13` per `pyproject.toml`.
- **Env loading**: The project already uses `python-dotenv` and calls
  `load_dotenv()` inside `src/agents/bedrock.py` and `src/utils/rag_utils.py`.
  LangSmith env vars must be visible **before** any LangChain or LangGraph
  module is imported, otherwise tracing instrumentation does not register.
- **Secret hygiene**: The repo's `.env` file currently contains a real
  LangSmith key committed to the working tree (visible in
  `/Users/danielerazo/python/langgraph-gmail/.env`). The spec must not
  encourage committing real keys; `.env.example` is the only file that ships
  values, and only with placeholders.
- **No new heavyweight deps**: `langsmith` is already a transitive dependency
  via `langchain-core`; no new top-level package is required for the basic
  integration. (We may explicitly list it in `pyproject.toml` for clarity.)
- **Graceful degradation**: With `LANGSMITH_API_KEY` unset, the app and the
  `langgraph dev` Studio flow must both still work.
- **Tutorial-first ergonomics**: Every config knob must be settable through
  `.env` only. No code edits required to switch projects.

## Prior Art
- Existing `.env` in this repo already declares `LANGSMITH_API_KEY` and
  `OTEL_*` exporters, indicating the maintainer intends some form of
  tracing — this spec finishes that work and turns it into a documented,
  graceful, branded LangSmith integration.
- `langgraph.json` already references `.env`, so the LangGraph CLI dev server
  (`langgraph dev`) will inherit any new LangSmith vars automatically.
- `README.md` already mentions "LangSmith Studio (LangGraph Studio)" in the
  Usage section, which gives a natural anchor for the new "LangSmith setup"
  section.
- Canonical LangSmith env-var-based tracing pattern as documented for
  `langsmith>=0.3.x`: setting `LANGSMITH_TRACING=true` plus
  `LANGSMITH_API_KEY` is sufficient for `langchain` and `langgraph` runs to
  auto-export traces; `@traceable` from `langsmith` decorates arbitrary
  Python functions that should appear in the same trace tree.
