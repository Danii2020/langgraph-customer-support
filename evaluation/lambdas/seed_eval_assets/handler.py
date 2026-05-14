"""
CloudFormation custom resource Lambda: seed-eval-assets.

Lifecycle:
  Create  -- uploads the three seed files (dataset, thresholds, prompt template)
             from SEED_ASSETS_DIR to s3://{EvalBucket} at their canonical keys.
  Update  -- no-op when EvalBucketName and ResultsBucketName are unchanged;
             re-uploads seed files to the new EvalBucket if either tracked
             property changed.
  Delete  -- empties both EvalBucket and ResultsBucket so CloudFormation can
             delete them without a BucketNotEmpty error.
             NOTE: buckets are intentionally coupled to the stack lifecycle.
             For production forks, set DeletionPolicy: Retain on the bucket
             resources and remove the empty-on-delete branch here.

All boto3 clients are constructed inside the handler (not at module level) so
unit tests can patch boto3.client without monkeypatching module-level globals.
"""
import json
import os
import urllib.request
from typing import Any

import boto3

# Directory packaged by sam build alongside handler.py. Populated by
# evaluation/scripts/prepare_lambda_assets.py before each sam build.
SEED_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "seed_assets")

# (local_filename, s3_key) pairs. Local filenames are looked up under
# SEED_ASSETS_DIR; s3_keys are written verbatim into the eval bucket.
# These S3 keys MUST match the values produced by the two trigger paths:
# the PromptVersionPublishedRule input transformer and the
# KbIngestionCompleteFunction state-machine input. The KB prompt template
# is no longer seeded to S3 -- it lives in Bedrock Prompt Management
# (see create_eval_prompt.py).
SEED_FILES: list[tuple[str, str]] = [
    ("evaluation_dataset.jsonl",          "datasets/rag_eval.jsonl"),
    ("retrieval_eval_dataset.jsonl",      "datasets/retrieval_eval.jsonl"),
    ("thresholds.json",                   "baselines/thresholds.json"),
    ("retrieval_thresholds.json",         "baselines/retrieval_thresholds.json"),
]

# Tracked across Update; if any value changes the Lambda re-uploads.
# SeedAssetsHash is a SHA-256 of the seed files maintained by
# evaluation/scripts/prepare_lambda_assets.py — editing the dataset or
# thresholds file changes this value, which is what triggers a re-upload
# on the next `sam deploy` even though the bucket names are unchanged.
_TRACKED_KEYS = ("EvalBucketName", "ResultsBucketName", "SeedAssetsHash")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    CloudFormation custom resource handler dispatching on event["RequestType"].

    ResourceProperties (from CloudFormation):
    {
        "EvalBucketName": "...",
        "ResultsBucketName": "...",
        "Region": "us-east-1"
    }

    Output Data (returned to CloudFormation on Create/Update-with-changes):
    {
        "FilesUploaded": "3"
    }
    """
    physical_id = event.get("PhysicalResourceId", "seed-eval-assets-resource")
    try:
        request_type = event["RequestType"]
        props = event.get("ResourceProperties", {})

        eval_bucket = props["EvalBucketName"]
        results_bucket = props["ResultsBucketName"]
        # Optional: the CloudTrail log bucket. Older stack versions did not
        # pass this property, so guard with .get() for backward compatibility.
        trail_log_bucket = props.get("TrailLogBucketName") or None
        region = props.get("Region", os.environ.get("AWS_REGION", "us-east-1"))

        s3_client = boto3.client("s3", region_name=region)

        if request_type == "Create":
            keys = upload_seed_assets(s3_client, eval_bucket)
            data = {"FilesUploaded": str(len(keys))}
            send_cfn_response(event, context, "SUCCESS", data=data, physical_resource_id=physical_id)
            return data

        elif request_type == "Update":
            old_props = event.get("OldResourceProperties", {})
            changed = any(props.get(k) != old_props.get(k) for k in _TRACKED_KEYS)
            if not changed:
                send_cfn_response(event, context, "SUCCESS", data={}, physical_resource_id=physical_id)
                return {}
            keys = upload_seed_assets(s3_client, eval_bucket)
            data = {"FilesUploaded": str(len(keys))}
            send_cfn_response(event, context, "SUCCESS", data=data, physical_resource_id=physical_id)
            return data

        elif request_type == "Delete":
            buckets_to_empty = [eval_bucket, results_bucket]
            if trail_log_bucket:
                buckets_to_empty.append(trail_log_bucket)
            for bucket in buckets_to_empty:
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


def upload_seed_assets(s3_client: Any, bucket: str) -> list[str]:
    """
    Upload every (local_filename, s3_key) pair in SEED_FILES to bucket.
    Returns the list of S3 keys uploaded.
    Missing local files are silently skipped (logged via print).
    """
    uploaded_keys: list[str] = []
    for local_filename, s3_key in SEED_FILES:
        local_path = os.path.join(SEED_ASSETS_DIR, local_filename)
        if not os.path.isfile(local_path):
            print(f"WARNING: source file not found, skipping: {local_path}")
            continue
        with open(local_path, "rb") as fh:
            s3_client.put_object(Bucket=bucket, Key=s3_key, Body=fh.read())
        uploaded_keys.append(s3_key)
    return uploaded_keys


def empty_bucket(s3_client: Any, bucket: str) -> None:
    """
    Delete every object (and versions/delete-markers if versioning was
    enabled) under bucket. Idempotent: empty bucket is a no-op.
    Mirrors kb_provisioning/lambdas/seed_and_ingest/handler.py:empty_bucket.
    """
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
        physical_resource_id = event.get("PhysicalResourceId", "seed-eval-assets-resource")

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
