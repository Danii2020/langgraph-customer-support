import os
import boto3
from typing import Any


# Variables the RAG evaluation API recognizes inside textPromptTemplate.
# Bedrock Prompt Management stores them as '{{var}}' for console UX; the
# RAG eval API requires '$var$', so the Lambda converts at fetch time.
RAG_PROMPT_VARIABLES = ("search_results", "query")


def _brace_to_dollar(text: str) -> str:
    """Convert '{{search_results}}' / '{{query}}' to '$search_results$' / '$query$'."""
    for var in RAG_PROMPT_VARIABLES:
        text = text.replace("{{" + var + "}}", f"${var}$")
    return text


def _fetch_prompt_text(client: Any, prompt_id: str, version: str | None) -> str:
    """
    Read the prompt text from Bedrock Prompt Management.

    If `version` is provided, fetch that specific published version. Otherwise
    list versions and fetch the highest-numbered one; fall back to DRAFT if no
    versions exist yet.
    """
    if not version:
        listing = client.get_prompt(promptIdentifier=prompt_id)
        versions = listing.get("versions") or []
        numeric = [int(v["version"]) for v in versions if str(v.get("version", "")).isdigit()]
        version = str(max(numeric)) if numeric else "DRAFT"

    response = client.get_prompt(promptIdentifier=prompt_id, promptVersion=version)
    variants = response.get("variants") or []
    if not variants:
        raise ValueError(
            f"Prompt {prompt_id} version {version} has no variants -- "
            "create one via create_eval_prompt.py."
        )
    template_config = variants[0].get("templateConfiguration", {})
    text = (template_config.get("text") or {}).get("text")
    if not text:
        raise ValueError(
            f"Prompt {prompt_id} version {version} variant has no text template."
        )
    return _brace_to_dollar(text)


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
            "prompt_version": "string"   # optional; CloudTrail rule passes the
                                         # version emitted by CreatePromptVersion.
                                         # Absent -> latest version of the prompt
                                         # identified by PROMPT_RESOURCE_ID env var.
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

    region = os.environ.get("AWS_REGION", "us-east-1")
    bedrock_client = boto3.client("bedrock", region_name=region)

    job_name = f"kb-eval-retrieve-and-generate-{_timestamp_suffix()}"

    prompt_template_text: str | None = None
    prompt_resource_id = os.environ.get("PROMPT_RESOURCE_ID")
    if prompt_resource_id:
        bedrock_agent_client = boto3.client("bedrock-agent", region_name=region)
        prompt_version = eval_config.get("prompt_version")
        prompt_template_text = _fetch_prompt_text(
            bedrock_agent_client, prompt_resource_id, prompt_version
        )

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
