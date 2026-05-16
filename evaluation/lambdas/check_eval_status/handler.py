import boto3
from typing import Any

# Terminal statuses -- polling stops when job reaches one of these.
# Compared case-insensitively because Bedrock returns PascalCase
# ("Completed", "Failed", "Stopped") while the legacy spec used SCREAMING_SNAKE.
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "STOPPED"}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Checks the status of a Bedrock evaluation job.

    Input event:
    {
        "job_arn": "arn:aws:bedrock:...:evaluation-job/..."
    }

    Returns:
    {
        "job_arn": "string",
        "status": "InProgress" | "Completed" | "Failed" | "Stopping" | "Stopped" | "Deleting",
        "completed": bool
    }
    """
    job_arn = event.get("job_arn")
    if not job_arn:
        raise KeyError("Missing required field: job_arn")

    bedrock_client = boto3.client("bedrock", region_name="us-east-1")

    try:
        response = bedrock_client.get_evaluation_job(jobIdentifier=job_arn)
    except Exception as exc:
        raise RuntimeError(f"Failed to get evaluation job status for {job_arn}: {exc}") from exc

    status = response.get("status")
    if not status:
        raise ValueError(
            f"GetEvaluationJob response did not contain 'status' for job {job_arn}"
        )

    completed = status.upper() in TERMINAL_STATUSES

    return {
        "job_arn": job_arn,
        "status": status,
        "completed": completed,
    }
