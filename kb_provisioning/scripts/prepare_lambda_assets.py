"""
Copies src/data/policies.txt and src/data/data.txt into
kb_provisioning/lambdas/seed_and_ingest/seed_data/ so that sam build
packages them with the Lambda function.

Run this once before every sam build:
    python kb_provisioning/scripts/prepare_lambda_assets.py

This script is idempotent: running it multiple times overwrites the files
with the same content — no side effects.
"""
import os
import shutil


def main() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    src_data_dir = os.path.join(repo_root, "src", "data")
    dest_dir = os.path.join(
        repo_root,
        "kb_provisioning",
        "lambdas",
        "seed_and_ingest",
        "seed_data",
    )

    os.makedirs(dest_dir, exist_ok=True)

    files_to_copy = ["policies.txt", "data.txt"]
    for filename in files_to_copy:
        src_path = os.path.join(src_data_dir, filename)
        dest_path = os.path.join(dest_dir, filename)
        if not os.path.isfile(src_path):
            print(f"WARNING: source file not found, skipping: {src_path}")
            continue
        shutil.copy2(src_path, dest_path)
        print(f"Copied: {src_path} -> {dest_path}")

    print("\nLambda assets prepared. You can now run: sam build")


if __name__ == "__main__":
    main()
