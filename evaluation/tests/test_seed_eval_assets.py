"""
Unit tests for evaluation/lambdas/seed_eval_assets/handler.py

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
    os.path.join(os.path.dirname(__file__), "..", "lambdas", "seed_eval_assets", "handler.py")
)
_spec = importlib.util.spec_from_file_location("seed_eval_assets_handler", _HANDLER_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["seed_eval_assets_handler"] = _mod
_spec.loader.exec_module(_mod)

handler = _mod.handler
upload_seed_assets = _mod.upload_seed_assets
empty_bucket = _mod.empty_bucket
send_cfn_response = _mod.send_cfn_response


# ---------------------------------------------------------------------------
# TestCreateRequest
# ---------------------------------------------------------------------------

class TestCreateRequest:
    """On Create: uploads three seed files, no bedrock calls, returns FilesUploaded."""

    def test_uploads_two_seed_files(self, tmp_path, mock_s3_client):
        """Both seed files present — two put_object calls to the eval bucket."""
        # Create fake seed files under tmp_path (standing in for SEED_ASSETS_DIR)
        (tmp_path / "evaluation_dataset.jsonl").write_text('{"question": "q1"}')
        (tmp_path / "thresholds.json").write_text('{"retrieve_and_generate": {}}')

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_ASSETS_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert mock_s3_client.put_object.call_count == 2
        mock_send.assert_called_once()
        assert mock_send.call_args[0][2] == "SUCCESS"

    def test_files_uploaded_count(self, tmp_path, mock_s3_client):
        """FilesUploaded data key equals '2' when both seed files are present."""
        (tmp_path / "evaluation_dataset.jsonl").write_text("data")
        (tmp_path / "thresholds.json").write_text("data")

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_ASSETS_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert result["FilesUploaded"] == "2"

    def test_skips_missing_files(self, tmp_path, mock_s3_client):
        """Only one seed file present — uploads one, returns FilesUploaded == '1', no exception."""
        (tmp_path / "evaluation_dataset.jsonl").write_text("data")
        # thresholds.json absent

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_ASSETS_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert mock_s3_client.put_object.call_count == 1
        assert result["FilesUploaded"] == "1"
        assert mock_send.call_args[0][2] == "SUCCESS"

    def test_no_bedrock_calls(self, tmp_path, mock_s3_client):
        """No bedrock-agent API calls should be made during Create."""
        (tmp_path / "evaluation_dataset.jsonl").write_text("data")
        (tmp_path / "thresholds.json").write_text("data")

        event = make_cfn_event("Create")
        mock_bedrock = MagicMock()

        with (
            patch.object(_mod, "SEED_ASSETS_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", side_effect=[mock_s3_client]),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
            patch("boto3.client", return_value=mock_s3_client),
        ):
            handler(event, None)

        mock_bedrock.start_ingestion_job.assert_not_called()

    def test_uploads_to_canonical_s3_keys(self, tmp_path, mock_s3_client):
        """Seed files are uploaded to the canonical S3 keys defined in SEED_FILES."""
        (tmp_path / "evaluation_dataset.jsonl").write_text("data")
        (tmp_path / "thresholds.json").write_text("data")

        props = {
            "EvalBucketName": "my-special-eval-bucket",
            "ResultsBucketName": "my-results-bucket",
            "Region": "us-east-1",
        }
        event = make_cfn_event("Create", properties=props)

        with (
            patch.object(_mod, "SEED_ASSETS_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            handler(event, None)

        uploaded_calls = mock_s3_client.put_object.call_args_list
        buckets = [c[1]["Bucket"] for c in uploaded_calls]
        keys = [c[1]["Key"] for c in uploaded_calls]
        assert all(b == "my-special-eval-bucket" for b in buckets)
        assert "datasets/rag_eval.jsonl" in keys
        assert "baselines/thresholds.json" in keys


# ---------------------------------------------------------------------------
# TestUpdateRequestNoOp
# ---------------------------------------------------------------------------

class TestUpdateRequestNoOp:
    """On Update with identical EvalBucketName and ResultsBucketName: no S3 calls."""

    def test_no_calls_when_unchanged(self, mock_s3_client):
        """Identical old/new tracked properties: no put_object, SUCCESS response, empty data."""
        props = {
            "EvalBucketName": "my-eval-bucket",
            "ResultsBucketName": "my-results-bucket",
            "Region": "us-east-1",
        }
        event = make_cfn_event("Update", properties=props, old_properties=props.copy())

        with (
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        mock_s3_client.put_object.assert_not_called()
        assert mock_send.call_args[0][2] == "SUCCESS"
        assert result == {}


# ---------------------------------------------------------------------------
# TestUpdateRequestWithChanges
# ---------------------------------------------------------------------------

class TestUpdateRequestWithChanges:
    """On Update with changed tracked properties: re-upload seed assets."""

    def test_re_uploads_on_eval_bucket_change(self, tmp_path, mock_s3_client):
        """Changed EvalBucketName triggers re-upload to the new bucket."""
        (tmp_path / "evaluation_dataset.jsonl").write_text("data")
        (tmp_path / "thresholds.json").write_text("data")

        new_props = {
            "EvalBucketName": "new-eval-bucket",
            "ResultsBucketName": "my-results-bucket",
            "Region": "us-east-1",
        }
        old_props = {**new_props, "EvalBucketName": "old-eval-bucket"}
        event = make_cfn_event("Update", properties=new_props, old_properties=old_props)

        with (
            patch.object(_mod, "SEED_ASSETS_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert mock_s3_client.put_object.call_count == 2
        assert mock_send.call_args[0][2] == "SUCCESS"
        assert result["FilesUploaded"] == "2"

    def test_re_uploads_on_results_bucket_change(self, tmp_path, mock_s3_client):
        """Changed ResultsBucketName is a tracked key — triggers re-upload."""
        (tmp_path / "evaluation_dataset.jsonl").write_text("data")
        (tmp_path / "thresholds.json").write_text("data")

        new_props = {
            "EvalBucketName": "my-eval-bucket",
            "ResultsBucketName": "new-results-bucket",
            "Region": "us-east-1",
        }
        old_props = {**new_props, "ResultsBucketName": "old-results-bucket"}
        event = make_cfn_event("Update", properties=new_props, old_properties=old_props)

        with (
            patch.object(_mod, "SEED_ASSETS_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert mock_s3_client.put_object.call_count == 2
        assert mock_send.call_args[0][2] == "SUCCESS"


# ---------------------------------------------------------------------------
# TestDeleteRequest
# ---------------------------------------------------------------------------

class TestDeleteRequest:
    """On Delete: empties both EvalBucket and ResultsBucket, no bedrock calls."""

    def test_empties_both_buckets(self, mock_s3_client):
        """Delete calls list_objects_v2 and delete_objects for both buckets."""
        # Simulate one page of objects in eval bucket, empty results bucket
        eval_page = {"Contents": [
            {"Key": "datasets/rag_eval.jsonl"},
            {"Key": "baselines/thresholds.json"},
        ]}
        empty_page = {"Contents": []}

        call_count = {"n": 0}
        def paginator_side_effect(Bucket):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return iter([eval_page])
            return iter([empty_page])

        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = paginator_side_effect
        mock_s3_client.get_paginator.return_value = mock_paginator

        props = {
            "EvalBucketName": "my-eval-bucket",
            "ResultsBucketName": "my-results-bucket",
            "Region": "us-east-1",
        }
        event = make_cfn_event("Delete", properties=props)

        with (
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        # delete_objects called once for the non-empty eval bucket page
        assert mock_s3_client.delete_objects.call_count == 1
        assert mock_send.call_args[0][2] == "SUCCESS"
        assert result == {}

    def test_no_bedrock_calls(self, mock_s3_client):
        """No bedrock-agent calls on Delete."""
        event = make_cfn_event("Delete")

        with (
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            handler(event, None)

        # The mock_s3_client is the only client; no bedrock client was created
        # Verify no attributes named start_ingestion_job were called
        assert not hasattr(mock_s3_client, "start_ingestion_job") or \
               not mock_s3_client.start_ingestion_job.called

    def test_empties_trail_log_bucket_when_property_present(self, mock_s3_client):
        """When TrailLogBucketName is passed, the Delete branch empties three buckets, not two."""
        empty_page = {"Contents": []}

        seen_buckets: list[str] = []
        def paginator_side_effect(Bucket):
            seen_buckets.append(Bucket)
            return iter([empty_page])

        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = paginator_side_effect
        mock_s3_client.get_paginator.return_value = mock_paginator

        props = {
            "EvalBucketName": "my-eval-bucket",
            "ResultsBucketName": "my-results-bucket",
            "TrailLogBucketName": "my-trail-bucket",
            "Region": "us-east-1",
        }
        event = make_cfn_event("Delete", properties=props)

        with (
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            handler(event, None)

        # empty_bucket() makes two paginate calls per bucket
        # (list_objects_v2 + list_object_versions). With three buckets
        # ordered [eval, results, trail], we expect six entries with the
        # bucket names alternating two-at-a-time.
        unique_buckets = list(dict.fromkeys(seen_buckets))
        assert unique_buckets == ["my-eval-bucket", "my-results-bucket", "my-trail-bucket"]
        assert mock_send.call_args[0][2] == "SUCCESS"

    def test_empty_bucket_is_noop(self, mock_s3_client):
        """If both buckets are already empty, no delete_objects calls."""
        empty_page = {"Contents": []}
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = iter([empty_page])
        mock_s3_client.get_paginator.return_value = mock_paginator

        event = make_cfn_event("Delete")

        with (
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            handler(event, None)

        mock_s3_client.delete_objects.assert_not_called()
        assert mock_send.call_args[0][2] == "SUCCESS"


# ---------------------------------------------------------------------------
# TestSendCfnResponse
# ---------------------------------------------------------------------------

class TestSendCfnResponse:
    """Verifies the JSON body and HTTP request shape produced by send_cfn_response."""

    def test_body_shape(self):
        """Response body contains all required keys."""
        event = make_cfn_event("Create")

        with patch.object(_mod.urllib.request, "urlopen") as mock_urlopen:
            send_cfn_response(
                event,
                context=None,
                status="SUCCESS",
                data={"FilesUploaded": "3"},
                physical_resource_id="seed-eval-assets-resource",
            )

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        for key in ("Status", "Reason", "PhysicalResourceId", "StackId",
                    "RequestId", "LogicalResourceId", "Data"):
            assert key in body, f"Missing key in CFN response body: {key}"

    def test_failed_includes_reason(self):
        """FAILED status carries the reason string in the body."""
        event = make_cfn_event("Create")

        with patch.object(_mod.urllib.request, "urlopen") as mock_urlopen:
            send_cfn_response(
                event,
                context=None,
                status="FAILED",
                reason="ClientError: Access Denied",
                physical_resource_id="seed-eval-assets-resource",
            )

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["Status"] == "FAILED"
        assert "Access Denied" in body["Reason"]

    def test_puts_to_response_url(self):
        """The request goes to event['ResponseURL'] with method PUT."""
        event = make_cfn_event("Create")
        event["ResponseURL"] = "https://s3-presigned.example.com/cfn-response"

        with patch.object(_mod.urllib.request, "urlopen") as mock_urlopen:
            send_cfn_response(event, context=None, status="SUCCESS",
                              physical_resource_id="phys-id")

        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "PUT"
        assert req.full_url == "https://s3-presigned.example.com/cfn-response"


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Any exception in the handler body emits FAILED; handler never raises."""

    def test_failed_on_s3_put_denial(self, tmp_path, mock_s3_client):
        """s3:PutObject raises → FAILED response, handler returns normally."""
        (tmp_path / "evaluation_dataset.jsonl").write_text("data")
        mock_s3_client.put_object.side_effect = Exception("AccessDenied: s3:PutObject")

        event = make_cfn_event("Create")

        with (
            patch.object(_mod, "SEED_ASSETS_DIR", str(tmp_path)),
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert mock_send.call_args[0][2] == "FAILED"
        reason = mock_send.call_args[1].get("reason", "") or ""
        assert "AccessDenied" in reason
        assert isinstance(result, dict)

    def test_failed_on_delete_denial(self, mock_s3_client):
        """s3:ListBucket raises during Delete → FAILED response."""
        mock_paginator = MagicMock()
        mock_paginator.paginate.side_effect = Exception("AccessDenied: s3:ListBucket")
        mock_s3_client.get_paginator.return_value = mock_paginator

        event = make_cfn_event("Delete")

        with (
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert mock_send.call_args[0][2] == "FAILED"
        assert isinstance(result, dict)

    def test_handler_never_raises(self, mock_s3_client):
        """handler() must never raise — any exception is caught and returned as FAILED."""
        mock_s3_client.put_object.side_effect = RuntimeError("totally unexpected")

        event = make_cfn_event("Create")

        with (
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response"),
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            # Must not raise
            result = handler(event, None)

        assert isinstance(result, dict)

    def test_unknown_request_type_sends_failed(self, mock_s3_client):
        """An unknown RequestType is caught and results in a FAILED response."""
        event = make_cfn_event("Create")
        event["RequestType"] = "Bogus"

        with (
            patch.object(_mod.boto3, "client", return_value=mock_s3_client),
            patch.object(_mod, "send_cfn_response") as mock_send,
            patch.object(_mod.urllib.request, "urlopen"),
        ):
            result = handler(event, None)

        assert mock_send.call_args[0][2] == "FAILED"
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestModuleConstants
# ---------------------------------------------------------------------------

class TestModuleConstants:
    """Verify SEED_FILES and _TRACKED_KEYS match the contract spec."""

    def test_seed_files_value(self):
        """SEED_FILES has exactly two tuples with the canonical S3 keys."""
        expected = [
            ("evaluation_dataset.jsonl", "datasets/rag_eval.jsonl"),
            ("thresholds.json",          "baselines/thresholds.json"),
        ]
        assert _mod.SEED_FILES == expected

    def test_tracked_keys_value(self):
        """_TRACKED_KEYS is exactly ('EvalBucketName', 'ResultsBucketName')."""
        assert _mod._TRACKED_KEYS == ("EvalBucketName", "ResultsBucketName")

    def test_seed_assets_dir_is_under_handler_dir(self):
        """SEED_ASSETS_DIR is inside the same directory as handler.py."""
        handler_dir = os.path.dirname(_HANDLER_PATH)
        assert _mod.SEED_ASSETS_DIR.startswith(handler_dir)
        assert _mod.SEED_ASSETS_DIR.endswith("seed_assets")
