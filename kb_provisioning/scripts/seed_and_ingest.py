"""
Fallback CLI for seeding the source S3 bucket and starting an ingestion job.

Use this when:
  - EnableAutoIngestion=false was passed to sam deploy, OR
  - The custom resource Lambda hit IAM friction during stack creation, OR
  - You want to re-sync after uploading new documents to src/data/.

Usage:
    python kb_provisioning/scripts/seed_and_ingest.py \\
        --stack-name kb-provisioning \\
        --region us-east-1

    # To re-sync with a custom data directory:
    python kb_provisioning/scripts/seed_and_ingest.py \\
        --stack-name kb-provisioning \\
        --region us-east-1 \\
        --data-dir path/to/my/docs/

The script reads SourceBucketName, SourceDataPrefix, KnowledgeBaseId, and
DataSourceId from the CloudFormation stack outputs, so the stack must already
be deployed before running this script.
"""
import argparse
import os
import boto3


def get_stack_outputs(cfn_client: object, stack_name: str) -> dict[str, str]:
    """Retrieve all stack outputs as a flat key→value dict."""
    response = cfn_client.describe_stacks(StackName=stack_name)
    stacks = response.get("Stacks", [])
    if not stacks:
        raise RuntimeError(f"Stack '{stack_name}' not found.")
    outputs = stacks[0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def upload_data_files(s3_client: object, data_dir: str, bucket: str, prefix: str) -> list[str]:
    """Upload every regular file in data_dir to s3://bucket/prefix<filename>."""
    uploaded: list[str] = []
    if not os.path.isdir(data_dir):
        raise FileNotFoundError(f"Data directory not found: {data_dir}")
    for filename in sorted(os.listdir(data_dir)):
        local_path = os.path.join(data_dir, filename)
        if not os.path.isfile(local_path):
            continue
        s3_key = f"{prefix}{filename}"
        print(f"Uploading: {local_path} -> s3://{bucket}/{s3_key}")
        s3_client.upload_file(local_path, bucket, s3_key)
        uploaded.append(s3_key)
    return uploaded


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the source S3 bucket and start a Bedrock KB ingestion job."
    )
    parser.add_argument(
        "--stack-name",
        default="kb-provisioning",
        help="CloudFormation stack name (default: kb-provisioning).",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region (default: us-east-1).",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help=(
            "Local directory containing files to upload "
            "(default: src/data/ relative to the repository root)."
        ),
    )
    args = parser.parse_args()

    region = args.region
    stack_name = args.stack_name

    # Resolve data directory: default to <repo_root>/src/data/
    if args.data_dir:
        data_dir = os.path.abspath(args.data_dir)
    else:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        data_dir = os.path.join(repo_root, "src", "data")

    print(f"Stack:      {stack_name}")
    print(f"Region:     {region}")
    print(f"Data dir:   {data_dir}")
    print()

    cfn_client = boto3.client("cloudformation", region_name=region)
    print(f"Reading outputs from stack '{stack_name}'...")
    outputs = get_stack_outputs(cfn_client, stack_name)

    bucket = outputs.get("SourceBucketName")
    prefix = outputs.get("SourceDataPrefix") or "data/"
    kb_id = outputs.get("KnowledgeBaseId")
    ds_id = outputs.get("DataSourceId")

    if not bucket:
        raise RuntimeError("Stack output 'SourceBucketName' not found.")
    if not kb_id:
        raise RuntimeError("Stack output 'KnowledgeBaseId' not found.")
    if not ds_id:
        raise RuntimeError("Stack output 'DataSourceId' not found.")

    print(f"Source bucket: {bucket}")
    print(f"Key prefix:    {prefix}")
    print(f"Knowledge base: {kb_id}")
    print(f"Data source:    {ds_id}")
    print()

    s3_client = boto3.client("s3", region_name=region)
    uploaded = upload_data_files(s3_client, data_dir, bucket, prefix)
    print(f"\nUploaded {len(uploaded)} file(s).")

    bedrock_agent = boto3.client("bedrock-agent", region_name=region)
    print("\nStarting ingestion job...")
    response = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )
    job_id = response.get("ingestionJob", {}).get("ingestionJobId", "unknown")
    print(f"Ingestion job started: {job_id}")
    print(
        f"\nMonitor with:\n"
        f"  aws bedrock-agent list-ingestion-jobs "
        f"--knowledge-base-id {kb_id} "
        f"--data-source-id {ds_id} "
        f"--region {region}"
    )


if __name__ == "__main__":
    main()
