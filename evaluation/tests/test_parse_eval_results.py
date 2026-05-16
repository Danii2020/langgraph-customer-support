"""
Unit tests for evaluation/lambdas/parse_eval_results/handler.py
"""
import importlib.util
import json
import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Load the Lambda handler module by absolute path to avoid name collisions
# with other handler.py files in the evaluation/lambdas/* directories.
_HANDLER_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "lambdas", "parse_eval_results", "handler.py")
)
_spec = importlib.util.spec_from_file_location("parse_eval_results_handler", _HANDLER_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["parse_eval_results_handler"] = _mod
_spec.loader.exec_module(_mod)

handler = _mod.handler
read_s3_json = _mod.read_s3_json
read_s3_jsonl = _mod.read_s3_jsonl
get_evaluation_output_s3_uri = _mod.get_evaluation_output_s3_uri
find_output_jsonl_uri = _mod.find_output_jsonl_uri
extract_metric_scores = _mod.extract_metric_scores
compare_against_thresholds = _mod.compare_against_thresholds
normalize_metric_name = _mod.normalize_metric_name


def _make_body(data: dict):
    body_bytes = json.dumps(data).encode("utf-8")

    class MockBody:
        def read(self):
            return body_bytes

    return {"Body": MockBody()}


def _make_jsonl_body(records: list):
    body_bytes = ("\n".join(json.dumps(r) for r in records)).encode("utf-8")

    class MockBody:
        def read(self):
            return body_bytes

    return {"Body": MockBody()}


def _make_paginator(pages):
    """Build a fake list_objects_v2 paginator that yields the given pages."""
    paginator = MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


# ---------------------------------------------------------------------------
# read_s3_json
# ---------------------------------------------------------------------------

class TestReadS3Json:

    def test_reads_valid_json(self, mock_s3_client, make_s3_response_fixture):
        data = {"retrieve_and_generate": {"faithfulness": 0.82}}
        mock_s3_client.get_object.return_value = make_s3_response_fixture(data)

        result = read_s3_json(mock_s3_client, "s3://my-bucket/path/to/file.json")

        mock_s3_client.get_object.assert_called_once_with(
            Bucket="my-bucket", Key="path/to/file.json"
        )
        assert result == data

    def test_raises_value_error_for_invalid_uri_no_prefix(self, mock_s3_client):
        with pytest.raises(ValueError, match="Invalid S3 URI format"):
            read_s3_json(mock_s3_client, "my-bucket/path/file.json")

    def test_raises_value_error_for_invalid_uri_no_key(self, mock_s3_client):
        with pytest.raises(ValueError, match="Invalid S3 URI format"):
            read_s3_json(mock_s3_client, "s3://my-bucket")

    def test_raises_file_not_found_for_missing_key(self, mock_s3_client):
        mock_s3_client.get_object.side_effect = KeyError("NoSuchKey")
        mock_s3_client.exceptions.NoSuchKey = KeyError

        with pytest.raises(FileNotFoundError):
            read_s3_json(mock_s3_client, "s3://my-bucket/missing.json")

    def test_raises_value_error_for_malformed_json(self, mock_s3_client):
        class MockBody:
            def read(self):
                return b"not-valid-json{"

        mock_s3_client.get_object.return_value = {"Body": MockBody()}

        with pytest.raises(ValueError, match="Malformed JSON"):
            read_s3_json(mock_s3_client, "s3://my-bucket/bad.json")

    def test_raises_runtime_error_for_generic_s3_error(self, mock_s3_client):
        mock_s3_client.get_object.side_effect = Exception("S3 connection error")

        with pytest.raises(RuntimeError, match="Failed to read S3 object"):
            read_s3_json(mock_s3_client, "s3://my-bucket/file.json")


# ---------------------------------------------------------------------------
# read_s3_jsonl
# ---------------------------------------------------------------------------

class TestReadS3Jsonl:

    def test_reads_multiple_records(self, mock_s3_client):
        records = [{"a": 1}, {"a": 2}, {"a": 3}]
        mock_s3_client.get_object.return_value = _make_jsonl_body(records)

        result = read_s3_jsonl(mock_s3_client, "s3://b/k.jsonl")

        assert result == records

    def test_skips_blank_lines(self, mock_s3_client):
        body_bytes = b'{"a":1}\n\n{"a":2}\n'

        class MockBody:
            def read(self):
                return body_bytes

        mock_s3_client.get_object.return_value = {"Body": MockBody()}

        result = read_s3_jsonl(mock_s3_client, "s3://b/k.jsonl")
        assert result == [{"a": 1}, {"a": 2}]

    def test_raises_on_malformed_line(self, mock_s3_client):
        body_bytes = b'{"a":1}\n{not json}\n'

        class MockBody:
            def read(self):
                return body_bytes

        mock_s3_client.get_object.return_value = {"Body": MockBody()}

        with pytest.raises(ValueError, match="Malformed JSONL"):
            read_s3_jsonl(mock_s3_client, "s3://b/k.jsonl")


# ---------------------------------------------------------------------------
# find_output_jsonl_uri
# ---------------------------------------------------------------------------

class TestFindOutputJsonlUri:

    def test_finds_nested_output_jsonl(self, mock_s3_client):
        nested_key = (
            "results/rag/kb-eval-retrieve-and-generate-20260422/job-id/"
            "inference_configs/0/datasets/RagDataset/abc123_output.jsonl"
        )
        pages = [{"Contents": [
            {"Key": "results/rag/kb-eval-retrieve-and-generate-20260422/job-id/manifest.json"},
            {"Key": nested_key},
        ]}]
        mock_s3_client.get_paginator.return_value = _make_paginator(pages)

        result = find_output_jsonl_uri(
            mock_s3_client,
            "s3://rag-evaluation-results-acct-region/results/rag/",
            "job-id",
        )

        mock_s3_client.get_paginator.assert_called_once_with("list_objects_v2")
        assert result == f"s3://rag-evaluation-results-acct-region/{nested_key}"

    def test_appends_trailing_slash_if_missing(self, mock_s3_client):
        pages = [{"Contents": [{"Key": "results/rag/jobX/x_output.jsonl"}]}]
        mock_s3_client.get_paginator.return_value = _make_paginator(pages)

        find_output_jsonl_uri(mock_s3_client, "s3://bucket/results/rag", "jobX")

        # Verify the prefix sent to paginate ended with /
        call_kwargs = mock_s3_client.get_paginator.return_value.paginate.call_args[1]
        assert call_kwargs["Prefix"].endswith("/")

    def test_raises_when_no_jsonl_found(self, mock_s3_client):
        pages = [{"Contents": [{"Key": "results/rag/manifest.json"}]}]
        mock_s3_client.get_paginator.return_value = _make_paginator(pages)

        with pytest.raises(FileNotFoundError, match="_output.jsonl"):
            find_output_jsonl_uri(mock_s3_client, "s3://bucket/results/rag/", "jobX")

    def test_raises_when_listing_fails(self, mock_s3_client):
        mock_s3_client.get_paginator.side_effect = Exception("AccessDenied")

        with pytest.raises(RuntimeError, match="Failed to list S3 objects"):
            find_output_jsonl_uri(mock_s3_client, "s3://bucket/prefix/", "jobX")

    def test_filters_by_job_id_when_multiple_sibling_jobs_exist(self, mock_s3_client):
        """Real-world scenario: same output prefix, multiple completed jobs.
        Without job_id filtering, the first JSONL (oldest run) was returned,
        causing the email to report stale metrics from a prior eval.
        """
        older_key = (
            "results/retrieval/kb-eval-retrieve-only-20260513224113/un7fcmg4hlnf/"
            "inference_configs/0/datasets/RetrievalDataset/aaa_output.jsonl"
        )
        target_key = (
            "results/retrieval/kb-eval-retrieve-only-20260514032412/w08u6tmqhlkj/"
            "inference_configs/0/datasets/RetrievalDataset/bbb_output.jsonl"
        )
        pages = [{"Contents": [{"Key": older_key}, {"Key": target_key}]}]
        mock_s3_client.get_paginator.return_value = _make_paginator(pages)

        result = find_output_jsonl_uri(
            mock_s3_client,
            "s3://eval-bucket/results/retrieval/",
            "w08u6tmqhlkj",
        )
        assert result == f"s3://eval-bucket/{target_key}"

    def test_does_not_match_job_id_as_substring_of_a_different_id(self, mock_s3_client):
        """Job-id filter must require slash-delimited boundaries; 'abc' must
        not match a key containing 'abcdef'."""
        wrong_key = (
            "results/r/kb-eval-x/abcdef9999/"
            "inference_configs/0/datasets/X/out_output.jsonl"
        )
        pages = [{"Contents": [{"Key": wrong_key}]}]
        mock_s3_client.get_paginator.return_value = _make_paginator(pages)

        with pytest.raises(FileNotFoundError):
            find_output_jsonl_uri(mock_s3_client, "s3://b/results/r/", "abc")


# ---------------------------------------------------------------------------
# get_evaluation_output_s3_uri
# ---------------------------------------------------------------------------

class TestGetEvaluationOutputS3Uri:

    def test_extracts_uri_from_valid_response(self, mock_bedrock_client):
        mock_bedrock_client.get_evaluation_job.return_value = {
            "outputDataConfig": {"s3Uri": "s3://bucket/output/job-123/"}
        }

        result = get_evaluation_output_s3_uri(
            mock_bedrock_client,
            "arn:aws:bedrock:us-east-2:123456789:evaluation-job/job-123",
        )

        assert result == "s3://bucket/output/job-123/"
        mock_bedrock_client.get_evaluation_job.assert_called_once_with(
            jobIdentifier="arn:aws:bedrock:us-east-2:123456789:evaluation-job/job-123"
        )

    def test_raises_runtime_error_on_api_failure(self, mock_bedrock_client):
        mock_bedrock_client.get_evaluation_job.side_effect = Exception("AccessDenied")

        with pytest.raises(RuntimeError, match="Failed to get evaluation job"):
            get_evaluation_output_s3_uri(
                mock_bedrock_client,
                "arn:aws:bedrock:us-east-2:123:evaluation-job/job-1",
            )

    def test_raises_value_error_when_uri_missing(self, mock_bedrock_client):
        mock_bedrock_client.get_evaluation_job.return_value = {"outputDataConfig": {}}

        with pytest.raises(ValueError, match="Output S3 URI not found"):
            get_evaluation_output_s3_uri(
                mock_bedrock_client,
                "arn:aws:bedrock:us-east-2:123:evaluation-job/job-1",
            )

    def test_raises_value_error_when_output_data_config_missing(self, mock_bedrock_client):
        mock_bedrock_client.get_evaluation_job.return_value = {}

        with pytest.raises(ValueError, match="Output S3 URI not found"):
            get_evaluation_output_s3_uri(
                mock_bedrock_client,
                "arn:aws:bedrock:us-east-2:123:evaluation-job/job-1",
            )


# ---------------------------------------------------------------------------
# normalize_metric_name
# ---------------------------------------------------------------------------

class TestNormalizeMetricName:

    def test_strips_builtin_prefix_and_lowercases(self):
        assert normalize_metric_name("Builtin.Faithfulness") == "faithfulness"

    def test_converts_pascal_case_to_snake_case(self):
        assert normalize_metric_name("Builtin.LogicalCoherence") == "logical_coherence"

    def test_handles_name_without_prefix(self):
        assert normalize_metric_name("Faithfulness") == "faithfulness"

    def test_normalizes_context_relevance(self):
        """Retrieve-only metric: Builtin.ContextRelevance → context_relevance."""
        assert normalize_metric_name("Builtin.ContextRelevance") == "context_relevance"

    def test_normalizes_context_coverage(self):
        """Retrieve-only metric: Builtin.ContextCoverage → context_coverage."""
        assert normalize_metric_name("Builtin.ContextCoverage") == "context_coverage"


# ---------------------------------------------------------------------------
# extract_metric_scores
# ---------------------------------------------------------------------------

class TestExtractMetricScores:

    def test_averages_across_records(self, sample_rag_jsonl_records):
        scores = extract_metric_scores(sample_rag_jsonl_records)

        # Faithfulness: (0.90 + 0.86) / 2 = 0.88
        assert scores["faithfulness"] == pytest.approx(0.88)
        # LogicalCoherence: (0.82 + 0.78) / 2 = 0.80
        assert scores["logical_coherence"] == pytest.approx(0.80)
        assert scores["correctness"] == pytest.approx(0.81)

    def test_normalizes_metric_names(self):
        records = [
            {"conversationTurns": [
                {"results": [{"metricName": "Builtin.Helpfulness", "result": 0.5}]}
            ]},
        ]
        scores = extract_metric_scores(records)
        assert "helpfulness" in scores
        assert "Builtin.Helpfulness" not in scores

    def test_skips_entries_with_missing_fields(self):
        records = [{"conversationTurns": [
            {"results": [
                {"metricName": "Builtin.Faithfulness", "result": 0.9},
                {"metricName": None, "result": 0.5},  # skipped
                {"metricName": "Builtin.Correctness"},  # skipped (no result)
            ]}
        ]}]
        scores = extract_metric_scores(records)
        assert scores == {"faithfulness": 0.9}

    def test_empty_records_returns_empty(self):
        assert extract_metric_scores([]) == {}

    def test_raises_on_non_numeric_result(self):
        records = [{"conversationTurns": [
            {"results": [{"metricName": "Builtin.Faithfulness", "result": "bad"}]}
        ]}]
        with pytest.raises(ValueError, match="Non-numeric score"):
            extract_metric_scores(records)


# ---------------------------------------------------------------------------
# compare_against_thresholds
# ---------------------------------------------------------------------------

class TestCompareAgainstThresholds:

    def test_all_pass(self, passing_scores, flat_thresholds):
        verdict = compare_against_thresholds(passing_scores, flat_thresholds)
        assert verdict["passed"] is True
        assert verdict["failed_metrics"] == []
        for metric in flat_thresholds:
            assert verdict["results"][metric]["passed"] is True

    def test_some_fail(self, failing_scores, flat_thresholds):
        verdict = compare_against_thresholds(failing_scores, flat_thresholds)
        assert verdict["passed"] is False
        assert "faithfulness" in verdict["failed_metrics"]
        assert verdict["results"]["faithfulness"]["passed"] is False
        assert verdict["results"]["correctness"]["passed"] is True

    def test_all_fail(self, all_failing_scores, flat_thresholds):
        verdict = compare_against_thresholds(all_failing_scores, flat_thresholds)
        assert verdict["passed"] is False
        assert len(verdict["failed_metrics"]) == len(flat_thresholds)

    def test_score_equals_threshold_passes(self):
        verdict = compare_against_thresholds({"faithfulness": 0.82}, {"faithfulness": 0.82})
        assert verdict["passed"] is True
        assert verdict["results"]["faithfulness"]["passed"] is True

    def test_score_just_below_threshold_fails(self):
        verdict = compare_against_thresholds({"faithfulness": 0.8199}, {"faithfulness": 0.82})
        assert verdict["passed"] is False
        assert "faithfulness" in verdict["failed_metrics"]

    def test_missing_score_treated_as_zero_and_fails(self):
        verdict = compare_against_thresholds({}, {"faithfulness": 0.82})
        assert verdict["passed"] is False
        assert verdict["results"]["faithfulness"]["score"] == 0.0
        assert verdict["results"]["faithfulness"]["passed"] is False

    def test_empty_thresholds_returns_all_pass(self):
        verdict = compare_against_thresholds({"faithfulness": 0.85}, {})
        assert verdict["passed"] is True
        assert verdict["results"] == {}
        assert verdict["failed_metrics"] == []


# ---------------------------------------------------------------------------
# handler (end-to-end with mocked S3 + Bedrock)
# ---------------------------------------------------------------------------

class TestHandler:

    def _wire_mocks(self, sample_thresholds, jsonl_records, jsonl_key="results/rag/job/x_output.jsonl"):
        """Build mocked bedrock + s3 clients for a successful flow."""
        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.return_value = {
            "outputDataConfig": {"s3Uri": "s3://bucket/results/rag/"}
        }

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = KeyError
        mock_s3.get_paginator.return_value = _make_paginator(
            [{"Contents": [{"Key": jsonl_key}]}]
        )
        # First get_object: thresholds JSON. Second: JSONL payload.
        mock_s3.get_object.side_effect = [
            _make_body(sample_thresholds),
            _make_jsonl_body(jsonl_records),
        ]
        return mock_bedrock, mock_s3

    def test_handler_returns_passing_verdict(self, sample_thresholds, sample_rag_jsonl_records):
        event = {
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        }
        mock_bedrock, mock_s3 = self._wire_mocks(sample_thresholds, sample_rag_jsonl_records)

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            result = handler(event, None)

        assert result["passed"] is True
        assert result["failed_metrics"] == []
        assert "faithfulness" in result["results"]

    def test_handler_returns_failing_verdict_when_metric_below_threshold(
        self, sample_thresholds, failing_rag_jsonl_records
    ):
        event = {
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        }
        mock_bedrock, mock_s3 = self._wire_mocks(sample_thresholds, failing_rag_jsonl_records)

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            result = handler(event, None)

        assert result["passed"] is False
        assert "faithfulness" in result["failed_metrics"]

    def test_handler_raises_key_error_when_rag_arn_missing(self):
        with pytest.raises(KeyError, match="retrieve_and_generate_job_arn"):
            handler({"thresholds_s3_uri": "s3://bucket/thresholds.json"}, None)

    def test_handler_raises_key_error_when_thresholds_uri_missing(self):
        with pytest.raises(KeyError, match="thresholds_s3_uri"):
            handler({"retrieve_and_generate_job_arn": "arn:aws:bedrock:..."}, None)

    def test_handler_raises_when_no_jsonl_under_prefix(self, sample_thresholds):
        event = {
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        }

        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.return_value = {
            "outputDataConfig": {"s3Uri": "s3://bucket/results/rag/"}
        }

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = KeyError
        mock_s3.get_object.return_value = _make_body(sample_thresholds)
        # No matching *_output.jsonl in the listing
        mock_s3.get_paginator.return_value = _make_paginator(
            [{"Contents": [{"Key": "results/rag/manifest.json"}]}]
        )

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            with pytest.raises(FileNotFoundError, match="_output.jsonl"):
                handler(event, None)

    def test_handler_raises_on_invalid_bedrock_job_arn(self):
        event = {
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        }

        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.side_effect = Exception("ResourceNotFoundException")

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = KeyError
        mock_s3.get_object.return_value = _make_body({"retrieve_and_generate": {}})

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            with pytest.raises(RuntimeError, match="Failed to get evaluation job"):
                handler(event, None)


# ---------------------------------------------------------------------------
# thresholds_subkey: retrieve-only branch
# ---------------------------------------------------------------------------

class TestThresholdsSubkey:
    """
    The retrieve-only branch of the state machine passes
    thresholds_subkey='retrieve_only' so the handler reads its own
    thresholds block from the shared (or separate) JSON file.
    """

    def _build_mocks(self, thresholds_data: dict, jsonl_records: list[dict]):
        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.return_value = {
            "outputDataConfig": {"s3Uri": "s3://bucket/results/retrieval/"}
        }
        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = KeyError
        mock_s3.get_paginator.return_value = _make_paginator(
            [{"Contents": [{"Key": "results/retrieval/job/x_output.jsonl"}]}]
        )
        mock_s3.get_object.side_effect = [
            _make_body(thresholds_data),
            _make_jsonl_body(jsonl_records),
        ]
        return mock_bedrock, mock_s3

    def test_reads_retrieve_only_block_when_subkey_passed(self):
        thresholds = {
            "retrieve_and_generate": {"faithfulness": 0.95},  # would FAIL if read
            "retrieve_only": {"context_relevance": 0.5, "context_coverage": 0.5},
        }
        jsonl = [{
            "conversationTurns": [{
                "results": [
                    {"metricName": "Builtin.ContextRelevance", "result": 0.8},
                    {"metricName": "Builtin.ContextCoverage", "result": 0.7},
                ]
            }]
        }]
        event = {
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-1:123:evaluation-job/job",
            "thresholds_s3_uri": "s3://bucket/baselines/retrieval_thresholds.json",
            "thresholds_subkey": "retrieve_only",
        }
        mock_bedrock, mock_s3 = self._build_mocks(thresholds, jsonl)

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            result = handler(event, None)

        assert result["passed"] is True
        assert "context_relevance" in result["results"]
        assert "context_coverage" in result["results"]
        # The RAG faithfulness threshold must NOT have been applied.
        assert "faithfulness" not in result["results"]

    def test_defaults_to_retrieve_and_generate_when_subkey_absent(self):
        """Backward-compat: no thresholds_subkey → reads 'retrieve_and_generate'."""
        thresholds = {
            "retrieve_and_generate": {"faithfulness": 0.5},
            "retrieve_only": {"context_relevance": 0.95},  # would FAIL if read
        }
        jsonl = [{
            "conversationTurns": [{
                "results": [{"metricName": "Builtin.Faithfulness", "result": 0.9}]
            }]
        }]
        event = {
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-1:123:evaluation-job/job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
            # thresholds_subkey intentionally omitted
        }
        mock_bedrock, mock_s3 = self._build_mocks(thresholds, jsonl)

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            result = handler(event, None)

        assert result["passed"] is True
        assert "faithfulness" in result["results"]

    def test_empty_subkey_treated_as_default(self):
        """An empty-string thresholds_subkey should not break threshold lookup."""
        thresholds = {"retrieve_and_generate": {"faithfulness": 0.5}}
        jsonl = [{
            "conversationTurns": [{
                "results": [{"metricName": "Builtin.Faithfulness", "result": 0.9}]
            }]
        }]
        event = {
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-1:123:evaluation-job/job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
            "thresholds_subkey": "",
        }
        mock_bedrock, mock_s3 = self._build_mocks(thresholds, jsonl)

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            result = handler(event, None)

        assert result["passed"] is True
