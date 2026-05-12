"""
Copies the three seed files from their canonical source locations into
evaluation/lambdas/seed_eval_assets/seed_assets/ so that sam build packages
them with the Lambda function.

Run this once before every sam build:
    python evaluation/scripts/prepare_lambda_assets.py

This script is idempotent: running it multiple times overwrites the files
with the same content -- no side effects.
"""
import os
import shutil


def main() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    dest_dir = os.path.join(
        repo_root,
        "evaluation",
        "lambdas",
        "seed_eval_assets",
        "seed_assets",
    )

    os.makedirs(dest_dir, exist_ok=True)

    files_to_copy = [
        (
            os.path.join(repo_root, "evaluation", "dataset", "evaluation_dataset.jsonl"),
            os.path.join(dest_dir, "evaluation_dataset.jsonl"),
        ),
        (
            os.path.join(repo_root, "evaluation", "config", "thresholds.json"),
            os.path.join(dest_dir, "thresholds.json"),
        ),
        (
            os.path.join(repo_root, "evaluation", "prompts", "kb_prompt_template.txt"),
            os.path.join(dest_dir, "kb_prompt_template.txt"),
        ),
    ]

    for src_path, dest_path in files_to_copy:
        if not os.path.isfile(src_path):
            print(f"WARNING: source file not found, skipping: {src_path}")
            continue
        shutil.copy2(src_path, dest_path)
        print(f"Copied: {src_path} -> {dest_path}")

    print("\nLambda assets prepared. You can now run: sam build")


if __name__ == "__main__":
    main()
