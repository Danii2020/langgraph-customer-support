import os

_tracing_configured = False
_tracing_enabled = False


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
    global _tracing_configured, _tracing_enabled

    if _tracing_configured:
        return _tracing_enabled

    _tracing_configured = True

    # Both conditions must be true for tracing to be active:
    # LANGSMITH_TRACING must be the exact string "true" (case-insensitive),
    # AND LANGSMITH_API_KEY must be a non-empty string.
    tracing_flag = os.environ.get("LANGSMITH_TRACING", "").strip().lower()
    api_key = os.environ.get("LANGSMITH_API_KEY", "").strip()

    if tracing_flag != "true" or not api_key:
        _tracing_enabled = False
        return False

    # LANGSMITH_PROJECT controls which "bucket" in the LangSmith UI this
    # run lands in. Defaulting here avoids traces silently landing in the
    # generic "default" project, which makes it impossible to filter by
    # project in the dashboard.
    if not os.environ.get("LANGSMITH_PROJECT", "").strip():
        os.environ["LANGSMITH_PROJECT"] = "langgraph-gmail"

    if not os.environ.get("LANGSMITH_ENDPOINT", "").strip():
        os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"

    _tracing_enabled = True
    return True


def is_tracing_enabled() -> bool:
    """Return True iff LangSmith tracing is currently active for this process."""
    return _tracing_enabled
