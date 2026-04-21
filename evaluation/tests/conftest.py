"""
Shared pytest fixtures for the RAG Evaluation Pipeline unit tests.
"""
import json
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_thresholds():
    """Baseline threshold configuration matching evaluation/config/thresholds.json."""
    return {
        "retrieval_only": {
            "context_relevance": 0.78,
            "context_coverage": 0.75,
        },
        "retrieve_and_generate": {
            "faithfulness": 0.82,
            "correctness": 0.78,
            "completeness": 0.72,
            "helpfulness": 0.73,
            "logical_coherence": 0.78,
        },
    }


@pytest.fixture
def flat_thresholds():
    """All thresholds merged into a single flat dict (as used by compare_against_thresholds)."""
    return {
        "context_relevance": 0.78,
        "context_coverage": 0.75,
        "faithfulness": 0.82,
        "correctness": 0.78,
        "completeness": 0.72,
        "helpfulness": 0.73,
        "logical_coherence": 0.78,
    }


@pytest.fixture
def sample_eval_output_average_scores():
    """Bedrock evaluation output with averageScores format -- all metrics passing."""
    return {
        "averageScores": {
            "context_relevance": 0.85,
            "context_coverage": 0.80,
            "faithfulness": 0.88,
            "correctness": 0.81,
            "completeness": 0.76,
            "helpfulness": 0.75,
            "logical_coherence": 0.80,
        }
    }


@pytest.fixture
def sample_eval_output_summary():
    """Bedrock evaluation output with evaluationSummary.scores format."""
    return {
        "evaluationSummary": {
            "scores": [
                {"metricName": "context_relevance", "score": 0.85},
                {"metricName": "context_coverage", "score": 0.80},
                {"metricName": "faithfulness", "score": 0.88},
                {"metricName": "correctness", "score": 0.81},
                {"metricName": "completeness", "score": 0.76},
                {"metricName": "helpfulness", "score": 0.75},
                {"metricName": "logical_coherence", "score": 0.80},
            ]
        }
    }


@pytest.fixture
def sample_retrieval_only_output():
    """Bedrock evaluation output for retrieval-only job (averageScores format)."""
    return {
        "averageScores": {
            "context_relevance": 0.85,
            "context_coverage": 0.80,
        }
    }


@pytest.fixture
def sample_rag_output():
    """Bedrock evaluation output for retrieve-and-generate job (averageScores format)."""
    return {
        "averageScores": {
            "faithfulness": 0.88,
            "correctness": 0.81,
            "completeness": 0.76,
            "helpfulness": 0.75,
            "logical_coherence": 0.80,
        }
    }


@pytest.fixture
def passing_scores():
    """Score dict where all metrics pass their thresholds."""
    return {
        "context_relevance": 0.85,
        "context_coverage": 0.80,
        "faithfulness": 0.88,
        "correctness": 0.81,
        "completeness": 0.76,
        "helpfulness": 0.75,
        "logical_coherence": 0.80,
    }


@pytest.fixture
def failing_scores():
    """Score dict where faithfulness fails its threshold."""
    return {
        "context_relevance": 0.85,
        "context_coverage": 0.80,
        "faithfulness": 0.71,  # below threshold 0.82
        "correctness": 0.81,
        "completeness": 0.76,
        "helpfulness": 0.75,
        "logical_coherence": 0.80,
    }


@pytest.fixture
def all_failing_scores():
    """Score dict where every metric is below threshold."""
    return {
        "context_relevance": 0.50,
        "context_coverage": 0.50,
        "faithfulness": 0.50,
        "correctness": 0.50,
        "completeness": 0.50,
        "helpfulness": 0.50,
        "logical_coherence": 0.50,
    }


# ---------------------------------------------------------------------------
# Mock boto3 client fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_s3_client():
    """MagicMock for a boto3 S3 client."""
    client = MagicMock()
    # Set up exceptions so that NoSuchKey can be referenced as an attribute
    client.exceptions = MagicMock()
    client.exceptions.NoSuchKey = KeyError
    return client


@pytest.fixture
def mock_bedrock_client():
    """MagicMock for a boto3 Bedrock client."""
    return MagicMock()


def make_s3_response(data: dict) -> dict:
    """Helper: create a mock S3 get_object response for the given dict."""
    import io
    body_bytes = json.dumps(data).encode("utf-8")

    class MockStreamingBody:
        def read(self):
            return body_bytes

    return {"Body": MockStreamingBody()}


@pytest.fixture
def make_s3_response_fixture():
    """Return the make_s3_response helper as a fixture."""
    return make_s3_response
