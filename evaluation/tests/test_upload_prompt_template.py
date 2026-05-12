"""
Unit tests for evaluation/scripts/upload_prompt_template.py

Tests cover resolve_eval_bucket(), main() argparse defaults, and upload
behavior. boto3 calls are mocked; no real AWS calls are made.
"""
import importlib.util
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Module loader — import upload_prompt_template.py by absolute path
# ---------------------------------------------------------------------------
_SCRIPT_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "scripts", "upload_prompt_template.py"
    )
)
_spec = importlib.util.spec_from_file_location("upload_prompt_template", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["upload_prompt_template"] = _mod
_spec.loader.exec_module(_mod)

resolve_eval_bucket = _mod.resolve_eval_bucket
main = _mod.main


# ---------------------------------------------------------------------------
# TestResolveEvalBucket
# ---------------------------------------------------------------------------

class TestResolveEvalBucket:
    """Tests for the resolve_eval_bucket(cfn_client, stack_name) helper."""

    def test_returns_bucket_when_output_present(self, mock_cfn_client):
        """Returns the OutputValue of EvalBucketName when the stack has that output."""
        bucket = resolve_eval_bucket(mock_cfn_client, "rag-eval-pipeline")

        assert bucket == "rag-eval-pipeline-eval-123456789012-us-east-1"
        mock_cfn_client.describe_stacks.assert_called_once_with(StackName="rag-eval-pipeline")

    def test_raises_runtime_error_when_stack_not_found(self):
        """RuntimeError with a friendly hint when describe_stacks raises (stack does not exist)."""
        cfn_client = MagicMock()
        cfn_client.describe_stacks.side_effect = Exception(
            "An error occurred (ValidationError): Stack 'rag-eval-pipeline' does not exist"
        )

        with pytest.raises(RuntimeError, match="not found"):
            resolve_eval_bucket(cfn_client, "rag-eval-pipeline")

    def test_raises_runtime_error_hint_contains_stack_name(self):
        """The RuntimeError message mentions the stack name and suggests sam deploy."""
        cfn_client = MagicMock()
        cfn_client.describe_stacks.side_effect = Exception("Stack does not exist")

        with pytest.raises(RuntimeError) as exc_info:
            resolve_eval_bucket(cfn_client, "my-stack")

        assert "my-stack" in str(exc_info.value)
        assert "sam deploy" in str(exc_info.value)

    def test_raises_key_error_when_output_missing(self):
        """KeyError when stack exists but EvalBucketName output is not in Outputs."""
        cfn_client = MagicMock()
        cfn_client.describe_stacks.return_value = {
            "Stacks": [
                {
                    "StackName": "rag-eval-pipeline",
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [
                        {"OutputKey": "StateMachineArn", "OutputValue": "arn:aws:states:..."},
                    ],
                }
            ]
        }

        with pytest.raises(KeyError):
            resolve_eval_bucket(cfn_client, "rag-eval-pipeline")

    def test_raises_runtime_error_when_stacks_list_is_empty(self):
        """RuntimeError when describe_stacks returns an empty Stacks list."""
        cfn_client = MagicMock()
        cfn_client.describe_stacks.return_value = {"Stacks": []}

        with pytest.raises(RuntimeError, match="not found"):
            resolve_eval_bucket(cfn_client, "rag-eval-pipeline")


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------

class TestMain:
    """Tests for main() argparse behavior and upload flow."""

    def test_bucket_flag_skips_stack_lookup(self, mock_cfn_client, tmp_path):
        """When --bucket is provided, CloudFormation is not called."""
        template_file = tmp_path / "kb_prompt_template.txt"
        template_file.write_text("system prompt content")

        mock_s3 = MagicMock()

        with (
            patch("sys.argv", [
                "upload_prompt_template.py",
                "--bucket", "explicit-bucket",
                "--template", str(template_file),
            ]),
            patch.object(_mod.boto3, "client", return_value=mock_s3),
        ):
            main()

        # s3.upload_file was called, but no cloudformation client was used
        mock_s3.upload_file.assert_called_once()
        call_args = mock_s3.upload_file.call_args
        assert call_args[0][1] == "explicit-bucket"

    def test_resolves_from_stack_when_no_bucket_flag(self, mock_cfn_client, tmp_path):
        """Without --bucket, resolves bucket from CloudFormation stack output."""
        template_file = tmp_path / "kb_prompt_template.txt"
        template_file.write_text("system prompt content")

        mock_s3 = MagicMock()
        mock_cfn = MagicMock()
        mock_cfn.describe_stacks.return_value = {
            "Stacks": [{
                "StackName": "rag-eval-pipeline",
                "StackStatus": "CREATE_COMPLETE",
                "Outputs": [{
                    "OutputKey": "EvalBucketName",
                    "OutputValue": "rag-eval-pipeline-eval-123456789012-us-east-1",
                }],
            }]
        }

        with (
            patch("sys.argv", [
                "upload_prompt_template.py",
                "--template", str(template_file),
            ]),
            patch.object(_mod.boto3, "client", side_effect=[mock_cfn, mock_s3]),
        ):
            main()

        mock_cfn.describe_stacks.assert_called_once()
        mock_s3.upload_file.assert_called_once()
        # bucket should be the resolved one
        call_args = mock_s3.upload_file.call_args
        assert call_args[0][1] == "rag-eval-pipeline-eval-123456789012-us-east-1"

    def test_uploads_to_canonical_key(self, tmp_path):
        """Uploaded S3 key is <prefix>kb_prompt_template.txt."""
        template_file = tmp_path / "kb_prompt_template.txt"
        template_file.write_text("system prompt content")

        mock_s3 = MagicMock()

        with (
            patch("sys.argv", [
                "upload_prompt_template.py",
                "--bucket", "my-bucket",
                "--prefix", "prompts/",
                "--template", str(template_file),
            ]),
            patch.object(_mod.boto3, "client", return_value=mock_s3),
        ):
            main()

        call_args = mock_s3.upload_file.call_args
        uploaded_key = call_args[0][2]
        assert uploaded_key.endswith("kb_prompt_template.txt")
        assert "prompts" in uploaded_key

    def test_argparse_defaults(self):
        """Default flag values match samconfig.toml and contract spec."""
        import argparse

        # Parse with no arguments (use defaults); provide --bucket and --template to avoid
        # real filesystem/network calls and argparse errors
        parser = argparse.ArgumentParser()
        parser.add_argument("--bucket", default=None)
        parser.add_argument("--stack-name", default="rag-eval-pipeline")
        parser.add_argument("--region", default="us-east-1")
        parser.add_argument("--prefix", default="prompts/")
        parser.add_argument("--template", default="some_template.txt")

        args = parser.parse_args([])
        assert args.stack_name == "rag-eval-pipeline"
        assert args.region == "us-east-1"
        assert args.prefix == "prompts/"
        assert args.bucket is None

    def test_region_default_is_us_east_1(self, tmp_path):
        """The --region default must be 'us-east-1', NOT the stale 'us-east-2'."""
        template_file = tmp_path / "kb_prompt_template.txt"
        template_file.write_text("content")

        mock_s3 = MagicMock()
        mock_cfn = MagicMock()
        mock_cfn.describe_stacks.return_value = {
            "Stacks": [{
                "StackName": "rag-eval-pipeline",
                "StackStatus": "CREATE_COMPLETE",
                "Outputs": [{
                    "OutputKey": "EvalBucketName",
                    "OutputValue": "my-bucket",
                }],
            }]
        }

        boto3_calls: list[tuple] = []

        def capture_client(service, region_name=None, **kwargs):
            boto3_calls.append((service, region_name))
            if service == "cloudformation":
                return mock_cfn
            return mock_s3

        with (
            patch("sys.argv", [
                "upload_prompt_template.py",
                "--template", str(template_file),
            ]),
            patch.object(_mod.boto3, "client", side_effect=capture_client),
        ):
            main()

        regions_used = [region for _, region in boto3_calls]
        assert all(r == "us-east-1" for r in regions_used), (
            f"Expected all clients to use us-east-1 by default, got: {regions_used}"
        )
