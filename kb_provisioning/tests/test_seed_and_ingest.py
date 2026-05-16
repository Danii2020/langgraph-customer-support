"""
Unit tests for kb_provisioning/lambdas/seed_and_ingest/handler.py

Uses importlib.util.spec_from_file_location to load handler.py by absolute
path, matching the pattern in evaluation/tests/test_start_eval_job.py:10-19.
"""
import importlib.util
import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch, call

from .conftest import make_cfn_event

# ---------------------------------------------------------------------------
# Module loader — import handler.py by absolute path
# ---------------------------------------------------------------------------
_HANDLER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "lambdas", "seed_and_ingest", "handler.py")
)
_spec = importlib.util.spec_from_file_location("seed_and_ingest_handler", _HANDLER_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["seed_and_ingest_handler"] = _mod
_spec.loader.exec_module(_mod)

handler = _mod.handler
upload_seed_data = _mod.upload_seed_data
start_ingestion = _mod.start_ingestion
empty_bucket = _mod.empty_bucket
send_cfn_response = _mod.send_cfn_response


# ---------------------------------------------------------------------------
# TestCreateRequest
# ---------------------------------------------------------------------------

class TestCreateRequest:
    """On Create: uploads seed files, starts ingestion, returns IngestionJobId + FilesUploaded."""

    def test_uploads_seed_files_and_starts_ingestion(
        self, tmp_path, mock_s3_client, mock_bedrock_agent_client
    ):
        # Create two seed files in a temporary directory
        (tmp_path / "policies.txt").write_text("policy content")
        (tmp_path / "data.txt").write_text("data content")

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_DATA_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert mock_s3_client.put_object.call_count == 2
        mock_bedrock_agent_client.start_ingestion_job.assert_called_once_with(
            knowledgeBaseId="KB123",
            dataSourceId="DS456",
        )
        assert result["IngestionJobId"] == "test-job-id-001"
        assert result["FilesUploaded"] == "2"
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][2] == "SUCCESS"

    def test_response_data_contains_files_uploaded(
        self, tmp_path, mock_s3_client, mock_bedrock_agent_client
    ):
        (tmp_path / "policies.txt").write_text("policy content")

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_DATA_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert result["FilesUploaded"] == "1"

    def test_put_object_uses_correct_prefix_and_bucket(
        self, tmp_path, mock_s3_client, mock_bedrock_agent_client
    ):
        (tmp_path / "policies.txt").write_text("content")

        props = {
            "SourceBucketName": "my-workshop-bucket",
            "SourceDataPrefix": "docs/",
            "KnowledgeBaseId": "KB123",
            "DataSourceId": "DS456",
            "Region": "us-east-1",
        }
        event = make_cfn_event("Create", properties=props)

        with (
            patch.object(_mod, "SEED_DATA_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            handler(event, None)

        call_kwargs = mock_s3_client.put_object.call_args[1]
        assert call_kwargs["Bucket"] == "my-workshop-bucket"
        assert call_kwargs["Key"] == "docs/policies.txt"


# ---------------------------------------------------------------------------
# TestUpdateRequestNoOp
# ---------------------------------------------------------------------------

class TestUpdateRequestNoOp:
    """On Update with identical ResourceProperties: no S3 or Bedrock calls, SUCCESS response."""

    def test_no_s3_calls_when_properties_unchanged(
        self, mock_s3_client, mock_bedrock_agent_client
    ):
        props = {
            "SourceBucketName": "my-bucket",
            "SourceDataPrefix": "data/",
            "KnowledgeBaseId": "KB123",
            "DataSourceId": "DS456",
            "Region": "us-east-1",
        }
        event = make_cfn_event("Update", properties=props, old_properties=props.copy())

        with (
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        mock_s3_client.put_object.assert_not_called()
        mock_bedrock_agent_client.start_ingestion_job.assert_not_called()
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][2] == "SUCCESS"
        assert result == {}

    def test_returns_empty_dict_on_noop(self, mock_s3_client, mock_bedrock_agent_client):
        props = {
            "SourceBucketName": "bucket",
            "SourceDataPrefix": "data/",
            "KnowledgeBaseId": "KB999",
            "DataSourceId": "DS999",
            "Region": "us-east-1",
        }
        event = make_cfn_event("Update", properties=props, old_properties=props.copy())

        with (
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert result == {}


# ---------------------------------------------------------------------------
# TestUpdateRequestWithChanges
# ---------------------------------------------------------------------------

class TestUpdateRequestWithChanges:
    """On Update with changed tracked properties: re-upload and re-ingest."""

    def test_re_ingests_when_knowledge_base_id_changes(
        self, tmp_path, mock_s3_client, mock_bedrock_agent_client
    ):
        (tmp_path / "policies.txt").write_text("content")

        new_props = {
            "SourceBucketName": "my-bucket",
            "SourceDataPrefix": "data/",
            "KnowledgeBaseId": "KB-NEW",
            "DataSourceId": "DS456",
            "Region": "us-east-1",
        }
        old_props = {**new_props, "KnowledgeBaseId": "KB-OLD"}
        event = make_cfn_event("Update", properties=new_props, old_properties=old_props)

        with (
            patch.object(_mod, "SEED_DATA_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        mock_s3_client.put_object.assert_called()
        mock_bedrock_agent_client.start_ingestion_job.assert_called_once()
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][2] == "SUCCESS"
        assert "IngestionJobId" in result

    def test_re_ingests_when_data_source_id_changes(
        self, tmp_path, mock_s3_client, mock_bedrock_agent_client
    ):
        (tmp_path / "data.txt").write_text("content")

        new_props = {
            "SourceBucketName": "my-bucket",
            "SourceDataPrefix": "data/",
            "KnowledgeBaseId": "KB123",
            "DataSourceId": "DS-NEW",
            "Region": "us-east-1",
        }
        old_props = {**new_props, "DataSourceId": "DS-OLD"}
        event = make_cfn_event("Update", properties=new_props, old_properties=old_props)

        with (
            patch.object(_mod, "SEED_DATA_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        mock_bedrock_agent_client.start_ingestion_job.assert_called_once()


# ---------------------------------------------------------------------------
# TestDeleteRequest
# ---------------------------------------------------------------------------

class TestDeleteRequest:
    """On Delete: empties bucket (paginated), no Bedrock calls."""

    def test_calls_delete_objects_for_each_page(
        self, mock_s3_client, mock_bedrock_agent_client
    ):
        # Two pages: first has 2 objects, second is empty
        page1 = {"Contents": [{"Key": "data/policies.txt"}, {"Key": "data/data.txt"}]}
        page2 = {"Contents": []}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = iter([page1, page2])
        mock_s3_client.get_paginator.return_value = mock_paginator

        event = make_cfn_event("Delete")

        with (
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        mock_s3_client.delete_objects.assert_called_once_with(
            Bucket="my-source-bucket",
            Delete={
                "Objects": [
                    {"Key": "data/policies.txt"},
                    {"Key": "data/data.txt"},
                ]
            },
        )
        mock_bedrock_agent_client.start_ingestion_job.assert_not_called()
        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][2] == "SUCCESS"

    def test_no_bedrock_calls_on_delete(self, mock_s3_client, mock_bedrock_agent_client):
        event = make_cfn_event("Delete")

        with (
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            handler(event, None)

        mock_bedrock_agent_client.start_ingestion_job.assert_not_called()

    def test_empty_bucket_skips_delete_when_no_objects(
        self, mock_s3_client, mock_bedrock_agent_client
    ):
        page = {"Contents": []}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = iter([page])
        mock_s3_client.get_paginator.return_value = mock_paginator

        event = make_cfn_event("Delete")

        with (
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            handler(event, None)

        mock_s3_client.delete_objects.assert_not_called()


# ---------------------------------------------------------------------------
# TestSendCfnResponse
# ---------------------------------------------------------------------------

class TestSendCfnResponse:
    """Verifies the JSON body and HTTP request shape produced by send_cfn_response."""

    def test_sends_put_to_response_url(self):
        event = make_cfn_event("Create")

        with patch.object(_mod.urllib.request, "urlopen") as mock_urlopen:
            send_cfn_response(
                event,
                context=None,
                status="SUCCESS",
                data={"IngestionJobId": "job-abc"},
                physical_resource_id="phys-id",
            )

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "PUT"
        assert req.full_url == event["ResponseURL"]

    def test_body_contains_required_keys(self):
        event = make_cfn_event("Create")

        with patch.object(_mod.urllib.request, "urlopen") as mock_urlopen:
            send_cfn_response(
                event,
                context=None,
                status="SUCCESS",
                data={"FilesUploaded": "2"},
                physical_resource_id="phys-id",
            )

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        for key in ("Status", "Reason", "PhysicalResourceId", "StackId", "RequestId", "LogicalResourceId", "Data"):
            assert key in body, f"Missing key in CFN response body: {key}"

    def test_failed_status_includes_reason(self):
        event = make_cfn_event("Create")

        with patch.object(_mod.urllib.request, "urlopen") as mock_urlopen:
            send_cfn_response(
                event,
                context=None,
                status="FAILED",
                reason="Something went wrong",
                physical_resource_id="phys-id",
            )

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["Status"] == "FAILED"
        assert "Something went wrong" in body["Reason"]

    def test_body_populates_stack_and_request_ids(self):
        event = make_cfn_event("Create")
        event["StackId"] = "arn:aws:cloudformation:us-east-1:123:stack/mystack/abc"
        event["RequestId"] = "req-xyz"
        event["LogicalResourceId"] = "MyResource"

        with patch.object(_mod.urllib.request, "urlopen") as mock_urlopen:
            send_cfn_response(event, context=None, status="SUCCESS", physical_resource_id="pid")

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["StackId"] == event["StackId"]
        assert body["RequestId"] == "req-xyz"
        assert body["LogicalResourceId"] == "MyResource"


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Any exception in the handler body emits FAILED; handler never raises."""

    def test_emits_failed_when_s3_raises(self, mock_s3_client, mock_bedrock_agent_client, tmp_path):
        (tmp_path / "policies.txt").write_text("content")
        mock_s3_client.put_object.side_effect = Exception("AccessDenied")

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_DATA_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][2] == "FAILED"
        assert "AccessDenied" in call_args[1].get("reason", "") or \
               "AccessDenied" in str(call_args)

    def test_emits_failed_when_bedrock_raises(self, mock_s3_client, mock_bedrock_agent_client, tmp_path):
        (tmp_path / "policies.txt").write_text("content")
        mock_bedrock_agent_client.start_ingestion_job.side_effect = Exception("ValidationException")

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_DATA_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        mock_send.assert_called_once()
        args = mock_send.call_args
        assert args[0][2] == "FAILED"

    def test_handler_never_raises(self, mock_s3_client, mock_bedrock_agent_client):
        """Handler must catch all exceptions and return normally (never raise)."""
        mock_s3_client.put_object.side_effect = RuntimeError("unexpected")

        event = make_cfn_event("Create")
        # SEED_DATA_DIR left as default (no real files) — trigger path via mock

        with (
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            # Must not raise
            result = handler(event, None)

        assert isinstance(result, dict)

    def test_failed_response_reason_contains_exception_message(
        self, mock_s3_client, mock_bedrock_agent_client, tmp_path
    ):
        (tmp_path / "policies.txt").write_text("content")
        mock_s3_client.put_object.side_effect = ValueError("bucket-does-not-exist")

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_DATA_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client, mock_bedrock_agent_client]),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            handler(event, None)

        call_args = mock_send.call_args
        # reason is passed as keyword arg
        reason = call_args[1].get("reason", "") or ""
        assert "bucket-does-not-exist" in reason
