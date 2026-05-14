"""
Unit tests for evaluation/lambdas/format_notification/handler.py
"""
import importlib.util
import os
import sys

import pytest


_HANDLER_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "lambdas",
        "format_notification",
        "handler.py",
    )
)
_spec = importlib.util.spec_from_file_location(
    "format_notification_handler", _HANDLER_PATH
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["format_notification_handler"] = _mod
_spec.loader.exec_module(_mod)

handler = _mod.handler


# ---------------------------------------------------------------------------
# Fixtures: synthetic verdicts / branch terminal states
# ---------------------------------------------------------------------------

RAG_ARN = "arn:aws:bedrock:us-east-1:123456789012:evaluation-job/rag-abc"
RET_ARN = "arn:aws:bedrock:us-east-1:123456789012:evaluation-job/ret-xyz"


def _rag_verdict(passed: bool = True) -> dict:
    return {
        "passed": passed,
        "results": {
            "faithfulness":      {"score": 0.88, "threshold": 0.82, "passed": True},
            "correctness":       {"score": 0.81, "threshold": 0.78, "passed": True},
            "completeness":      {"score": 0.74, "threshold": 0.72, "passed": True},
            "helpfulness":       {"score": 0.75, "threshold": 0.73, "passed": True},
            "logical_coherence": {"score": 0.80, "threshold": 0.78, "passed": True},
        },
        "failed_metrics": [] if passed else ["faithfulness"],
    }


def _ret_verdict(passed: bool = True) -> dict:
    return {
        "passed": passed,
        "results": {
            "context_relevance": {"score": 0.85, "threshold": 0.70, "passed": True},
            "context_coverage":  {"score": 0.68 if passed else 0.55,
                                  "threshold": 0.65,
                                  "passed": passed},
        },
        "failed_metrics": [] if passed else ["context_coverage"],
    }


def _branch_state(verdict: dict, arn: str, subkey: str) -> dict:
    return {
        "retrieve_and_generate_job_arn": arn,
        "thresholds_subkey": subkey,
        "thresholds_s3_uri": "s3://eval-bucket/baselines/x.json",
        "verdict": verdict,
    }


def _event(rag_verdict: dict, ret_verdict: dict) -> dict:
    return {
        "parallel_results": [
            _branch_state(rag_verdict, RAG_ARN, "retrieve_and_generate"),
            _branch_state(ret_verdict, RET_ARN, "retrieve_only"),
        ]
    }


# ---------------------------------------------------------------------------
# Happy path: both branches PASS
# ---------------------------------------------------------------------------

class TestBothPass:

    def test_subject_indicates_overall_pass(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(True)), None)
        assert out["subject"] == "Eval Pipeline: PASS (RAG + Retrieval)"
        assert out["passed"] is True

    def test_message_includes_both_branch_summaries(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(True)), None)
        msg = out["message"]
        assert "Retrieve-and-Generate" in msg
        assert "Retrieve-Only" in msg
        assert "Retrieve-and-Generate:  PASS" in msg
        assert "Retrieve-Only:          PASS" in msg

    def test_message_includes_all_metrics(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(True)), None)
        msg = out["message"]
        for metric in (
            "faithfulness", "correctness", "completeness", "helpfulness",
            "logical_coherence", "context_relevance", "context_coverage",
        ):
            assert metric in msg

    def test_message_includes_both_job_arns(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(True)), None)
        assert RAG_ARN in out["message"]
        assert RET_ARN in out["message"]

    def test_pass_message_has_promotion_note(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(True)), None)
        assert "Safe to promote" in out["message"]


# ---------------------------------------------------------------------------
# Mixed verdicts
# ---------------------------------------------------------------------------

class TestMixedVerdicts:

    def test_rag_pass_retrieval_fail_subject(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(False)), None)
        assert out["subject"] == "Eval Pipeline: FAIL (RAG passed, Retrieval failed)"
        assert out["passed"] is False

    def test_rag_fail_retrieval_pass_subject(self):
        out = handler(_event(_rag_verdict(False), _ret_verdict(True)), None)
        assert out["subject"] == "Eval Pipeline: FAIL (RAG failed, Retrieval passed)"
        assert out["passed"] is False

    def test_both_fail_subject(self):
        out = handler(_event(_rag_verdict(False), _ret_verdict(False)), None)
        assert out["subject"] == "Eval Pipeline: FAIL (RAG failed, Retrieval failed)"
        assert out["passed"] is False

    def test_failure_message_includes_next_steps(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(False)), None)
        assert "Next steps:" in out["message"]
        assert "Retrieval metrics low" in out["message"]
        # Should NOT include the RAG diagnosis since RAG passed.
        assert "RAG metrics low" not in out["message"]

    def test_failure_message_marks_failing_metric(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(False)), None)
        msg = out["message"]
        # context_coverage line should show FAIL with the marker.
        assert "context_coverage" in msg
        assert "below threshold" in msg

    def test_both_fail_includes_combined_advice(self):
        out = handler(_event(_rag_verdict(False), _ret_verdict(False)), None)
        msg = out["message"]
        assert "RAG metrics low" in msg
        assert "Retrieval metrics low" in msg
        assert "retrieval is the upstream signal" in msg


# ---------------------------------------------------------------------------
# Pre-completion failure (Parallel state caught an error)
# ---------------------------------------------------------------------------

class TestPreCompletionError:

    def test_missing_parallel_results_uses_error_path(self):
        event = {"error": {"Error": "States.TaskFailed", "Cause": "Bedrock throttled"}}
        out = handler(event, None)
        assert "FAIL" in out["subject"]
        assert "pipeline error" in out["subject"]
        assert out["passed"] is False

    def test_error_message_surfaces_cause(self):
        event = {"error": {"Error": "States.TaskFailed", "Cause": "AccessDenied on KB"}}
        out = handler(event, None)
        assert "AccessDenied on KB" in out["message"]

    def test_empty_event(self):
        """No parallel_results, no error — should still produce a sane email."""
        out = handler({}, None)
        assert "FAIL" in out["subject"]
        assert "Check the Step Functions execution" in out["message"]

    def test_string_error(self):
        """Some Catch payloads stringify the error rather than emit a dict."""
        out = handler({"error": "RagPollingTimeout"}, None)
        assert "RagPollingTimeout" in out["message"]


# ---------------------------------------------------------------------------
# Defensive parsing: malformed verdicts
# ---------------------------------------------------------------------------

class TestDefensiveParsing:

    def test_missing_verdict_field(self):
        event = {
            "parallel_results": [
                {"retrieve_and_generate_job_arn": RAG_ARN, "thresholds_subkey": "retrieve_and_generate"},
                _branch_state(_ret_verdict(True), RET_ARN, "retrieve_only"),
            ]
        }
        out = handler(event, None)
        # RAG branch has no verdict so it's treated as FAIL; overall must FAIL.
        assert out["passed"] is False
        assert "no metric scores" in out["message"]

    def test_non_numeric_score(self):
        bad = _rag_verdict(True)
        bad["results"]["faithfulness"]["score"] = "n/a"
        event = _event(bad, _ret_verdict(True))
        out = handler(event, None)
        # The Lambda must not crash; it coerces unparseable scores to 0.000.
        assert "faithfulness" in out["message"]
        assert "0.000" in out["message"]

    def test_only_one_branch_in_parallel_results(self):
        """If only one entry, fall back to pre-completion error."""
        event = {"parallel_results": [_branch_state(_rag_verdict(True), RAG_ARN, "retrieve_and_generate")]}
        out = handler(event, None)
        assert out["passed"] is False
        assert "pipeline error" in out["subject"]


# ---------------------------------------------------------------------------
# Output shape contract
# ---------------------------------------------------------------------------

class TestOutputContract:

    def test_returns_three_required_keys(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(True)), None)
        assert set(out.keys()) == {"subject", "message", "passed"}

    def test_passed_is_strict_bool(self):
        out = handler(_event(_rag_verdict(True), _ret_verdict(True)), None)
        assert isinstance(out["passed"], bool)
        out2 = handler(_event(_rag_verdict(False), _ret_verdict(True)), None)
        assert isinstance(out2["passed"], bool)
        assert out2["passed"] is False

    def test_message_does_not_contain_json_braces(self):
        """A sanity check that we're not dumping raw JSON."""
        out = handler(_event(_rag_verdict(True), _ret_verdict(True)), None)
        # Body uses fixed-width formatting, not JSON, so curly braces should
        # only appear in metric labels (none of ours have them).
        assert "{" not in out["message"]
        assert "}" not in out["message"]
