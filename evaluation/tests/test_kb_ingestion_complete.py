"""
Unit tests for evaluation/lambdas/kb_ingestion_complete/handler.py
"""
import base64
import gzip
import importlib.util
import json
import os
import sys

import pytest
from unittest.mock import MagicMock, patch


_HANDLER_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "lambdas",
        "kb_ingestion_complete",
        "handler.py",
    )
)
_spec = importlib.util.spec_from_file_location(
    "kb_ingestion_complete_handler", _HANDLER_PATH
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["kb_ingestion_complete_handler"] = _mod
_spec.loader.exec_module(_mod)

handler = _mod.handler


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

STATE_MACHINE_ARN = "arn:aws:states:us-east-1:123456789012:stateMachine:rag-eval-pipeline-eval-pipeline"
EVAL_BUCKET = "rag-eval-pipeline-eval-123-us-east-1"
RESULTS_BUCKET = "rag-eval-pipeline-eval-results-123-us-east-1"
KB_ID = "ABCDEF1234"
KB_ARN = f"arn:aws:bedrock:us-east-1:123456789012:knowledge-base/{KB_ID}"

EXPECTED_INPUT = {
    "rag_dataset_s3_uri": f"s3://{EVAL_BUCKET}/datasets/rag_eval.jsonl",
    "rag_output_s3_uri": f"s3://{RESULTS_BUCKET}/results/rag/",
    "rag_thresholds_s3_uri": f"s3://{EVAL_BUCKET}/baselines/thresholds.json",
    "retrieval_dataset_s3_uri": f"s3://{EVAL_BUCKET}/datasets/retrieval_eval.jsonl",
    "retrieval_output_s3_uri": f"s3://{RESULTS_BUCKET}/results/retrieval/",
    "retrieval_thresholds_s3_uri": f"s3://{EVAL_BUCKET}/baselines/retrieval_thresholds.json",
    "prompt_version": "",
}


def _make_log_record(status: str, kb_arn: str = KB_ARN) -> dict:
    """Build one Bedrock KB ingestion log record (the per-event payload)."""
    return {
        "event_timestamp": 1730000000000,
        "event": {
            "ingestion_job_id": "job-abc",
            "data_source_id": "ds-xyz",
            "ingestion_job_status": status,
            "knowledge_base_arn": kb_arn,
            "resource_statistics": {
                "number_of_resources_updated": 0,
                "number_of_resources_ingested": 2,
                "number_of_resources_failed": 0,
            },
        },
        "event_version": "1.0",
        "event_type": "StartIngestionJob.StatusChanged",
        "level": "INFO",
    }


def _make_cwl_event(messages: list[str]) -> dict:
    """Build a synthetic CloudWatch Logs subscription-filter event payload."""
    payload = {
        "messageType": "DATA_MESSAGE",
        "owner": "123456789012",
        "logGroup": "/aws/vendedlogs/bedrock/knowledge-base/rag-eval-pipeline",
        "logStream": "stream-1",
        "subscriptionFilters": ["rag-eval-pipeline-kb-ingestion-complete"],
        "logEvents": [
            {"id": f"id-{i}", "timestamp": 1730000000000 + i, "message": m}
            for i, m in enumerate(messages)
        ],
    }
    compressed = gzip.compress(json.dumps(payload).encode("utf-8"))
    return {"awslogs": {"data": base64.b64encode(compressed).decode("utf-8")}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Set the env vars the Lambda reads from os.environ."""
    monkeypatch.setenv("STATE_MACHINE_ARN", STATE_MACHINE_ARN)
    monkeypatch.setenv("EVAL_BUCKET_NAME", EVAL_BUCKET)
    monkeypatch.setenv("RESULTS_BUCKET_NAME", RESULTS_BUCKET)
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", KB_ID)
    monkeypatch.setenv("AWS_REGION", "us-east-1")


@pytest.fixture
def mock_sfn():
    client = MagicMock()
    client.start_execution.return_value = {
        "executionArn": "arn:aws:states:us-east-1:123:execution:rag:abc"
    }
    return client


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestKbIngestionCompleteHappyPath:

    def test_complete_event_starts_execution(self, mock_sfn):
        event = _make_cwl_event([json.dumps(_make_log_record("COMPLETE"))])
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler(event, None)

        assert result["executions_started"] == 1
        assert result["events_skipped"] == 0
        mock_sfn.start_execution.assert_called_once()

    def test_state_machine_input_carries_both_branch_uris(self, mock_sfn):
        """
        The state-machine input must include URIs for BOTH parallel
        branches (RAG + retrieval) so neither branch is blocked by a
        missing dataset/thresholds URI.
        """
        event = _make_cwl_event([json.dumps(_make_log_record("COMPLETE"))])
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            handler(event, None)

        kwargs = mock_sfn.start_execution.call_args[1]
        assert kwargs["stateMachineArn"] == STATE_MACHINE_ARN
        sent = json.loads(kwargs["input"])
        assert sent == EXPECTED_INPUT
        # Sanity: both branch keys present.
        for key in (
            "rag_dataset_s3_uri",
            "rag_thresholds_s3_uri",
            "retrieval_dataset_s3_uri",
            "retrieval_thresholds_s3_uri",
        ):
            assert key in sent, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Non-COMPLETE statuses must be ignored
# ---------------------------------------------------------------------------

class TestKbIngestionCompleteFilters:

    @pytest.mark.parametrize(
        "status",
        ["INGESTION_JOB_STARTED", "FAILED", "STOPPED", "CRAWLING_COMPLETED"],
    )
    def test_non_complete_status_skipped(self, status, mock_sfn):
        event = _make_cwl_event([json.dumps(_make_log_record(status))])
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler(event, None)

        assert result["executions_started"] == 0
        assert result["events_skipped"] == 1
        mock_sfn.start_execution.assert_not_called()

    def test_complete_for_wrong_kb_is_skipped(self, mock_sfn):
        other_arn = "arn:aws:bedrock:us-east-1:123456789012:knowledge-base/OTHER123"
        event = _make_cwl_event(
            [json.dumps(_make_log_record("COMPLETE", kb_arn=other_arn))]
        )
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler(event, None)

        assert result["executions_started"] == 0
        mock_sfn.start_execution.assert_not_called()

    def test_missing_kb_id_env_does_not_filter(self, mock_sfn, monkeypatch):
        """
        If KNOWLEDGE_BASE_ID is unset, the Lambda must still process
        COMPLETE events (defense-in-depth filter is opt-in via the env var).
        """
        monkeypatch.delenv("KNOWLEDGE_BASE_ID", raising=False)
        event = _make_cwl_event([json.dumps(_make_log_record("COMPLETE"))])
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler(event, None)

        assert result["executions_started"] == 1


# ---------------------------------------------------------------------------
# Malformed payloads must not crash
# ---------------------------------------------------------------------------

class TestKbIngestionCompleteRobustness:

    def test_missing_awslogs_key(self, mock_sfn):
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler({}, None)
        assert result == {"executions_started": 0, "events_skipped": 0}
        mock_sfn.start_execution.assert_not_called()

    def test_missing_data_field(self, mock_sfn):
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler({"awslogs": {}}, None)
        assert result["executions_started"] == 0
        mock_sfn.start_execution.assert_not_called()

    def test_corrupt_base64_payload(self, mock_sfn):
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler({"awslogs": {"data": "not-base64-or-gzip"}}, None)
        assert result["executions_started"] == 0
        mock_sfn.start_execution.assert_not_called()

    def test_non_json_log_message_is_skipped(self, mock_sfn):
        event = _make_cwl_event(["this is not JSON"])
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler(event, None)
        assert result["executions_started"] == 0
        assert result["events_skipped"] == 1
        mock_sfn.start_execution.assert_not_called()

    def test_log_record_missing_event_field(self, mock_sfn):
        event = _make_cwl_event([json.dumps({"other_field": "value"})])
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler(event, None)
        assert result["executions_started"] == 0
        mock_sfn.start_execution.assert_not_called()


# ---------------------------------------------------------------------------
# Multiple events in a single payload
# ---------------------------------------------------------------------------

class TestKbIngestionCompleteMultipleEvents:

    def test_mixed_events_only_complete_triggers(self, mock_sfn):
        event = _make_cwl_event(
            [
                json.dumps(_make_log_record("INGESTION_JOB_STARTED")),
                json.dumps(_make_log_record("CRAWLING_COMPLETED")),
                json.dumps(_make_log_record("COMPLETE")),
            ]
        )
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler(event, None)

        assert result["executions_started"] == 1
        assert result["events_skipped"] == 2
        assert mock_sfn.start_execution.call_count == 1

    def test_two_complete_events_start_two_executions(self, mock_sfn):
        """
        Defense against filter-pattern drift: if Logs delivers two COMPLETE
        entries (e.g., a re-delivery or two simultaneous ingestion jobs on
        the same KB), the Lambda processes each independently. Step
        Functions executions are idempotent enough that two concurrent
        evals don't break anything.
        """
        event = _make_cwl_event(
            [
                json.dumps(_make_log_record("COMPLETE")),
                json.dumps(_make_log_record("COMPLETE")),
            ]
        )
        with patch.object(_mod.boto3, "client", return_value=mock_sfn):
            result = handler(event, None)

        assert result["executions_started"] == 2
        assert mock_sfn.start_execution.call_count == 2
