"""
Provisions a workshop S3 bucket and uploads the evaluation seed files
(RAG dataset + retrieval-only dataset + KB prompt template + both
threshold files) so workshop attendees can run manual Bedrock evaluation
jobs (via the Bedrock console or CLI) before deploying the automated
evaluation pipeline. Both job flavors are supported: retrieve-and-generate
and retrieve-only.

Run after the kb_provisioning stack is deployed:
    python evaluation/scripts/setup_manual_eval_assets.py

Idempotent: reuses an existing bucket if it is already owned by the caller
and overwrites the keys on every run.

This bucket is independent of the SAM-managed EvalBucket/ResultsBucket --
the SAM stack continues to provision and seed its own buckets when the
evaluation pipeline is deployed later in the workshop.
"""
import argparse
import os
import sys

import boto3
from botocore.exceptions import ClientError


BUCKET_PREFIX = "workshop-rag-eval"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create a workshop S3 bucket and upload the evaluation seed "
            "files (RAG + retrieval-only datasets + prompt template + both "
            "thresholds files) for the manual Bedrock evaluation job demo."
        )
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1, matching the eval pipeline).",
    )
    parser.add_argument(
        "--bucket",
        default=None,
        help=(
            "Override the auto-generated bucket name. Defaults to "
            f"{BUCKET_PREFIX}-<account-id>-<region>."
        ),
    )
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    files_to_upload = [
        (
            os.path.join(repo_root, "evaluation", "dataset", "evaluation_dataset.jsonl"),
            "evaluation_dataset.jsonl",
        ),
        (
            os.path.join(repo_root, "evaluation", "dataset", "retrieval_eval_dataset.jsonl"),
            "retrieval_eval_dataset.jsonl",
        ),
        (
            os.path.join(repo_root, "evaluation", "prompts", "kb_prompt_template.txt"),
            "kb_prompt_template.txt",
        ),
        (
            os.path.join(repo_root, "evaluation", "config", "thresholds.json"),
            "thresholds.json",
        ),
        (
            os.path.join(repo_root, "evaluation", "config", "retrieval_thresholds.json"),
            "retrieval_thresholds.json",
        ),
    ]

    missing = [src for src, _ in files_to_upload if not os.path.isfile(src)]
    if missing:
        print("ERROR: source file(s) not found:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        sys.exit(1)

    if args.bucket:
        bucket_name = args.bucket
    else:
        sts = boto3.client("sts", region_name=args.region)
        account_id = sts.get_caller_identity()["Account"]
        bucket_name = f"{BUCKET_PREFIX}-{account_id}-{args.region}"

    s3 = boto3.client("s3", region_name=args.region)

    try:
        if args.region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": args.region},
            )
        print(f"Created bucket: s3://{bucket_name}")
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "BucketAlreadyOwnedByYou":
            print(f"Reusing existing bucket: s3://{bucket_name}")
        elif code == "BucketAlreadyExists":
            print(
                f"ERROR: bucket name '{bucket_name}' is already taken by "
                "another AWS account. Re-run with --bucket <unique-name>.",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            raise

    for src_path, key in files_to_upload:
        s3.upload_file(src_path, bucket_name, key)
        print(f"Uploaded: s3://{bucket_name}/{key}")

    s3.put_object(Bucket=bucket_name, Key="results/")
    print(f"Created folder: s3://{bucket_name}/results/")

    print()
    print("Manual evaluation assets ready. Plug these into the Bedrock console:")
    print()
    print("Retrieve-and-generate job:")
    print(f"  Prompt dataset:    s3://{bucket_name}/evaluation_dataset.jsonl")
    print(f"  Prompt template:   s3://{bucket_name}/kb_prompt_template.txt")
    print(f"  Thresholds:        s3://{bucket_name}/thresholds.json")
    print(f"  Output S3 prefix:  s3://{bucket_name}/results/")
    print()
    print("Retrieve-only job:")
    print(f"  Prompt dataset:    s3://{bucket_name}/retrieval_eval_dataset.jsonl")
    print(f"  Thresholds:        s3://{bucket_name}/retrieval_thresholds.json")
    print(f"  Output S3 prefix:  s3://{bucket_name}/results/")


if __name__ == "__main__":
    main()
