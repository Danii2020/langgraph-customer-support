import os
import pytest
import src.observability.langsmith_setup as langsmith_setup_mod


def _reset_module_state():
    """Reset the module-level idempotency guards before each test."""
    langsmith_setup_mod._tracing_configured = False
    langsmith_setup_mod._tracing_enabled = False


def test_configure_langsmith_returns_false_when_api_key_missing(monkeypatch):
    _reset_module_state()
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    result = langsmith_setup_mod.configure_langsmith()

    assert result is False
    assert langsmith_setup_mod.is_tracing_enabled() is False


def test_configure_langsmith_returns_true_and_sets_project_default(monkeypatch):
    _reset_module_state()
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_testkey")
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)

    result = langsmith_setup_mod.configure_langsmith()

    assert result is True
    assert os.environ["LANGSMITH_PROJECT"] == "langgraph-gmail"


def test_configure_langsmith_is_idempotent(monkeypatch):
    _reset_module_state()
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_testkey")
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)

    first = langsmith_setup_mod.configure_langsmith()
    second = langsmith_setup_mod.configure_langsmith()

    assert first == second
    assert second is True
