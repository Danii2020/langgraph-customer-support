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
    """All thresholds as a flat dict (as used by compare_against_thresholds)."""
    return {
        "faithfulness": 0.82,
        "correctness": 0.78,
        "completeness": 0.72,
        "helpfulness": 0.73,
        "logical_coherence": 0.78,
    }


def _make_turn(scores: dict[str, float]) -> dict:
    """Build one Bedrock RAG conversationTurn record with the given metric scores."""
    return {
        "conversationTurns": [
            {
                "results": [
                    {"metricName": metric, "result": value}
                    for metric, value in scores.items()
                ]
            }
        ]
    }


@pytest.fixture
def sample_rag_jsonl_records():
    """Two-record Bedrock RAG output averaging to the passing scores below."""
    return [
        _make_turn({
            "Builtin.Faithfulness": 0.90,
            "Builtin.Correctness": 0.82,
            "Builtin.Completeness": 0.78,
            "Builtin.Helpfulness": 0.76,
            "Builtin.LogicalCoherence": 0.82,
        }),
        _make_turn({
            "Builtin.Faithfulness": 0.86,
            "Builtin.Correctness": 0.80,
            "Builtin.Completeness": 0.74,
            "Builtin.Helpfulness": 0.74,
            "Builtin.LogicalCoherence": 0.78,
        }),
    ]


@pytest.fixture
def failing_rag_jsonl_records():
    """RAG records where faithfulness averages below the 0.82 threshold."""
    return [
        _make_turn({
            "Builtin.Faithfulness": 0.60,
            "Builtin.Correctness": 0.82,
            "Builtin.Completeness": 0.78,
            "Builtin.Helpfulness": 0.76,
            "Builtin.LogicalCoherence": 0.82,
        }),
    ]


@pytest.fixture
def passing_scores():
    """Score dict where all metrics pass their thresholds."""
    return {
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
    body_bytes = json.dumps(data).encode("utf-8")

    class MockStreamingBody:
        def read(self):
            return body_bytes

    return {"Body": MockStreamingBody()}


def make_s3_jsonl_response(records: list[dict]) -> dict:
    """Helper: create a mock S3 get_object response with one JSON record per line."""
    body_bytes = ("\n".join(json.dumps(r) for r in records)).encode("utf-8")

    class MockStreamingBody:
        def read(self):
            return body_bytes

    return {"Body": MockStreamingBody()}


@pytest.fixture
def make_s3_response_fixture():
    """Return the make_s3_response helper as a fixture."""
    return make_s3_response


@pytest.fixture
def make_s3_jsonl_response_fixture():
    """Return the make_s3_jsonl_response helper as a fixture."""
    return make_s3_jsonl_response


# ---------------------------------------------------------------------------
# CloudFormation custom resource helpers (for seed_eval_assets tests)
# ---------------------------------------------------------------------------

def make_cfn_event(
    request_type: str,
    properties: dict | None = None,
    old_properties: dict | None = None,
    response_url: str = "https://cfn-response-url.example.com/response",
    stack_id: str = "arn:aws:cloudformation:us-east-1:123456789012:stack/rag-eval-pipeline/abc",
    request_id: str = "req-001",
    logical_resource_id: str = "SeedEvalAssetsCustomResource",
    physical_resource_id: str = "seed-eval-assets-resource",
) -> dict:
    """Build a synthetic CloudFormation custom resource event for seed_eval_assets tests."""
    if properties is None:
        properties = {
            "EvalBucketName": "my-eval-bucket",
            "ResultsBucketName": "my-results-bucket",
            "Region": "us-east-1",
        }
    event = {
        "RequestType": request_type,
        "ResponseURL": response_url,
        "StackId": stack_id,
        "RequestId": request_id,
        "LogicalResourceId": logical_resource_id,
        "PhysicalResourceId": physical_resource_id,
        "ResourceProperties": properties,
    }
    if old_properties is not None:
        event["OldResourceProperties"] = old_properties
    elif request_type == "Update":
        # Default OldResourceProperties = same as new (no-op)
        event["OldResourceProperties"] = properties.copy()
    return event


@pytest.fixture
def mock_cfn_client():
    """MagicMock for a boto3 CloudFormation client with a default EvalBucketName output."""
    client = MagicMock()
    client.describe_stacks.return_value = {
        "Stacks": [
            {
                "StackName": "rag-eval-pipeline",
                "StackStatus": "CREATE_COMPLETE",
                "Outputs": [
                    {
                        "OutputKey": "EvalBucketName",
                        "OutputValue": "rag-eval-pipeline-eval-123456789012-us-east-1",
                        "Description": "Resolved eval bucket name",
                    },
                ],
            }
        ]
    }
    return client
