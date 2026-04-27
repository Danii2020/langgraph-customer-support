import os
import boto3
from typing import Any


def _read_s3_text(s3_client: Any, s3_uri: str) -> str:
    """Read a text file from S3 given an s3:// URI."""
    bucket = s3_uri.split("/")[2]
    key = "/".join(s3_uri.split("/")[3:])
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Starts a Bedrock Knowledge Base RETRIEVE_AND_GENERATE evaluation job.

    Input event:
    {
        "eval_type": "RETRIEVE_AND_GENERATE",
        "knowledge_base_id": "string",
        "eval_config": {
            "dataset_s3_uri": "s3://...",
            "output_s3_uri": "s3://...",
            "role_arn": "arn:aws:iam::...:role/...",
            "model_id": "string",
            "evaluator_model_id": "string",
            "prompt_template_s3_uri": "s3://..."  # optional
        }
    }

    Returns:
    {
        "job_arn": "arn:aws:bedrock:...:evaluation-job/..."
    }
    """
    eval_type = event.get("eval_type")
    knowledge_base_id = event.get("knowledge_base_id")
    eval_config = event.get("eval_config", {})

    if not eval_type:
        raise KeyError("Missing required field: eval_type")
    if not knowledge_base_id:
        raise KeyError("Missing required field: knowledge_base_id")

    if eval_type != "RETRIEVE_AND_GENERATE":
        raise ValueError(
            f"Invalid eval_type '{eval_type}'. Must be 'RETRIEVE_AND_GENERATE'."
        )

    dataset_s3_uri = eval_config.get("dataset_s3_uri")
    output_s3_uri = eval_config.get("output_s3_uri")
    role_arn = eval_config.get("role_arn")
    evaluator_model_id = eval_config.get("evaluator_model_id")
    model_id = eval_config.get("model_id")

    if not dataset_s3_uri:
        raise KeyError("Missing required eval_config field: dataset_s3_uri")
    if not output_s3_uri:
        raise KeyError("Missing required eval_config field: output_s3_uri")
    if not role_arn:
        raise KeyError("Missing required eval_config field: role_arn")
    if not evaluator_model_id:
        raise KeyError("Missing required eval_config field: evaluator_model_id")
    if not model_id:
        raise KeyError("Missing required eval_config field: model_id")

    bedrock_client = boto3.client("bedrock", region_name="us-east-1")

    job_name = f"kb-eval-retrieve-and-generate-{_timestamp_suffix()}"

    prompt_template_s3_uri = eval_config.get("prompt_template_s3_uri")
    prompt_template_text = None
    if prompt_template_s3_uri:
        s3_client = boto3.client("s3", region_name="us-east-1")
        prompt_template_text = _read_s3_text(s3_client, prompt_template_s3_uri)

    job_arn = _start_retrieve_and_generate_job(
        bedrock_client=bedrock_client,
        job_name=job_name,
        knowledge_base_id=knowledge_base_id,
        dataset_s3_uri=dataset_s3_uri,
        output_s3_uri=output_s3_uri,
        role_arn=role_arn,
        model_id=model_id,
        evaluator_model_id=evaluator_model_id,
        prompt_template_text=prompt_template_text,
    )

    return {"job_arn": job_arn}


def _timestamp_suffix() -> str:
    """Return a timestamp string suitable for unique job naming."""
    import datetime
    return datetime.datetime.now(datetime.UTC).strftime("%Y%m%d%H%M%S")


def _start_retrieve_and_generate_job(
    bedrock_client: Any,
    job_name: str,
    knowledge_base_id: str,
    dataset_s3_uri: str,
    output_s3_uri: str,
    role_arn: str,
    model_id: str,
    evaluator_model_id: str,
    prompt_template_text: str | None = None,
) -> str:
    """Create a RETRIEVE_AND_GENERATE evaluation job and return the job ARN."""
    kb_configuration: dict[str, Any] = {
        "knowledgeBaseId": knowledge_base_id,
        "modelArn": model_id,
    }

    if prompt_template_text:
        kb_configuration["generationConfiguration"] = {
            "promptTemplate": {
                "textPromptTemplate": prompt_template_text
            },
            "kbInferenceConfig": {
                "textInferenceConfig": {
                    "temperature": 0.0,
                    "topP": 0.9,
                    "maxTokens": 1024,
                }
            },
        }

    try:
        response = bedrock_client.create_evaluation_job(
            jobName=job_name,
            roleArn=role_arn,
            applicationType="RagEvaluation",
            evaluationConfig={
                "automated": {
                    "datasetMetricConfigs": [
                        {
                            "taskType": "Summarization",
                            "dataset": {
                                "name": "RagDataset",
                                "datasetLocation": {
                                    "s3Uri": dataset_s3_uri
                                },
                            },
                            "metricNames": [
                                "Builtin.Faithfulness",
                                "Builtin.Correctness",
                                "Builtin.Completeness",
                                "Builtin.Helpfulness",
                                "Builtin.LogicalCoherence",
                            ],
                        }
                    ],
                    "evaluatorModelConfig": {
                        "bedrockEvaluatorModels": [
                            {
                                "modelIdentifier": evaluator_model_id
                            }
                        ]
                    },
                }
            },
            inferenceConfig={
                "ragConfigs": [
                    {
                        "knowledgeBaseConfig": {
                            "retrieveAndGenerateConfig": {
                                "type": "KNOWLEDGE_BASE",
                                "knowledgeBaseConfiguration": kb_configuration,
                            }
                        }
                    }
                ]
            },
            outputDataConfig={"s3Uri": output_s3_uri},
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to create RETRIEVE_AND_GENERATE evaluation job: {exc}"
        ) from exc

    job_arn = response.get("jobArn")
    if not job_arn:
        raise ValueError("CreateEvaluationJob response did not contain jobArn")
    return job_arn
