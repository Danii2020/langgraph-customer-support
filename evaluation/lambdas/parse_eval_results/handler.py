import json
import boto3
from typing import Any


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Parses Bedrock evaluation job results and compares against thresholds.

    Input event:
    {
        "retrieval_only_job_arn": "arn:aws:bedrock:us-east-2:...:evaluation-job/...",
        "retrieve_and_generate_job_arn": "arn:aws:bedrock:us-east-2:...:evaluation-job/...",
        "thresholds_s3_uri": "s3://bucket/baselines/thresholds.json"
    }

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
    retrieval_only_job_arn = event.get("retrieval_only_job_arn")
    retrieve_and_generate_job_arn = event.get("retrieve_and_generate_job_arn")
    thresholds_s3_uri = event.get("thresholds_s3_uri")

    if not retrieval_only_job_arn:
        raise KeyError("Missing required field: retrieval_only_job_arn")
    if not retrieve_and_generate_job_arn:
        raise KeyError("Missing required field: retrieve_and_generate_job_arn")
    if not thresholds_s3_uri:
        raise KeyError("Missing required field: thresholds_s3_uri")

    bedrock_client = boto3.client("bedrock", region_name="us-east-1")
    s3_client = boto3.client("s3", region_name="us-east-1")

    # Load thresholds
    thresholds_data = read_s3_json(s3_client, thresholds_s3_uri)
    retrieval_thresholds = thresholds_data.get("retrieval_only", {})
    rag_thresholds = thresholds_data.get("retrieve_and_generate", {})

    # Parse retrieval-only job results
    retrieval_output_uri = get_evaluation_output_s3_uri(bedrock_client, retrieval_only_job_arn)
    retrieval_eval_data = read_s3_json(s3_client, retrieval_output_uri)
    retrieval_scores = extract_metric_scores(retrieval_eval_data)

    # Parse retrieve-and-generate job results
    rag_output_uri = get_evaluation_output_s3_uri(bedrock_client, retrieve_and_generate_job_arn)
    rag_eval_data = read_s3_json(s3_client, rag_output_uri)
    rag_scores = extract_metric_scores(rag_eval_data)

    # Combine all scores and thresholds
    all_scores = {**retrieval_scores, **rag_scores}
    all_thresholds = {**retrieval_thresholds, **rag_thresholds}

    return compare_against_thresholds(all_scores, all_thresholds)


def get_evaluation_output_s3_uri(bedrock_client: Any, job_arn: str) -> str:
    """Call GetEvaluationJob and extract the output S3 URI."""
    try:
        response = bedrock_client.get_evaluation_job(jobIdentifier=job_arn)
    except Exception as exc:
        raise RuntimeError(f"Failed to get evaluation job {job_arn}: {exc}") from exc

    # The output config contains the S3 URI where results are stored
    output_data_config = response.get("outputDataConfig", {})
    s3_uri = output_data_config.get("s3Uri")
    if not s3_uri:
        raise ValueError(
            f"Output S3 URI not found in evaluation job response for {job_arn}. "
            f"Response outputDataConfig: {output_data_config}"
        )
    return s3_uri


def read_s3_json(s3_client: Any, s3_uri: str) -> dict[str, Any]:
    """Parse an s3://bucket/key URI and read the JSON content."""
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI format: {s3_uri}. Expected s3://bucket/key")

    without_prefix = s3_uri[len("s3://"):]
    slash_index = without_prefix.find("/")
    if slash_index == -1:
        raise ValueError(f"Invalid S3 URI format: {s3_uri}. No key found after bucket name")

    bucket = without_prefix[:slash_index]
    key = without_prefix[slash_index + 1:]

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


def extract_metric_scores(eval_results: dict[str, Any]) -> dict[str, float]:
    """Extract per-metric average scores from the Bedrock evaluation results JSON.

    Bedrock evaluation output JSON has an 'averageScores' field at the top level,
    or nested within 'evaluationSummary' depending on the job type. We handle
    both structures defensively.

    Expected structure (primary):
    {
        "averageScores": {
            "context_relevance": 0.85,
            "context_coverage": 0.80,
            ...
        }
    }

    Alternative structure (some job types):
    {
        "evaluationSummary": {
            "scores": [
                {"metricName": "context_relevance", "score": 0.85},
                ...
            ]
        }
    }
    """
    # Primary: flat averageScores dict
    if "averageScores" in eval_results:
        raw = eval_results["averageScores"]
        if not isinstance(raw, dict):
            raise ValueError(
                f"Expected 'averageScores' to be a dict, got {type(raw).__name__}"
            )
        scores: dict[str, float] = {}
        for metric, value in raw.items():
            try:
                scores[metric] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Non-numeric score for metric '{metric}': {value}"
                ) from exc
        return scores

    # Alternative: evaluationSummary.scores list
    if "evaluationSummary" in eval_results:
        summary = eval_results["evaluationSummary"]
        score_list = summary.get("scores", [])
        if not isinstance(score_list, list):
            raise ValueError(
                f"Expected 'evaluationSummary.scores' to be a list, got {type(score_list).__name__}"
            )
        scores = {}
        for entry in score_list:
            metric_name = entry.get("metricName")
            value = entry.get("score")
            if metric_name is None:
                raise ValueError(f"Score entry missing 'metricName': {entry}")
            try:
                scores[metric_name] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Non-numeric score for metric '{metric_name}': {value}"
                ) from exc
        return scores

    raise ValueError(
        "Evaluation results JSON does not contain 'averageScores' or 'evaluationSummary'. "
        f"Top-level keys found: {list(eval_results.keys())}"
    )


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
            # Treat missing score as a failure with score 0.0
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
