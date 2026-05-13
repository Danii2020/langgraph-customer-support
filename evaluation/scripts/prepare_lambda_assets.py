"""
Copies the two seed files (dataset + thresholds) from their canonical
source locations into evaluation/lambdas/seed_eval_assets/seed_assets/
so that sam build packages them with the Lambda function. The KB prompt
template is NOT seeded here -- it lives in Bedrock Prompt Management
(see create_eval_prompt.py).

Also recomputes the SeedAssetsHash CloudFormation property in
evaluation/template.yaml so that any change to the seed files triggers
a custom-resource Update (and a re-upload) on the next `sam deploy`.
Without this, the seed-eval-assets Lambda's Update branch is a no-op
when bucket names are unchanged, and the S3 copy of the dataset stays
stale even after `sam deploy` succeeds.

Run this once before every sam build:
    python evaluation/scripts/prepare_lambda_assets.py

This script is idempotent: running it multiple times overwrites the files
with the same content -- no side effects.
"""
import hashlib
import os
import re
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
    ]

    copied_sources: list[str] = []
    for src_path, dest_path in files_to_copy:
        if not os.path.isfile(src_path):
            print(f"WARNING: source file not found, skipping: {src_path}")
            continue
        shutil.copy2(src_path, dest_path)
        copied_sources.append(src_path)
        print(f"Copied: {src_path} -> {dest_path}")

    digest = _compute_seed_assets_hash(copied_sources)
    template_path = os.path.join(repo_root, "evaluation", "template.yaml")
    updated = _update_template_hash(template_path, digest)
    if updated:
        print(f"SeedAssetsHash updated in template.yaml: {digest}")
    else:
        print(f"SeedAssetsHash unchanged in template.yaml: {digest}")

    print("\nLambda assets prepared. You can now run: sam build")


def _compute_seed_assets_hash(source_paths: list[str]) -> str:
    """
    SHA-256 of the concatenated seed-file bytes, hashed in sorted-path order
    so the digest is stable across machines and across script runs.
    """
    hasher = hashlib.sha256()
    for path in sorted(source_paths):
        with open(path, "rb") as fh:
            hasher.update(fh.read())
    return hasher.hexdigest()


_HASH_LINE_RE = re.compile(
    r'(SeedAssetsHash:\s*")[0-9a-fA-F]{64}(")'
)


def _update_template_hash(template_path: str, digest: str) -> bool:
    """
    Rewrite the SeedAssetsHash value inside template.yaml. Returns True if
    the file content changed, False if the digest was already current.
    Raises if the marker line is missing -- the template must contain a
    SeedAssetsHash property with a 64-char hex placeholder for this to work.
    """
    with open(template_path, "r", encoding="utf-8") as fh:
        original = fh.read()

    new_text, n_subs = _HASH_LINE_RE.subn(rf'\g<1>{digest}\g<2>', original, count=1)
    if n_subs == 0:
        raise RuntimeError(
            f"Could not find SeedAssetsHash line in {template_path}. "
            "Expected a line like: SeedAssetsHash: \"<64-char-hex>\""
        )
    if new_text == original:
        return False

    with open(template_path, "w", encoding="utf-8") as fh:
        fh.write(new_text)
    return True


if __name__ == "__main__":
    main()
