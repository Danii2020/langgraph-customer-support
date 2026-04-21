"""
Upload the KB prompt template to S3.

Usage:
    python evaluation/scripts/upload_prompt_template.py <bucket-name> [--prefix prompts/]
"""
import argparse
import os
import boto3


def main():
    parser = argparse.ArgumentParser(description="Upload KB prompt template to S3")
    parser.add_argument("bucket", help="S3 bucket name")
    parser.add_argument(
        "--prefix",
        default="prompts/",
        help="S3 key prefix (default: prompts/)",
    )
    parser.add_argument(
        "--template",
        default=os.path.join(
            os.path.dirname(__file__), "..", "prompts", "kb_prompt_template.txt"
        ),
        help="Path to the prompt template file",
    )
    parser.add_argument("--region", default="us-east-2")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    key = f"{args.prefix.rstrip('/')}/kb_prompt_template.txt"

    s3.upload_file(args.template, args.bucket, key)
    print(f"Uploaded to s3://{args.bucket}/{key}")


if __name__ == "__main__":
    main()
