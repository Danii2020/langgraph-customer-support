"""
Creates (or updates) a Bedrock Prompt Management resource for the RAG
evaluation KB prompt, then publishes a version. The evaluation pipeline
references this prompt by ID -- new versions trigger eval runs via the
PromptVersionPublishedRule (CloudTrail -> EventBridge) defined in
evaluation/template.yaml.

Run once before deploying the evaluation stack:
    python evaluation/scripts/create_eval_prompt.py

Re-run after editing evaluation/prompts/kb_prompt_template.txt to push the
new text as the prompt's DRAFT and publish a fresh version (which triggers
the eval pipeline once the stack is deployed).

The prompt text is stored using Bedrock Prompt Management's native
'{{variable}}' syntax so '{{search_results}}' and '{{query}}' show up as
input variables in the Bedrock console. The start_eval_job Lambda converts
back to the '$variable$' form required by the RAG evaluation API at
runtime.
"""
import argparse
import os
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError


DEFAULT_PROMPT_NAME = "rag-eval-kb-prompt"
DEFAULT_VARIANT_NAME = "default"
DEFAULT_MODEL_ID = "amazon.nova-pro-v1:0"
INPUT_VARIABLES = ["search_results", "query"]


def convert_dollar_to_brace(text: str) -> str:
    """
    Rewrite '$search_results$' / '$query$' (the Bedrock RAG eval API's
    placeholder syntax) into '{{search_results}}' / '{{query}}' (Bedrock
    Prompt Management's native variable syntax).

    Only the two known eval variables are converted -- any other '$...$'
    sequences in the prompt are left intact.
    """
    for var in INPUT_VARIABLES:
        text = text.replace(f"${var}$", "{{" + var + "}}")
    return text


def find_prompt_by_name(client: Any, name: str) -> dict[str, Any] | None:
    """Return the first prompt summary matching `name`, or None."""
    paginator = client.get_paginator("list_prompts")
    for page in paginator.paginate():
        for summary in page.get("promptSummaries", []):
            if summary.get("name") == name:
                return summary
    return None


def build_variant(text: str, model_id: str) -> dict[str, Any]:
    return {
        "name": DEFAULT_VARIANT_NAME,
        "modelId": model_id,
        "templateType": "TEXT",
        "templateConfiguration": {
            "text": {
                "text": text,
                "inputVariables": [{"name": v} for v in INPUT_VARIABLES],
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create or update a Bedrock Prompt Management resource for the "
            "RAG evaluation KB prompt and publish a version."
        )
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1).",
    )
    parser.add_argument(
        "--name",
        default=DEFAULT_PROMPT_NAME,
        help=f"Prompt name (default: {DEFAULT_PROMPT_NAME}).",
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
        help=(
            f"Default model ID for the prompt variant (default: {DEFAULT_MODEL_ID}). "
            "Does NOT affect the RAG eval -- the eval pipeline overrides the "
            "generator model via the BedrockModelId stack parameter."
        ),
    )
    parser.add_argument(
        "--template",
        default=os.path.join(
            os.path.dirname(__file__), "..", "prompts", "kb_prompt_template.txt"
        ),
        help="Path to the prompt template file.",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.template):
        print(f"ERROR: template not found: {args.template}", file=sys.stderr)
        sys.exit(1)

    with open(args.template, "r", encoding="utf-8") as fh:
        raw_text = fh.read()
    text = convert_dollar_to_brace(raw_text)

    client = boto3.client("bedrock-agent", region_name=args.region)
    variant = build_variant(text, args.model_id)

    existing = find_prompt_by_name(client, args.name)

    if existing:
        prompt_id = existing["id"]
        print(f"Reusing existing prompt: {prompt_id} ({args.name})")
        try:
            client.update_prompt(
                promptIdentifier=prompt_id,
                name=args.name,
                defaultVariant=DEFAULT_VARIANT_NAME,
                variants=[variant],
            )
            print("Updated DRAFT with current template text.")
        except ClientError as exc:
            print(f"ERROR: update_prompt failed: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            response = client.create_prompt(
                name=args.name,
                description="RAG evaluation KB prompt -- managed by create_eval_prompt.py",
                defaultVariant=DEFAULT_VARIANT_NAME,
                variants=[variant],
            )
        except ClientError as exc:
            print(f"ERROR: create_prompt failed: {exc}", file=sys.stderr)
            sys.exit(1)
        prompt_id = response["id"]
        print(f"Created prompt: {prompt_id} ({args.name})")

    try:
        version_response = client.create_prompt_version(promptIdentifier=prompt_id)
    except ClientError as exc:
        print(f"ERROR: create_prompt_version failed: {exc}", file=sys.stderr)
        sys.exit(1)

    version = version_response.get("version")
    print(f"Published version: {version}")

    print()
    print("Paste this into evaluation/samconfig.toml parameter_overrides:")
    print(f'  PromptResourceId="{prompt_id}"')


if __name__ == "__main__":
    main()
