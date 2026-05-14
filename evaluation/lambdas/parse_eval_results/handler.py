import json
import boto3
from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Parses Bedrock evaluation job results and compares against thresholds.

    Input event:
    {
        "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:...:evaluation-job/...",
        "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json",
        "thresholds_subkey": "retrieve_and_generate"   # optional; default
                                                        # "retrieve_and_generate". The
                                                        # retrieval-only branch of the
                                                        # state machine passes
                                                        # "retrieve_only" to read its
                                                        # own thresholds block.
    }

    The input field is still named `retrieve_and_generate_job_arn` for
    backward compatibility; for retrieve-only jobs it carries the
    retrieval evaluation job ARN. The Bedrock API surface for parsing
    output is identical between the two job types -- the only differences
    are the metric names emitted in the JSONL and the thresholds_subkey
    used to look up the matching thresholds block.

    Returns:
    {
        "passed": bool,
        "results": {
            "<metric_name>": {
                "score": float,
                "threshold": float,
                "passed": bool
            },
            ...
        },
        "failed_metrics": ["<metric_name>", ...]
    }
    """
    retrieve_and_generate_job_arn = event.get("retrieve_and_generate_job_arn")
    thresholds_s3_uri = event.get("thresholds_s3_uri")
    thresholds_subkey = event.get("thresholds_subkey") or "retrieve_and_generate"

    if not retrieve_and_generate_job_arn:
        raise KeyError("Missing required field: retrieve_and_generate_job_arn")
    if not thresholds_s3_uri:
        raise KeyError("Missing required field: thresholds_s3_uri")

    # The job ID is the last segment of the ARN
    # (arn:aws:bedrock:...:evaluation-job/<job_id>). Bedrock writes the
    # per-job output under <output_prefix>/<job_name>/<job_id>/... and
    # GetEvaluationJob only returns the top-level <output_prefix>, so we
    # must filter by job_id to avoid picking up an older sibling job's
    # JSONL when multiple eval runs share the same output prefix.
    job_id = retrieve_and_generate_job_arn.rsplit("/", 1)[-1]
    if not job_id:
        raise ValueError(
            f"Could not extract job ID from ARN: {retrieve_and_generate_job_arn}"
        )

    bedrock_client = boto3.client("bedrock", region_name="us-east-1")
    s3_client = boto3.client("s3", region_name="us-east-1")

    thresholds_data = read_s3_json(s3_client, thresholds_s3_uri)
    rag_thresholds = thresholds_data.get(thresholds_subkey, {})

    rag_output_prefix = get_evaluation_output_s3_uri(bedrock_client, retrieve_and_generate_job_arn)
    rag_jsonl_uri = find_output_jsonl_uri(s3_client, rag_output_prefix, job_id)
    rag_records = read_s3_jsonl(s3_client, rag_jsonl_uri)
    rag_scores = extract_metric_scores(rag_records)

    return compare_against_thresholds(rag_scores, rag_thresholds)


def get_evaluation_output_s3_uri(bedrock_client: Any, job_arn: str) -> str:
    """Call GetEvaluationJob and extract the output S3 URI prefix."""
    try:
        response = bedrock_client.get_evaluation_job(jobIdentifier=job_arn)
    except Exception as exc:
        raise RuntimeError(f"Failed to get evaluation job {job_arn}: {exc}") from exc

    output_data_config = response.get("outputDataConfig", {})
    s3_uri = output_data_config.get("s3Uri")
    if not s3_uri:
        raise ValueError(
            f"Output S3 URI not found in evaluation job response for {job_arn}. "
            f"Response outputDataConfig: {output_data_config}"
        )
    return s3_uri


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Split an s3://bucket/key URI into (bucket, key)."""
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI format: {s3_uri}. Expected s3://bucket/key")

    without_prefix = s3_uri[len("s3://"):]
    slash_index = without_prefix.find("/")
    if slash_index == -1:
        raise ValueError(f"Invalid S3 URI format: {s3_uri}. No key found after bucket name")

    return without_prefix[:slash_index], without_prefix[slash_index + 1:]


def find_output_jsonl_uri(s3_client: Any, prefix_uri: str, job_id: str) -> str:
    """List objects under the Bedrock-returned prefix and locate the *_output.jsonl file
    for the given evaluation job.

    Bedrock writes RAG evaluation output to:
      <prefix>/<jobName>/<jobId>/inference_configs/0/datasets/<dataset>/<uuid>_output.jsonl

    `prefix_uri` is the top-level output URI (shared across all jobs that use the
    same outputDataConfig.s3Uri) so we filter on `/<job_id>/` to pick the right run.
    """
    bucket, prefix = parse_s3_uri(prefix_uri)
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    job_id_segment = f"/{job_id}/"

    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("_output.jsonl") and job_id_segment in key:
                    return f"s3://{bucket}/{key}"
    except Exception as exc:
        raise RuntimeError(f"Failed to list S3 objects under {prefix_uri}: {exc}") from exc

    raise FileNotFoundError(
        f"No '*_output.jsonl' file found under {prefix_uri} for job {job_id}"
    )


def read_s3_json(s3_client: Any, s3_uri: str) -> dict[str, Any]:
    """Parse an s3://bucket/key URI and read a single JSON object."""
    bucket, key = parse_s3_uri(s3_uri)

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
    except s3_client.exceptions.NoSuchKey:
        raise FileNotFoundError(f"S3 object not found: {s3_uri}")
    except Exception as exc:
        raise RuntimeError(f"Failed to read S3 object {s3_uri}: {exc}") from exc

    body = response["Body"].read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in S3 object {s3_uri}: {exc}") from exc


def read_s3_jsonl(s3_client: Any, s3_uri: str) -> list[dict[str, Any]]:
    """Read a JSONL file from S3 and return one parsed record per non-empty line."""
    bucket, key = parse_s3_uri(s3_uri)

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
    except s3_client.exceptions.NoSuchKey:
        raise FileNotFoundError(f"S3 object not found: {s3_uri}")
    except Exception as exc:
        raise RuntimeError(f"Failed to read S3 object {s3_uri}: {exc}") from exc

    body = response["Body"].read().decode("utf-8")
    records: list[dict[str, Any]] = []
    for line_num, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Malformed JSONL in {s3_uri} on line {line_num}: {exc}"
            ) from exc
    return records


def normalize_metric_name(raw_name: str) -> str:
    """Convert Bedrock's 'Builtin.LogicalCoherence' style names to thresholds' 'logical_coherence'."""
    name = raw_name
    if name.startswith("Builtin."):
        name = name[len("Builtin."):]
    chars: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0 and not name[i - 1].isupper():
            chars.append("_")
        chars.append(ch.lower())
    return "".join(chars)


def extract_metric_scores(records: list[dict[str, Any]]) -> dict[str, float]:
    """Average per-metric scores across every conversation turn in the JSONL records.

    Bedrock RAG evaluation output (one JSON record per line) shape:
      {
        "conversationTurns": [
          {
            ...,
            "results": [
              {"metricName": "Builtin.Faithfulness", "result": 1.0, ...},
              {"metricName": "Builtin.Correctness",   "result": 0.81, ...},
              ...
            ]
          }
        ]
      }
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}

    for record in records:
        for turn in record.get("conversationTurns", []):
            for metric_result in turn.get("results", []):
                metric_name = metric_result.get("metricName")
                value = metric_result.get("result")
                if metric_name is None or value is None:
                    continue
                try:
                    score = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Non-numeric score for metric '{metric_name}': {value}"
                    ) from exc
                normalized = normalize_metric_name(metric_name)
                sums[normalized] = sums.get(normalized, 0.0) + score
                counts[normalized] = counts.get(normalized, 0) + 1

    return {metric: sums[metric] / counts[metric] for metric in sums}


def compare_against_thresholds(
    scores: dict[str, float],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    """
    Compare each metric score against its threshold.

    A metric passes if and only if score >= threshold.
    Overall passed is true if and only if all individual metrics pass.

    Returns:
    {
        "passed": bool,
        "results": {metric: {"score": float, "threshold": float, "passed": bool}},
        "failed_metrics": [str]
    }
    """
    results: dict[str, dict[str, Any]] = {}
    failed_metrics: list[str] = []

    for metric, threshold in thresholds.items():
        score = scores.get(metric)
        if score is None:
            score = 0.0
        metric_passed = score >= threshold
        results[metric] = {
            "score": score,
            "threshold": threshold,
            "passed": metric_passed,
        }
        if not metric_passed:
            failed_metrics.append(metric)

    overall_passed = len(failed_metrics) == 0

    return {
        "passed": overall_passed,
        "results": results,
        "failed_metrics": failed_metrics,
    }
