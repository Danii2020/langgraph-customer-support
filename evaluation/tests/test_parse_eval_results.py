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
get_evaluation_output_s3_uri = _mod.get_evaluation_output_s3_uri
extract_metric_scores = _mod.extract_metric_scores
compare_against_thresholds = _mod.compare_against_thresholds


def _make_body(data: dict):
    """Create a minimal mock S3 get_object body."""
    body_bytes = json.dumps(data).encode("utf-8")

    class MockBody:
        def read(self):
            return body_bytes

    return {"Body": MockBody()}


# ---------------------------------------------------------------------------
# read_s3_json
# ---------------------------------------------------------------------------

class TestReadS3Json:

    def test_reads_valid_json(self, mock_s3_client, make_s3_response_fixture):
        data = {"averageScores": {"context_relevance": 0.85}}
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

    def test_uri_with_nested_path(self, mock_s3_client, make_s3_response_fixture):
        data = {"key": "value"}
        mock_s3_client.get_object.return_value = make_s3_response_fixture(data)

        read_s3_json(mock_s3_client, "s3://bucket/a/b/c/d.json")

        mock_s3_client.get_object.assert_called_once_with(
            Bucket="bucket", Key="a/b/c/d.json"
        )


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
        mock_bedrock_client.get_evaluation_job.return_value = {
            "outputDataConfig": {}  # s3Uri absent
        }

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
# extract_metric_scores
# ---------------------------------------------------------------------------

class TestExtractMetricScores:

    def test_extracts_from_average_scores_format(self, sample_eval_output_average_scores):
        scores = extract_metric_scores(sample_eval_output_average_scores)
        assert scores["context_relevance"] == 0.85
        assert scores["context_coverage"] == 0.80
        assert scores["faithfulness"] == 0.88

    def test_extracts_from_evaluation_summary_format(self, sample_eval_output_summary):
        scores = extract_metric_scores(sample_eval_output_summary)
        assert scores["context_relevance"] == 0.85
        assert scores["faithfulness"] == 0.88
        assert scores["logical_coherence"] == 0.80

    def test_raises_value_error_on_unknown_format(self):
        with pytest.raises(ValueError, match="does not contain"):
            extract_metric_scores({"someOtherKey": {}})

    def test_raises_value_error_on_non_numeric_score_in_average_scores(self):
        data = {"averageScores": {"context_relevance": "not-a-number"}}
        with pytest.raises(ValueError, match="Non-numeric score"):
            extract_metric_scores(data)

    def test_raises_value_error_on_non_numeric_score_in_summary(self):
        data = {
            "evaluationSummary": {
                "scores": [{"metricName": "context_relevance", "score": "bad"}]
            }
        }
        with pytest.raises(ValueError, match="Non-numeric score"):
            extract_metric_scores(data)

    def test_raises_value_error_when_average_scores_not_dict(self):
        data = {"averageScores": [0.85, 0.80]}
        with pytest.raises(ValueError, match="Expected 'averageScores' to be a dict"):
            extract_metric_scores(data)

    def test_partial_output_with_subset_of_metrics(self):
        data = {"averageScores": {"context_relevance": 0.85}}
        scores = extract_metric_scores(data)
        assert scores == {"context_relevance": 0.85}

    def test_entry_missing_metric_name_in_summary(self):
        data = {
            "evaluationSummary": {
                "scores": [{"score": 0.85}]  # no metricName
            }
        }
        with pytest.raises(ValueError, match="missing 'metricName'"):
            extract_metric_scores(data)

    def test_integer_scores_are_accepted(self):
        data = {"averageScores": {"context_relevance": 1}}
        scores = extract_metric_scores(data)
        assert scores["context_relevance"] == 1.0
        assert isinstance(scores["context_relevance"], float)


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
        # Other metrics should still pass
        assert verdict["results"]["context_relevance"]["passed"] is True

    def test_all_fail(self, all_failing_scores, flat_thresholds):
        verdict = compare_against_thresholds(all_failing_scores, flat_thresholds)
        assert verdict["passed"] is False
        assert len(verdict["failed_metrics"]) == len(flat_thresholds)

    def test_score_equals_threshold_passes(self):
        """Boundary: score == threshold must be treated as passing (contract C5)."""
        scores = {"context_relevance": 0.78}
        thresholds = {"context_relevance": 0.78}
        verdict = compare_against_thresholds(scores, thresholds)
        assert verdict["passed"] is True
        assert verdict["results"]["context_relevance"]["passed"] is True

    def test_score_just_below_threshold_fails(self):
        scores = {"context_relevance": 0.7799}
        thresholds = {"context_relevance": 0.78}
        verdict = compare_against_thresholds(scores, thresholds)
        assert verdict["passed"] is False
        assert "context_relevance" in verdict["failed_metrics"]

    def test_missing_score_treated_as_zero_and_fails(self):
        """A metric in thresholds with no corresponding score should fail."""
        scores = {}  # empty -- no scores provided
        thresholds = {"context_relevance": 0.78}
        verdict = compare_against_thresholds(scores, thresholds)
        assert verdict["passed"] is False
        assert verdict["results"]["context_relevance"]["score"] == 0.0
        assert verdict["results"]["context_relevance"]["passed"] is False

    def test_verdict_structure_is_complete(self, passing_scores, flat_thresholds):
        verdict = compare_against_thresholds(passing_scores, flat_thresholds)
        assert "passed" in verdict
        assert "results" in verdict
        assert "failed_metrics" in verdict
        for metric in flat_thresholds:
            assert metric in verdict["results"]
            m = verdict["results"][metric]
            assert "score" in m
            assert "threshold" in m
            assert "passed" in m

    def test_empty_thresholds_returns_all_pass(self):
        verdict = compare_against_thresholds({"context_relevance": 0.85}, {})
        assert verdict["passed"] is True
        assert verdict["results"] == {}
        assert verdict["failed_metrics"] == []


# ---------------------------------------------------------------------------
# handler (end-to-end integration test with mocked dependencies)
# ---------------------------------------------------------------------------

class TestHandler:

    def test_handler_returns_passing_verdict(
        self, sample_thresholds, sample_retrieval_only_output, sample_rag_output
    ):
        event = {
            "retrieval_only_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/ro-job",
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/rag-job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        }

        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.side_effect = [
            {"outputDataConfig": {"s3Uri": "s3://bucket/results/ro/output.json"}},
            {"outputDataConfig": {"s3Uri": "s3://bucket/results/rag/output.json"}},
        ]

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = KeyError
        mock_s3.get_object.side_effect = [
            _make_body(sample_thresholds),
            _make_body(sample_retrieval_only_output),
            _make_body(sample_rag_output),
        ]

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            result = handler(event, None)

        assert result["passed"] is True
        assert result["failed_metrics"] == []
        assert "context_relevance" in result["results"]
        assert "faithfulness" in result["results"]

    def test_handler_returns_failing_verdict_when_metric_below_threshold(
        self, sample_thresholds
    ):
        event = {
            "retrieval_only_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/ro-job",
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/rag-job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        }

        retrieval_output = {"averageScores": {"context_relevance": 0.85, "context_coverage": 0.80}}
        rag_output = {
            "averageScores": {
                "faithfulness": 0.71,  # below 0.82 threshold
                "correctness": 0.81,
                "completeness": 0.76,
                "helpfulness": 0.75,
                "logical_coherence": 0.80,
            }
        }

        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.side_effect = [
            {"outputDataConfig": {"s3Uri": "s3://bucket/results/ro/output.json"}},
            {"outputDataConfig": {"s3Uri": "s3://bucket/results/rag/output.json"}},
        ]

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = KeyError
        mock_s3.get_object.side_effect = [
            _make_body(sample_thresholds),
            _make_body(retrieval_output),
            _make_body(rag_output),
        ]

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            result = handler(event, None)

        assert result["passed"] is False
        assert "faithfulness" in result["failed_metrics"]

    def test_handler_raises_key_error_when_retrieval_arn_missing(self):
        event = {
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:...",
            "thresholds_s3_uri": "s3://bucket/thresholds.json",
        }
        with pytest.raises(KeyError, match="retrieval_only_job_arn"):
            handler(event, None)

    def test_handler_raises_key_error_when_rag_arn_missing(self):
        event = {
            "retrieval_only_job_arn": "arn:aws:bedrock:...",
            "thresholds_s3_uri": "s3://bucket/thresholds.json",
        }
        with pytest.raises(KeyError, match="retrieve_and_generate_job_arn"):
            handler(event, None)

    def test_handler_raises_key_error_when_thresholds_uri_missing(self):
        event = {
            "retrieval_only_job_arn": "arn:aws:bedrock:...",
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:...",
        }
        with pytest.raises(KeyError, match="thresholds_s3_uri"):
            handler(event, None)

    def test_handler_raises_on_missing_s3_file(self, sample_thresholds):
        event = {
            "retrieval_only_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/ro-job",
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/rag-job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        }

        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.return_value = {
            "outputDataConfig": {"s3Uri": "s3://bucket/results/output.json"}
        }

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = FileNotFoundError
        mock_s3.get_object.side_effect = FileNotFoundError("NoSuchKey")

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            with pytest.raises((FileNotFoundError, RuntimeError)):
                handler(event, None)

    def test_handler_raises_on_invalid_bedrock_job_arn(self):
        event = {
            "retrieval_only_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/ro-job",
            "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:123:evaluation-job/rag-job",
            "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        }

        mock_bedrock = MagicMock()
        mock_bedrock.get_evaluation_job.side_effect = Exception("ResourceNotFoundException")

        mock_s3 = MagicMock()
        mock_s3.exceptions = MagicMock()
        mock_s3.exceptions.NoSuchKey = KeyError
        mock_s3.get_object.return_value = _make_body(
            {"retrieval_only": {}, "retrieve_and_generate": {}}
        )

        def fake_client(service, **kwargs):
            return mock_bedrock if service == "bedrock" else mock_s3

        with patch.object(_mod.boto3, "client", side_effect=fake_client):
            with pytest.raises(RuntimeError, match="Failed to get evaluation job"):
                handler(event, None)
