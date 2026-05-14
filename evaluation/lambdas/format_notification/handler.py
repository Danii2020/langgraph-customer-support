"""
Builds the SNS notification body for the eval pipeline.

The state machine has two parallel branches (RAG + retrieval-only); the
default ASL output is `States.JsonToString($.parallel_results)` which
produces an unreadable JSON dump in the recipient's email. This Lambda
takes the same input and produces a plain-text summary with per-metric
scores aligned in fixed-width columns, plus a short "next steps" hint
keyed on which branch failed.

Input event shapes:

  Happy path (both branches completed, verdict may be PASS or FAIL):
    {
      "parallel_results": [
        {                                     # RAG branch terminal state
          "retrieve_and_generate_job_arn": "arn:...",
          "thresholds_subkey": "retrieve_and_generate",
          "verdict": {
            "passed": bool,
            "results": {
              "<metric>": {"score": float, "threshold": float, "passed": bool},
              ...
            },
            "failed_metrics": ["<metric>", ...]
          }
        },
        { ... }                               # retrieval branch (same shape)
      ]
    }

  Pre-completion failure path (Parallel state caught a branch error):
    {
      "error": { "Error": "...", "Cause": "..." }   # optionally with $.parallel_results too
    }

Output:
    {
      "subject": "Eval Pipeline: PASS (RAG + Retrieval)",
      "message": "<multi-line plain-text body>",
      "passed":  true | false
    }
"""
from typing import Any


# Display order of branches in the email body. Matches the order of
# `Branches` in the Parallel state's ASL, so parallel_results[0] is
# always RAG and parallel_results[1] is always retrieval-only.
_RAG_INDEX = 0
_RET_INDEX = 1

_BRANCH_TITLES = {
    "retrieve_and_generate": "Retrieve-and-Generate (5 generation metrics)",
    "retrieve_only":         "Retrieve-Only (2 retrieval metrics)",
}

_SEP = "=" * 64
_SUB = "-" * 64
_METRIC_COL_WIDTH = 22


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    parallel_results = event.get("parallel_results")
    error = event.get("error")

    if isinstance(parallel_results, list) and len(parallel_results) >= 2:
        return _format_completed(parallel_results[_RAG_INDEX], parallel_results[_RET_INDEX])

    return _format_pre_completion_error(error)


# ---------------------------------------------------------------------------
# Happy-ish path: both branches ran to completion
# ---------------------------------------------------------------------------

def _format_completed(rag_state: dict[str, Any], ret_state: dict[str, Any]) -> dict[str, Any]:
    rag_verdict = rag_state.get("verdict") or {}
    ret_verdict = ret_state.get("verdict") or {}

    rag_passed = bool(rag_verdict.get("passed"))
    ret_passed = bool(ret_verdict.get("passed"))
    overall = rag_passed and ret_passed

    rag_arn = rag_state.get("retrieve_and_generate_job_arn", "<unknown>")
    ret_arn = ret_state.get("retrieve_and_generate_job_arn", "<unknown>")

    subject = _build_subject(overall, rag_passed, ret_passed)
    message = _build_body(overall, rag_passed, ret_passed,
                          rag_verdict, ret_verdict, rag_arn, ret_arn)

    return {"subject": subject, "message": message, "passed": overall}


def _build_subject(overall: bool, rag_passed: bool, ret_passed: bool) -> str:
    if overall:
        return "Eval Pipeline: PASS (RAG + Retrieval)"
    parts = []
    parts.append("RAG passed" if rag_passed else "RAG failed")
    parts.append("Retrieval passed" if ret_passed else "Retrieval failed")
    return f"Eval Pipeline: FAIL ({', '.join(parts)})"


def _build_body(
    overall: bool,
    rag_passed: bool,
    ret_passed: bool,
    rag_verdict: dict[str, Any],
    ret_verdict: dict[str, Any],
    rag_arn: str,
    ret_arn: str,
) -> str:
    lines: list[str] = []
    lines.append(_SEP)
    lines.append(f"Eval Pipeline Verdict: {'PASS' if overall else 'FAIL'}")
    lines.append(_SEP)
    lines.append("")
    lines.append(f"  Retrieve-and-Generate:  {'PASS' if rag_passed else 'FAIL'}")
    lines.append(f"  Retrieve-Only:          {'PASS' if ret_passed else 'FAIL'}")
    lines.append("")
    lines.extend(_render_branch(
        title=_BRANCH_TITLES["retrieve_and_generate"],
        verdict=rag_verdict,
        job_arn=rag_arn,
    ))
    lines.append("")
    lines.extend(_render_branch(
        title=_BRANCH_TITLES["retrieve_only"],
        verdict=ret_verdict,
        job_arn=ret_arn,
    ))
    lines.append("")
    lines.append(_SEP)
    if overall:
        lines.append("All metrics above their thresholds. Safe to promote.")
    else:
        lines.append("Next steps:")
        if not rag_passed:
            lines.append("  - RAG metrics low -> generator/prompt issue. The retriever")
            lines.append("    may still be fine; check the retrieval branch's scores")
            lines.append("    to confirm.")
        if not ret_passed:
            lines.append("  - Retrieval metrics low -> retriever issue. Likely causes:")
            lines.append("    chunking strategy, embedding model, top-K, or missing")
            lines.append("    documents in the source S3.")
        if not rag_passed and not ret_passed:
            lines.append("  - Both branches failed: retrieval is the upstream signal;")
            lines.append("    fix that first, then re-check generation.")
    lines.append(_SEP)
    return "\n".join(lines)


def _render_branch(title: str, verdict: dict[str, Any], job_arn: str) -> list[str]:
    results = verdict.get("results") or {}
    failed = verdict.get("failed_metrics") or []
    branch_passed = bool(verdict.get("passed"))

    lines: list[str] = []
    lines.append(_SUB)
    lines.append(f"{title}  [{'PASS' if branch_passed else 'FAIL'}]")
    lines.append(_SUB)
    lines.append(f"  {'Metric':<{_METRIC_COL_WIDTH}}  Score   Threshold   Result")

    if not results:
        lines.append("  (no metric scores -- branch did not produce a verdict)")
    else:
        for metric in sorted(results.keys()):
            info = results[metric] or {}
            score = _safe_float(info.get("score"))
            threshold = _safe_float(info.get("threshold"))
            passed = bool(info.get("passed"))
            marker = "PASS" if passed else "FAIL  <-- below threshold"
            lines.append(
                f"  {metric:<{_METRIC_COL_WIDTH}}  {score:5.3f}   >= {threshold:5.3f}   {marker}"
            )

    if failed:
        lines.append("")
        lines.append(f"  Failed metrics: {', '.join(failed)}")

    lines.append("")
    lines.append(f"  Job ARN: {job_arn}")
    return lines


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Pre-completion failure: Parallel never produced parallel_results
# ---------------------------------------------------------------------------

def _format_pre_completion_error(error: Any) -> dict[str, Any]:
    err_text = _extract_error_text(error)

    lines: list[str] = []
    lines.append(_SEP)
    lines.append("Eval Pipeline Verdict: FAIL (pipeline error)")
    lines.append(_SEP)
    lines.append("")
    lines.append("The pipeline failed before either branch produced metric")
    lines.append("scores. No PASS/FAIL verdict was computed.")
    lines.append("")
    if err_text:
        lines.append(f"Error: {err_text}")
        lines.append("")
    lines.append("Check the Step Functions execution for details.")
    lines.append(_SEP)

    return {
        "subject": "Eval Pipeline: FAIL (pipeline error)",
        "message": "\n".join(lines),
        "passed": False,
    }


def _extract_error_text(error: Any) -> str:
    """Pull a one-line error description out of a Step Functions Catch payload."""
    if error is None:
        return ""
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        return (
            error.get("Cause")
            or error.get("Error")
            or error.get("errorMessage")
            or str(error)
        )
    return str(error)
