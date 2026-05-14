"""
Lambda invoked by a CloudWatch Logs subscription filter on the Bedrock
Knowledge Base ingestion log group. Fires when an ingestion job reaches
COMPLETE and starts a fresh execution of the eval pipeline state machine.

This replaces the dead `KbSyncCompletionRule` EventBridge rule. Bedrock
Knowledge Bases do NOT emit a native EventBridge event when an ingestion
job finishes -- they only write a structured log entry via the KB log
delivery feature. The subscription filter pattern at the template level
narrows to `ingestion_job_status = "COMPLETE"`, so by the time the
Lambda is invoked the status is already known; the per-event validation
below is defensive only.

CloudWatch Logs subscription event shape:
    {
      "awslogs": {
        "data": "<base64-encoded gzipped JSON>"
      }
    }

Decoded payload:
    {
      "messageType": "DATA_MESSAGE",
      "logGroup": "/aws/vendedlogs/bedrock/knowledge-base/<id>",
      "logStream": "...",
      "subscriptionFilters": ["..."],
      "logEvents": [
        {"id": "...", "timestamp": ..., "message": "<json string>"}
      ]
    }

The state machine input shape is kept identical to the JSON the old
EventBridge rule sent, so no downstream state-machine code needs to
change.
"""
import base64
import gzip
import json
import os
from typing import Any

import boto3


COMPLETE_STATUS = "COMPLETE"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Decode the CloudWatch Logs subscription payload, find log entries
    that indicate the configured Knowledge Base finished an ingestion
    job, and start one Step Functions execution per such entry.
    """
    state_machine_arn = os.environ["STATE_MACHINE_ARN"]
    eval_bucket = os.environ["EVAL_BUCKET_NAME"]
    results_bucket = os.environ["RESULTS_BUCKET_NAME"]
    expected_kb_id = os.environ.get("KNOWLEDGE_BASE_ID", "")

    log_events = _decode_log_events(event)

    # State machine input shape covers both parallel branches:
    # the RAG-eval branch and the retrieval-only branch read their
    # own dataset / output / thresholds URIs from this object.
    state_machine_input = {
        "rag_dataset_s3_uri":         f"s3://{eval_bucket}/datasets/rag_eval.jsonl",
        "rag_output_s3_uri":          f"s3://{results_bucket}/results/rag/",
        "rag_thresholds_s3_uri":      f"s3://{eval_bucket}/baselines/thresholds.json",
        "retrieval_dataset_s3_uri":   f"s3://{eval_bucket}/datasets/retrieval_eval.jsonl",
        "retrieval_output_s3_uri":    f"s3://{results_bucket}/results/retrieval/",
        "retrieval_thresholds_s3_uri": f"s3://{eval_bucket}/baselines/retrieval_thresholds.json",
        "prompt_version": "",
    }

    region = os.environ.get("AWS_REGION", "us-east-1")
    sfn_client = boto3.client("stepfunctions", region_name=region)

    started = 0
    skipped = 0
    for log_event in log_events:
        record = _parse_log_message(log_event.get("message", ""))
        if record is None:
            skipped += 1
            continue
        if not _matches_complete_for_kb(record, expected_kb_id):
            skipped += 1
            continue

        sfn_client.start_execution(
            stateMachineArn=state_machine_arn,
            input=json.dumps(state_machine_input),
        )
        started += 1

    return {"executions_started": started, "events_skipped": skipped}


def _decode_log_events(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the logEvents array, or [] if the payload is malformed."""
    awslogs = event.get("awslogs") or {}
    data_b64 = awslogs.get("data")
    if not data_b64:
        return []
    try:
        compressed = base64.b64decode(data_b64)
        raw = gzip.decompress(compressed)
        payload = json.loads(raw)
    except (ValueError, OSError, json.JSONDecodeError):
        return []
    events = payload.get("logEvents")
    return events if isinstance(events, list) else []


def _parse_log_message(message: str) -> dict[str, Any] | None:
    """Parse the per-event message body. Returns None on malformed input."""
    if not message:
        return None
    try:
        return json.loads(message)
    except (ValueError, json.JSONDecodeError):
        return None


def _matches_complete_for_kb(record: dict[str, Any], expected_kb_id: str) -> bool:
    """
    Return True when the parsed log record represents a COMPLETE
    ingestion status update for the configured Knowledge Base. The
    subscription filter pattern already enforces status==COMPLETE; this
    guard exists to keep the Lambda robust against malformed events or
    filter-pattern drift, and to scope to the configured KB ID when
    multiple KBs share a log group (defense in depth -- AWS::Logs::Delivery
    sources are 1:1 with a KB ARN, so cross-KB leakage shouldn't happen).
    """
    inner = record.get("event")
    if not isinstance(inner, dict):
        return False
    if inner.get("ingestion_job_status") != COMPLETE_STATUS:
        return False
    if expected_kb_id:
        kb_arn = inner.get("knowledge_base_arn", "")
        if not kb_arn.endswith(f"/{expected_kb_id}"):
            return False
    return True
