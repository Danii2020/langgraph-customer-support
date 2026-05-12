"""
Upload the KB prompt template to S3 to retrigger the RAG evaluation pipeline.

This is the canonical workshop demo step: upload a (possibly modified) prompt
template to the eval bucket, which triggers PromptTemplateChangeRule via
EventBridge and starts a new EvalPipelineStateMachine execution.

Usage (happy-path -- resolves bucket from CloudFormation stack output):
    python evaluation/scripts/upload_prompt_template.py

Explicit overrides:
    python evaluation/scripts/upload_prompt_template.py \\
        --stack-name rag-eval-pipeline \\
        --region us-east-1 \\
        --template evaluation/prompts/kb_prompt_template.txt \\
        --prefix prompts/

Escape hatch (skip stack lookup):
    python evaluation/scripts/upload_prompt_template.py --bucket my-eval-bucket
"""
import argparse
import os
from typing import Any

import boto3


def resolve_eval_bucket(cfn_client: Any, stack_name: str) -> str:
    """
    Look up the EvalBucketName output of stack_name via DescribeStacks.

    Raises:
      RuntimeError: if the stack does not exist, with a one-line hint.
      KeyError:     if the stack exists but the EvalBucketName output is
                    not present (means an old stack or a deploy mid-flight).

    Pure function -- takes cfn_client as a parameter so unit tests can
    inject a MagicMock without monkeypatching boto3.
    """
    try:
        response = cfn_client.describe_stacks(StackName=stack_name)
    except Exception as exc:
        # boto3 raises ClientError when the stack does not exist.
        raise RuntimeError(
            f"Stack '{stack_name}' not found. "
            "Run `sam deploy` first or pass --bucket explicitly."
        ) from exc

    stacks = response.get("Stacks", [])
    if not stacks:
        raise RuntimeError(
            f"Stack '{stack_name}' not found. "
            "Run `sam deploy` first or pass --bucket explicitly."
        )

    outputs = stacks[0].get("Outputs", [])
    for output in outputs:
        if output.get("OutputKey") == "EvalBucketName":
            return output["OutputValue"]

    raise KeyError(
        "EvalBucketName output not found in stack outputs for "
        f"'{stack_name}'. The stack may still be deploying or may be an "
        "older version that does not export this output. "
        "Wait for the deploy to complete or pass --bucket explicitly."
    )


def main() -> None:
    """argparse entrypoint. See module docstring for behavior contract."""
    parser = argparse.ArgumentParser(
        description=(
            "Upload the KB prompt template to S3 to retrigger the RAG "
            "evaluation pipeline via PromptTemplateChangeRule."
        )
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help=(
            "S3 bucket name (escape hatch). When provided, the CloudFormation "
            "stack lookup is skipped and this bucket is used directly."
        ),
    )
    parser.add_argument(
        "--stack-name",
        default="rag-eval-pipeline",
        help=(
            "CloudFormation stack name to look up the EvalBucketName output "
            "(default: rag-eval-pipeline)."
        ),
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1).",
    )
    parser.add_argument(
        "--prefix",
        default="prompts/",
        help="S3 key prefix (default: prompts/).",
    )
    parser.add_argument(
        "--template",
        default=os.path.join(
            os.path.dirname(__file__), "..", "prompts", "kb_prompt_template.txt"
        ),
        help="Path to the prompt template file (default: evaluation/prompts/kb_prompt_template.txt).",
    )
    args = parser.parse_args()

    if args.bucket:
        bucket = args.bucket
    else:
        cfn_client = boto3.client("cloudformation", region_name=args.region)
        bucket = resolve_eval_bucket(cfn_client, args.stack_name)

    s3 = boto3.client("s3", region_name=args.region)
    key = f"{args.prefix.rstrip('/')}/kb_prompt_template.txt"

    s3.upload_file(args.template, bucket, key)
    print(f"Uploaded to s3://{bucket}/{key}")


if __name__ == "__main__":
    main()
