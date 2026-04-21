"""
Set up the S3 bucket with the evaluation dataset, thresholds, and result folders.

Usage:
    python evaluation/scripts/setup_s3.py <bucket-name> [--region us-east-2]
"""
import argparse
import os
import boto3


def main():
    parser = argparse.ArgumentParser(description="Set up S3 bucket for RAG evaluation pipeline")
    parser.add_argument("bucket", help="S3 bucket name")
    parser.add_argument("--region", default="us-east-2")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    base_dir = os.path.join(os.path.dirname(__file__), "..")

    dataset_path = os.path.join(base_dir, "dataset", "evaluation_dataset.jsonl")
    thresholds_path = os.path.join(base_dir, "config", "thresholds.json")

    uploads = [
        (dataset_path, "datasets/retrieval_only_eval.jsonl"),
        (dataset_path, "datasets/rag_eval.jsonl"),
        (thresholds_path, "baselines/thresholds.json"),
    ]

    for local_path, s3_key in uploads:
        s3.upload_file(local_path, args.bucket, s3_key)
        print(f"Uploaded: s3://{args.bucket}/{s3_key}")

    # Create empty "folders" for results output
    for folder in ["results/retrieval_only/", "results/rag/"]:
        s3.put_object(Bucket=args.bucket, Key=folder, Body=b"")
        print(f"Created:  s3://{args.bucket}/{folder}")

    print("\nS3 setup complete.")


if __name__ == "__main__":
    main()
