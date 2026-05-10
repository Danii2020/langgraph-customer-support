"""
CloudFormation custom resource Lambda: seed-and-ingest.

Lifecycle:
  Create  — uploads every file in SEED_DATA_DIR to s3://{SourceBucket}/{SourceDataPrefix}
             then calls bedrock-agent:StartIngestionJob for the KB + DataSource.
  Update  — no-op when ResourceProperties are unchanged; re-uploads and re-ingests
             if any tracked property (SourceBucketName, SourceDataPrefix,
             KnowledgeBaseId, DataSourceId) changed.
  Delete  — empties the source bucket so CFN can delete it (BucketNotEmpty guard).
             Does NOT stop or delete the Bedrock KB; CFN handles that.

All boto3 clients are constructed inside the handler (not at module level) so
unit tests can patch boto3.client without monkeypatching module-level globals.
"""
import json
import os
import urllib.request
from typing import Any

import boto3

SEED_DATA_DIR = os.path.join(os.path.dirname(__file__), "seed_data")

# Keys compared between Create and Update to decide whether re-ingestion is needed.
_TRACKED_KEYS = ("SourceBucketName", "SourceDataPrefix", "KnowledgeBaseId", "DataSourceId")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    CloudFormation custom resource handler dispatching on event["RequestType"].

    ResourceProperties (from CloudFormation):
    {
        "SourceBucketName": "...",
        "SourceDataPrefix": "data/",
        "KnowledgeBaseId": "...",
        "DataSourceId": "...",
        "Region": "us-east-1"
    }

    Output Data (returned to CloudFormation on Create/Update-with-changes):
    {
        "IngestionJobId": "...",
        "FilesUploaded": "2"
    }
    """
    physical_id = event.get("PhysicalResourceId", "seed-and-ingest-resource")
    try:
        request_type = event["RequestType"]
        props = event.get("ResourceProperties", {})

        bucket = props["SourceBucketName"]
        prefix = props["SourceDataPrefix"]
        kb_id = props["KnowledgeBaseId"]
        ds_id = props["DataSourceId"]
        region = props.get("Region", os.environ.get("AWS_REGION", "us-east-1"))

        s3_client = boto3.client("s3", region_name=region)
        bedrock_agent = boto3.client("bedrock-agent", region_name=region)

        if request_type == "Create":
            keys = upload_seed_data(s3_client, bucket, prefix)
            job_id = start_ingestion(bedrock_agent, kb_id, ds_id)
            data = {"IngestionJobId": job_id, "FilesUploaded": str(len(keys))}
            send_cfn_response(event, context, "SUCCESS", data=data, physical_resource_id=physical_id)
            return data

        elif request_type == "Update":
            old_props = event.get("OldResourceProperties", {})
            changed = any(props.get(k) != old_props.get(k) for k in _TRACKED_KEYS)
            if not changed:
                send_cfn_response(event, context, "SUCCESS", data={}, physical_resource_id=physical_id)
                return {}
            keys = upload_seed_data(s3_client, bucket, prefix)
            job_id = start_ingestion(bedrock_agent, kb_id, ds_id)
            data = {"IngestionJobId": job_id, "FilesUploaded": str(len(keys))}
            send_cfn_response(event, context, "SUCCESS", data=data, physical_resource_id=physical_id)
            return data

        elif request_type == "Delete":
            empty_bucket(s3_client, bucket)
            send_cfn_response(event, context, "SUCCESS", data={}, physical_resource_id=physical_id)
            return {}

        else:
            raise ValueError(f"Unknown RequestType: {request_type}")

    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        send_cfn_response(
            event,
            context,
            "FAILED",
            data={},
            physical_resource_id=physical_id,
            reason=reason,
        )
        return {}


def upload_seed_data(s3_client: Any, bucket: str, prefix: str) -> list[str]:
    """Upload every file under SEED_DATA_DIR. Returns the list of S3 keys uploaded."""
    uploaded_keys: list[str] = []
    if not os.path.isdir(SEED_DATA_DIR):
        return uploaded_keys
    for filename in os.listdir(SEED_DATA_DIR):
        local_path = os.path.join(SEED_DATA_DIR, filename)
        if not os.path.isfile(local_path):
            continue
        s3_key = f"{prefix}{filename}"
        with open(local_path, "rb") as fh:
            s3_client.put_object(Bucket=bucket, Key=s3_key, Body=fh.read())
        uploaded_keys.append(s3_key)
    return uploaded_keys


def start_ingestion(bedrock_agent: Any, kb_id: str, ds_id: str) -> str:
    """Call StartIngestionJob and return the ingestion job ID. Does NOT wait for completion."""
    response = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )
    ingestion_job = response.get("ingestionJob", {})
    job_id = ingestion_job.get("ingestionJobId", "")
    return job_id


def empty_bucket(s3_client: Any, bucket: str) -> None:
    """Delete every object (and delete marker/version if versioned) in the bucket."""
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        objects = page.get("Contents", [])
        if not objects:
            continue
        # Batch deletes in groups of 1000 (S3 API limit).
        batch: list[dict[str, str]] = [{"Key": obj["Key"]} for obj in objects]
        s3_client.delete_objects(Bucket=bucket, Delete={"Objects": batch})

    # Also purge delete markers and non-current versions if versioning was enabled.
    try:
        version_paginator = s3_client.get_paginator("list_object_versions")
        for page in version_paginator.paginate(Bucket=bucket):
            to_delete: list[dict[str, str]] = []
            for v in page.get("Versions", []):
                to_delete.append({"Key": v["Key"], "VersionId": v["VersionId"]})
            for dm in page.get("DeleteMarkers", []):
                to_delete.append({"Key": dm["Key"], "VersionId": dm["VersionId"]})
            if to_delete:
                s3_client.delete_objects(Bucket=bucket, Delete={"Objects": to_delete})
    except Exception:
        # list_object_versions may not be available if versioning was never enabled;
        # ignore errors here — the bucket should already be empty from the first pass.
        pass


def send_cfn_response(
    event: dict[str, Any],
    context: Any,
    status: str,
    data: dict[str, Any] | None = None,
    physical_resource_id: str | None = None,
    reason: str | None = None,
) -> None:
    """PUT the JSON-encoded response body to event['ResponseURL']. Network failures here are fatal."""
    if data is None:
        data = {}

    if physical_resource_id is None:
        physical_resource_id = event.get("PhysicalResourceId", "seed-and-ingest-resource")

    if reason is None and status == "FAILED":
        reason = "Unknown failure"

    body = {
        "Status": status,
        "Reason": reason or "",
        "PhysicalResourceId": physical_resource_id,
        "StackId": event.get("StackId", ""),
        "RequestId": event.get("RequestId", ""),
        "LogicalResourceId": event.get("LogicalResourceId", ""),
        "Data": data,
    }

    body_bytes = json.dumps(body).encode("utf-8")
    response_url = event["ResponseURL"]

    req = urllib.request.Request(
        url=response_url,
        data=body_bytes,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body_bytes)),
        },
        method="PUT",
    )
    urllib.request.urlopen(req)
