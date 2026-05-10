"""
Pytest fixtures for KB Provisioning custom resource Lambda tests.
"""
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_s3_client():
    """MagicMock boto3 S3 client with sensible defaults."""
    client = MagicMock()
    # list_objects_v2 returns empty by default (no objects to delete)
    client.get_paginator.return_value.paginate.return_value = iter([{"Contents": []}])
    # put_object and delete_objects succeed silently
    client.put_object.return_value = {}
    client.delete_objects.return_value = {"Deleted": [], "Errors": []}
    return client


@pytest.fixture
def mock_bedrock_agent_client():
    """MagicMock boto3 bedrock-agent client."""
    client = MagicMock()
    client.start_ingestion_job.return_value = {
        "ingestionJob": {
            "ingestionJobId": "test-job-id-001",
            "knowledgeBaseId": "KB123",
            "dataSourceId": "DS456",
            "status": "STARTING",
        }
    }
    return client


def make_cfn_event(
    request_type: str,
    properties: dict | None = None,
    old_properties: dict | None = None,
    response_url: str = "https://cfn-response-url.example.com/response",
    stack_id: str = "arn:aws:cloudformation:us-east-1:123456789012:stack/kb-provisioning/abc",
    request_id: str = "req-001",
    logical_resource_id: str = "SeedAndIngestCustomResource",
    physical_resource_id: str = "seed-and-ingest-resource",
) -> dict:
    """Build a synthetic CloudFormation custom resource event."""
    if properties is None:
        properties = {
            "SourceBucketName": "my-source-bucket",
            "SourceDataPrefix": "data/",
            "KnowledgeBaseId": "KB123",
            "DataSourceId": "DS456",
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
