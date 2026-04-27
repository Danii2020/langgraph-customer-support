"""
Unit tests for evaluation/lambdas/check_eval_status/handler.py
"""
import importlib.util
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

_HANDLER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "lambdas", "check_eval_status", "handler.py")
)
_spec = importlib.util.spec_from_file_location("check_eval_status_handler", _HANDLER_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["check_eval_status_handler"] = _mod
_spec.loader.exec_module(_mod)

handler = _mod.handler
TERMINAL_STATUSES = _mod.TERMINAL_STATUSES

JOB_ARN = "arn:aws:bedrock:us-east-2:123456789012:evaluation-job/job-abc123"


def make_mock_bedrock(status: str) -> MagicMock:
    client = MagicMock()
    client.get_evaluation_job.return_value = {"status": status}
    return client


# ---------------------------------------------------------------------------
# IN_PROGRESS status
# ---------------------------------------------------------------------------

class TestCheckEvalStatusInProgress:

    def test_returns_in_progress_with_completed_false(self):
        mock_bedrock = make_mock_bedrock("IN_PROGRESS")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "IN_PROGRESS"
        assert result["completed"] is False
        assert result["job_arn"] == JOB_ARN

    def test_calls_get_evaluation_job_with_correct_arn(self):
        mock_bedrock = make_mock_bedrock("IN_PROGRESS")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            handler({"job_arn": JOB_ARN}, None)

        mock_bedrock.get_evaluation_job.assert_called_once_with(jobIdentifier=JOB_ARN)


# ---------------------------------------------------------------------------
# COMPLETED status
# ---------------------------------------------------------------------------

class TestCheckEvalStatusCompleted:

    def test_returns_completed_with_completed_true(self):
        mock_bedrock = make_mock_bedrock("COMPLETED")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "COMPLETED"
        assert result["completed"] is True

    def test_result_contains_job_arn(self):
        mock_bedrock = make_mock_bedrock("COMPLETED")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["job_arn"] == JOB_ARN


# ---------------------------------------------------------------------------
# FAILED status
# ---------------------------------------------------------------------------

class TestCheckEvalStatusFailed:

    def test_returns_failed_with_completed_true(self):
        mock_bedrock = make_mock_bedrock("FAILED")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "FAILED"
        assert result["completed"] is True

    def test_failed_is_in_terminal_statuses(self):
        assert "FAILED" in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# STOPPING and STOPPED statuses
# ---------------------------------------------------------------------------

class TestCheckEvalStatusStopping:

    def test_stopping_is_not_completed(self):
        mock_bedrock = make_mock_bedrock("STOPPING")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "STOPPING"
        assert result["completed"] is False

    def test_stopped_is_completed(self):
        mock_bedrock = make_mock_bedrock("STOPPED")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "STOPPED"
        assert result["completed"] is True


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestCheckEvalStatusErrors:

    def test_raises_key_error_when_job_arn_missing(self):
        with pytest.raises(KeyError, match="job_arn"):
            handler({}, None)

    def test_raises_runtime_error_on_api_failure(self):
        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.side_effect = Exception("AccessDeniedException")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            with pytest.raises(RuntimeError, match="Failed to get evaluation job status"):
                handler({"job_arn": JOB_ARN}, None)

    def test_raises_value_error_when_status_missing_in_response(self):
        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.return_value = {}  # no status field
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            with pytest.raises(ValueError, match="did not contain 'status'"):
                handler({"job_arn": JOB_ARN}, None)

    def test_raises_key_error_when_job_arn_is_none(self):
        with pytest.raises(KeyError, match="job_arn"):
            handler({"job_arn": None}, None)


# ---------------------------------------------------------------------------
# Terminal statuses constant
# ---------------------------------------------------------------------------

class TestTerminalStatuses:

    def test_completed_is_terminal(self):
        assert "COMPLETED" in TERMINAL_STATUSES

    def test_failed_is_terminal(self):
        assert "FAILED" in TERMINAL_STATUSES

    def test_stopped_is_terminal(self):
        assert "STOPPED" in TERMINAL_STATUSES

    def test_in_progress_is_not_terminal(self):
        assert "IN_PROGRESS" not in TERMINAL_STATUSES

    def test_stopping_is_not_terminal(self):
        assert "STOPPING" not in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Bedrock returns PascalCase status values; ensure we still detect terminal
# states regardless of casing.
# ---------------------------------------------------------------------------

class TestCheckEvalStatusBedrockPascalCase:

    def test_pascal_case_completed_is_completed(self):
        mock_bedrock = make_mock_bedrock("Completed")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "Completed"
        assert result["completed"] is True

    def test_pascal_case_in_progress_is_not_completed(self):
        mock_bedrock = make_mock_bedrock("InProgress")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "InProgress"
        assert result["completed"] is False

    def test_pascal_case_failed_is_completed(self):
        mock_bedrock = make_mock_bedrock("Failed")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "Failed"
        assert result["completed"] is True

    def test_pascal_case_stopped_is_completed(self):
        mock_bedrock = make_mock_bedrock("Stopped")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "Stopped"
        assert result["completed"] is True

    def test_pascal_case_stopping_is_not_completed(self):
        mock_bedrock = make_mock_bedrock("Stopping")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler({"job_arn": JOB_ARN}, None)

        assert result["status"] == "Stopping"
        assert result["completed"] is False
