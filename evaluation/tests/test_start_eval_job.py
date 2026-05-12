"""
Unit tests for evaluation/lambdas/start_eval_job/handler.py
"""
import importlib.util
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

_HANDLER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "lambdas", "start_eval_job", "handler.py")
)
_spec = importlib.util.spec_from_file_location("start_eval_job_handler", _HANDLER_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["start_eval_job_handler"] = _mod
_spec.loader.exec_module(_mod)

handler = _mod.handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_EVENT = {
    "knowledge_base_id": "ABCDEF123456",
    "eval_config": {
        "dataset_s3_uri": "s3://my-bucket/datasets/eval.jsonl",
        "output_s3_uri": "s3://my-bucket/results/",
        "role_arn": "arn:aws:iam::123456789012:role/BedrockEvalRole",
        "evaluator_model_id": "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0",
        "model_id": "arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0",
    },
}

RAG_EVENT = {**BASE_EVENT, "eval_type": "RETRIEVE_AND_GENERATE"}


def make_mock_bedrock(job_arn: str = "arn:aws:bedrock:us-east-2:123:evaluation-job/job-abc") -> MagicMock:
    client = MagicMock()
    client.create_evaluation_job.return_value = {"jobArn": job_arn}
    return client


# ---------------------------------------------------------------------------
# Retrieve-and-generate job creation
# ---------------------------------------------------------------------------

class TestStartEvalJobRetrieveAndGenerate:

    def test_returns_job_arn(self):
        expected_arn = "arn:aws:bedrock:us-east-2:123:evaluation-job/rag-job-001"
        mock_bedrock = make_mock_bedrock(expected_arn)
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            result = handler(RAG_EVENT, None)

        assert result["job_arn"] == expected_arn

    def test_calls_create_evaluation_job(self):
        mock_bedrock = make_mock_bedrock()
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            handler(RAG_EVENT, None)

        mock_bedrock.create_evaluation_job.assert_called_once()
        call_kwargs = mock_bedrock.create_evaluation_job.call_args[1]
        assert "jobName" in call_kwargs
        assert call_kwargs["roleArn"] == BASE_EVENT["eval_config"]["role_arn"]

    def test_job_name_contains_retrieve_and_generate(self):
        mock_bedrock = make_mock_bedrock()
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            handler(RAG_EVENT, None)

        call_kwargs = mock_bedrock.create_evaluation_job.call_args[1]
        assert "retrieve-and-generate" in call_kwargs["jobName"].lower()

    def test_output_s3_uri_is_passed(self):
        mock_bedrock = make_mock_bedrock()
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            handler(RAG_EVENT, None)

        call_kwargs = mock_bedrock.create_evaluation_job.call_args[1]
        assert call_kwargs["outputDataConfig"]["s3Uri"] == BASE_EVENT["eval_config"]["output_s3_uri"]

    def test_model_id_included_in_job_config(self):
        mock_bedrock = make_mock_bedrock()
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            handler(RAG_EVENT, None)

        call_kwargs = mock_bedrock.create_evaluation_job.call_args[1]
        # Verify the model ID appears in the inference config
        inference_config_str = str(call_kwargs.get("inferenceConfig", {}))
        assert RAG_EVENT["eval_config"]["model_id"] in inference_config_str


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestStartEvalJobErrors:

    def test_raises_key_error_when_eval_type_missing(self):
        event = {**BASE_EVENT}
        with pytest.raises(KeyError, match="eval_type"):
            handler(event, None)

    def test_raises_key_error_when_knowledge_base_id_missing(self):
        event = {"eval_type": "RETRIEVE_AND_GENERATE", "eval_config": BASE_EVENT["eval_config"]}
        with pytest.raises(KeyError, match="knowledge_base_id"):
            handler(event, None)

    def test_raises_value_error_for_invalid_eval_type(self):
        event = {**RAG_EVENT, "eval_type": "INVALID_TYPE"}
        with pytest.raises(ValueError, match="Invalid eval_type"):
            handler(event, None)

    def test_raises_value_error_for_retrieval_only_eval_type(self):
        event = {**RAG_EVENT, "eval_type": "RETRIEVAL_ONLY"}
        with pytest.raises(ValueError, match="Invalid eval_type"):
            handler(event, None)

    def test_raises_key_error_when_dataset_uri_missing(self):
        event = {
            "eval_type": "RETRIEVE_AND_GENERATE",
            "knowledge_base_id": "KB123",
            "eval_config": {
                "output_s3_uri": "s3://bucket/output/",
                "role_arn": "arn:aws:iam::123:role/Role",
                "evaluator_model_id": "arn:aws:bedrock:us-east-2::foundation-model/test-model",
                "model_id": "arn:aws:bedrock:us-east-2::foundation-model/test-model",
            },
        }
        with pytest.raises(KeyError, match="dataset_s3_uri"):
            handler(event, None)

    def test_raises_key_error_when_output_uri_missing(self):
        event = {
            "eval_type": "RETRIEVE_AND_GENERATE",
            "knowledge_base_id": "KB123",
            "eval_config": {
                "dataset_s3_uri": "s3://bucket/data.jsonl",
                "role_arn": "arn:aws:iam::123:role/Role",
                "evaluator_model_id": "arn:aws:bedrock:us-east-2::foundation-model/test-model",
                "model_id": "arn:aws:bedrock:us-east-2::foundation-model/test-model",
            },
        }
        with pytest.raises(KeyError, match="output_s3_uri"):
            handler(event, None)

    def test_raises_key_error_when_role_arn_missing(self):
        event = {
            "eval_type": "RETRIEVE_AND_GENERATE",
            "knowledge_base_id": "KB123",
            "eval_config": {
                "dataset_s3_uri": "s3://bucket/data.jsonl",
                "output_s3_uri": "s3://bucket/output/",
                "evaluator_model_id": "arn:aws:bedrock:us-east-2::foundation-model/test-model",
                "model_id": "arn:aws:bedrock:us-east-2::foundation-model/test-model",
            },
        }
        with pytest.raises(KeyError, match="role_arn"):
            handler(event, None)

    def test_raises_key_error_when_evaluator_model_id_missing(self):
        event = {
            "eval_type": "RETRIEVE_AND_GENERATE",
            "knowledge_base_id": "KB123",
            "eval_config": {
                "dataset_s3_uri": "s3://bucket/data.jsonl",
                "output_s3_uri": "s3://bucket/output/",
                "role_arn": "arn:aws:iam::123:role/Role",
                "model_id": "arn:aws:bedrock:us-east-2::foundation-model/test-model",
            },
        }
        with pytest.raises(KeyError, match="evaluator_model_id"):
            handler(event, None)

    def test_raises_key_error_when_model_id_missing_for_rag(self):
        event = {
            "eval_type": "RETRIEVE_AND_GENERATE",
            "knowledge_base_id": "KB123",
            "eval_config": {
                "dataset_s3_uri": "s3://bucket/data.jsonl",
                "output_s3_uri": "s3://bucket/output/",
                "role_arn": "arn:aws:iam::123:role/Role",
                "evaluator_model_id": "arn:aws:bedrock:us-east-2::foundation-model/test-model",
                # model_id intentionally omitted
            },
        }
        with pytest.raises(KeyError, match="model_id"):
            handler(event, None)

    def test_raises_runtime_error_on_bedrock_api_failure(self):
        mock_bedrock = MagicMock()
        mock_bedrock.create_evaluation_job.side_effect = Exception("ThrottlingException")
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            with pytest.raises(RuntimeError, match="Failed to create"):
                handler(RAG_EVENT, None)

    def test_raises_value_error_when_job_arn_missing_in_response(self):
        mock_bedrock = MagicMock()
        mock_bedrock.create_evaluation_job.return_value = {}  # no jobArn
        with patch.object(_mod.boto3, "client", return_value=mock_bedrock):
            with pytest.raises(ValueError, match="did not contain jobArn"):
                handler(RAG_EVENT, None)


# ---------------------------------------------------------------------------
# Prompt Management integration
# ---------------------------------------------------------------------------

def _make_get_prompt_response(text: str, version: str = "1") -> dict:
    """Build a get_prompt response with the given variant text and version."""
    return {
        "version": version,
        "variants": [
            {
                "name": "default",
                "templateConfiguration": {
                    "text": {
                        "text": text,
                        "inputVariables": [{"name": "search_results"}, {"name": "query"}],
                    }
                },
            }
        ],
    }


def _make_clients(bedrock_client: MagicMock, bedrock_agent_client: MagicMock):
    """
    Return a side_effect for boto3.client that returns the right mock for
    each service name ('bedrock' vs 'bedrock-agent').
    """
    def factory(service_name, *args, **kwargs):
        if service_name == "bedrock":
            return bedrock_client
        if service_name == "bedrock-agent":
            return bedrock_agent_client
        raise AssertionError(f"unexpected boto3.client call: {service_name}")
    return factory


class TestPromptManagementIntegration:
    """When PROMPT_RESOURCE_ID env var is set, fetch prompt text from Bedrock Prompt Management."""

    def test_uses_specific_version_when_eval_config_provides_one(self):
        """eval_config.prompt_version pins the GetPrompt call to that version."""
        mock_bedrock = make_mock_bedrock()
        mock_agent = MagicMock()
        mock_agent.get_prompt.return_value = _make_get_prompt_response(
            "Answer using {{search_results}} for {{query}}.", version="3"
        )

        event = {**RAG_EVENT, "eval_config": {**RAG_EVENT["eval_config"], "prompt_version": "3"}}

        with (
            patch.object(_mod.boto3, "client", side_effect=_make_clients(mock_bedrock, mock_agent)),
            patch.dict(os.environ, {"PROMPT_RESOURCE_ID": "PR123"}),
        ):
            handler(event, None)

        mock_agent.get_prompt.assert_called_once_with(promptIdentifier="PR123", promptVersion="3")

    def test_resolves_latest_version_when_no_prompt_version(self):
        """No prompt_version in event -> list versions, pick max, fetch that version."""
        mock_bedrock = make_mock_bedrock()
        mock_agent = MagicMock()
        mock_agent.get_prompt.side_effect = [
            {"versions": [{"version": "1"}, {"version": "3"}, {"version": "2"}], "variants": []},
            _make_get_prompt_response("text {{query}}", version="3"),
        ]

        with (
            patch.object(_mod.boto3, "client", side_effect=_make_clients(mock_bedrock, mock_agent)),
            patch.dict(os.environ, {"PROMPT_RESOURCE_ID": "PR123"}),
        ):
            handler(RAG_EVENT, None)

        # First call: no promptVersion. Second: highest version.
        first = mock_agent.get_prompt.call_args_list[0]
        second = mock_agent.get_prompt.call_args_list[1]
        assert "promptVersion" not in first.kwargs
        assert second.kwargs["promptVersion"] == "3"

    def test_falls_back_to_draft_when_no_versions(self):
        """If only DRAFT exists, resolve to DRAFT."""
        mock_bedrock = make_mock_bedrock()
        mock_agent = MagicMock()
        mock_agent.get_prompt.side_effect = [
            {"versions": [], "variants": []},
            _make_get_prompt_response("draft text {{query}}", version="DRAFT"),
        ]

        with (
            patch.object(_mod.boto3, "client", side_effect=_make_clients(mock_bedrock, mock_agent)),
            patch.dict(os.environ, {"PROMPT_RESOURCE_ID": "PR123"}),
        ):
            handler(RAG_EVENT, None)

        assert mock_agent.get_prompt.call_args_list[1].kwargs["promptVersion"] == "DRAFT"

    def test_brace_variables_converted_to_dollar_syntax(self):
        """{{search_results}} and {{query}} must be rewritten to $search_results$ / $query$."""
        mock_bedrock = make_mock_bedrock()
        mock_agent = MagicMock()
        mock_agent.get_prompt.return_value = _make_get_prompt_response(
            "Use {{search_results}} to answer {{query}}.", version="1"
        )

        event = {**RAG_EVENT, "eval_config": {**RAG_EVENT["eval_config"], "prompt_version": "1"}}

        with (
            patch.object(_mod.boto3, "client", side_effect=_make_clients(mock_bedrock, mock_agent)),
            patch.dict(os.environ, {"PROMPT_RESOURCE_ID": "PR123"}),
        ):
            handler(event, None)

        call_kwargs = mock_bedrock.create_evaluation_job.call_args[1]
        sent_template = (
            call_kwargs["inferenceConfig"]["ragConfigs"][0]["knowledgeBaseConfig"]
            ["retrieveAndGenerateConfig"]["knowledgeBaseConfiguration"]
            ["generationConfiguration"]["promptTemplate"]["textPromptTemplate"]
        )
        assert sent_template == "Use $search_results$ to answer $query$."

    def test_no_prompt_template_when_env_var_unset(self):
        """Without PROMPT_RESOURCE_ID set, no prompt management calls and no generationConfiguration."""
        mock_bedrock = make_mock_bedrock()
        mock_agent = MagicMock()

        env_without_prompt = {k: v for k, v in os.environ.items() if k != "PROMPT_RESOURCE_ID"}
        with (
            patch.object(_mod.boto3, "client", side_effect=_make_clients(mock_bedrock, mock_agent)),
            patch.dict(os.environ, env_without_prompt, clear=True),
        ):
            handler(RAG_EVENT, None)

        mock_agent.get_prompt.assert_not_called()
        call_kwargs = mock_bedrock.create_evaluation_job.call_args[1]
        kb_config = (
            call_kwargs["inferenceConfig"]["ragConfigs"][0]["knowledgeBaseConfig"]
            ["retrieveAndGenerateConfig"]["knowledgeBaseConfiguration"]
        )
        assert "generationConfiguration" not in kb_config

    def test_empty_prompt_version_resolves_latest(self):
        """KbSyncCompletionRule passes prompt_version='' — should resolve to latest, not pin to ''."""
        mock_bedrock = make_mock_bedrock()
        mock_agent = MagicMock()
        mock_agent.get_prompt.side_effect = [
            {"versions": [{"version": "2"}], "variants": []},
            _make_get_prompt_response("v2 text", version="2"),
        ]

        event = {**RAG_EVENT, "eval_config": {**RAG_EVENT["eval_config"], "prompt_version": ""}}

        with (
            patch.object(_mod.boto3, "client", side_effect=_make_clients(mock_bedrock, mock_agent)),
            patch.dict(os.environ, {"PROMPT_RESOURCE_ID": "PR123"}),
        ):
            handler(event, None)

        # No version on the first call (listing); '2' on the second (fetch).
        assert "promptVersion" not in mock_agent.get_prompt.call_args_list[0].kwargs
        assert mock_agent.get_prompt.call_args_list[1].kwargs["promptVersion"] == "2"
