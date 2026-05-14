"""
Provisions the GitHub OIDC IAM role used by the RAG Eval Gate workflow
(.github/workflows/rag-eval-gate.yml) so an attendee can wire their own
fork of the repo to their own AWS account.

What it does, in order:
  1. Creates the GitHub OIDC identity provider in IAM if missing.
     URL:         https://token.actions.githubusercontent.com
     Audience:    sts.amazonaws.com
  2. Creates or updates an IAM role with a trust policy scoped to
     `repo:<org>/<repo>:*` so any branch/PR/workflow in that repo
     can assume it via OIDC -- no static AWS keys live in GitHub.
  3. Puts an inline permissions policy on the role granting the minimum
     set of AWS actions the workflow needs: starting/inspecting the
     eval Step Functions execution, listing the Bedrock-managed prompt,
     and reading the eval stack outputs.

Idempotent: re-running updates the trust + permissions policies in place.

Usage:
    python evaluation/scripts/setup_github_oidc.py \\
        --repo Danii2020/langgraph-customer-support

To tear down:
    python evaluation/scripts/setup_github_oidc.py \\
        --repo Danii2020/langgraph-customer-support --delete
"""
import argparse
import json
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError


GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_HOSTNAME = "token.actions.githubusercontent.com"
GITHUB_OIDC_AUDIENCE = "sts.amazonaws.com"

DEFAULT_ROLE_NAME = "gh-actions-rag-eval-gate"
DEFAULT_STACK_NAME = "rag-eval-pipeline"
DEFAULT_REGION = "us-east-1"
PERMISSIONS_POLICY_NAME = "rag-eval-gate-permissions"


def get_account_id(region: str) -> str:
    sts = boto3.client("sts", region_name=region)
    return sts.get_caller_identity()["Account"]


def find_github_oidc_provider_arn(iam: Any) -> str | None:
    """Return the ARN of the GitHub OIDC provider in this account, or None."""
    response = iam.list_open_id_connect_providers()
    for entry in response.get("OpenIDConnectProviderList", []):
        arn = entry.get("Arn", "")
        if arn.endswith(f":oidc-provider/{GITHUB_OIDC_HOSTNAME}"):
            return arn
    return None


def ensure_github_oidc_provider(iam: Any) -> str:
    """Create the GitHub OIDC provider if missing. Returns its ARN."""
    existing = find_github_oidc_provider_arn(iam)
    if existing:
        print(f"OIDC provider already exists: {existing}")
        return existing

    # IAM ignores thumbprints for token.actions.githubusercontent.com
    # since 2023 (AWS validates the cert chain server-side), but the
    # CreateOpenIDConnectProvider API still requires the parameter, so
    # we pass a single placeholder. AWS docs:
    # https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html
    response = iam.create_open_id_connect_provider(
        Url=GITHUB_OIDC_URL,
        ClientIDList=[GITHUB_OIDC_AUDIENCE],
        ThumbprintList=["ffffffffffffffffffffffffffffffffffffffff"],
    )
    arn = response["OpenIDConnectProviderArn"]
    print(f"Created OIDC provider: {arn}")
    return arn


def build_trust_policy(provider_arn: str, repo: str) -> dict[str, Any]:
    """Trust policy: only the named repo can assume the role via OIDC."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": provider_arn},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        f"{GITHUB_OIDC_HOSTNAME}:aud": GITHUB_OIDC_AUDIENCE
                    },
                    "StringLike": {
                        f"{GITHUB_OIDC_HOSTNAME}:sub": f"repo:{repo}:*"
                    },
                },
            }
        ],
    }


def build_permissions_policy(
    region: str, account_id: str, stack_name: str
) -> dict[str, Any]:
    """Minimum IAM permissions the rag-eval-gate workflow needs."""
    state_machine_name = f"{stack_name}-eval-pipeline"
    state_machine_arn = (
        f"arn:aws:states:{region}:{account_id}:stateMachine:{state_machine_name}"
    )
    execution_arn_pattern = (
        f"arn:aws:states:{region}:{account_id}:execution:{state_machine_name}:*"
    )
    stack_arn_pattern = (
        f"arn:aws:cloudformation:{region}:{account_id}:stack/{stack_name}/*"
    )
    prompt_arn_pattern = f"arn:aws:bedrock:{region}:{account_id}:prompt/*"

    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "StartAndInspectEvalExecutions",
                "Effect": "Allow",
                "Action": ["states:StartExecution"],
                "Resource": state_machine_arn,
            },
            {
                "Sid": "ReadExecutionStatusAndHistory",
                "Effect": "Allow",
                "Action": [
                    "states:DescribeExecution",
                    "states:GetExecutionHistory",
                ],
                "Resource": execution_arn_pattern,
            },
            {
                "Sid": "ReadEvalStackOutputs",
                "Effect": "Allow",
                "Action": ["cloudformation:DescribeStacks"],
                "Resource": stack_arn_pattern,
            },
            {
                # IAM uses `bedrock:` prefix even though the boto3 client
                # is `bedrock-agent`. ListPrompts has no resource-level
                # scoping in some regions, so we pair it with a `*` and
                # let GetPrompt enforce the prompt-ARN scope.
                "Sid": "ResolvePromptVersion",
                "Effect": "Allow",
                "Action": ["bedrock:ListPrompts"],
                "Resource": "*",
            },
            {
                "Sid": "GetPromptVersionDetails",
                "Effect": "Allow",
                "Action": ["bedrock:GetPrompt"],
                "Resource": prompt_arn_pattern,
            },
        ],
    }


def upsert_role(
    iam: Any,
    role_name: str,
    trust_policy: dict[str, Any],
    permissions_policy: dict[str, Any],
) -> str:
    """Create the role if missing, otherwise refresh its trust + inline policy. Returns the role ARN."""
    trust_json = json.dumps(trust_policy)
    try:
        existing = iam.get_role(RoleName=role_name)
        role_arn = existing["Role"]["Arn"]
        print(f"Reusing existing role: {role_arn}")
        iam.update_assume_role_policy(
            RoleName=role_name, PolicyDocument=trust_json
        )
        print("Refreshed trust policy.")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=trust_json,
            Description="GitHub Actions OIDC role for the RAG eval gate workflow.",
            MaxSessionDuration=3600,
        )
        role_arn = response["Role"]["Arn"]
        print(f"Created role: {role_arn}")

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName=PERMISSIONS_POLICY_NAME,
        PolicyDocument=json.dumps(permissions_policy),
    )
    print(f"Attached inline policy: {PERMISSIONS_POLICY_NAME}")
    return role_arn


def delete_role(iam: Any, role_name: str) -> None:
    """Best-effort teardown: detach inline policies, then delete the role."""
    try:
        policies = iam.list_role_policies(RoleName=role_name).get("PolicyNames", [])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchEntity":
            print(f"Role {role_name} does not exist -- nothing to delete.")
            return
        raise
    for policy_name in policies:
        iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
        print(f"Removed inline policy: {policy_name}")
    iam.delete_role(RoleName=role_name)
    print(f"Deleted role: {role_name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Provision (or remove) the GitHub OIDC role used by the "
            "RAG eval gate workflow."
        )
    )
    parser.add_argument(
        "--repo",
        required=True,
        help=(
            "GitHub repository in 'org/repo' form (e.g. "
            "'Danii2020/langgraph-customer-support'). Only this repo will "
            "be permitted to assume the role."
        ),
    )
    parser.add_argument(
        "--role-name",
        default=DEFAULT_ROLE_NAME,
        help=f"IAM role name (default: {DEFAULT_ROLE_NAME}).",
    )
    parser.add_argument(
        "--stack-name",
        default=DEFAULT_STACK_NAME,
        help=(
            f"Eval pipeline CloudFormation stack name (default: "
            f"{DEFAULT_STACK_NAME}). Used to scope the inline policy to the "
            "right Step Functions state machine."
        ),
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"AWS region (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the role + inline policy. The OIDC provider is left in place.",
    )
    args = parser.parse_args()

    if "/" not in args.repo or args.repo.count("/") != 1:
        print(
            f"ERROR: --repo must be in 'org/repo' form (got: {args.repo!r})",
            file=sys.stderr,
        )
        sys.exit(1)

    iam = boto3.client("iam")

    if args.delete:
        delete_role(iam, args.role_name)
        return

    account_id = get_account_id(args.region)
    provider_arn = ensure_github_oidc_provider(iam)
    trust_policy = build_trust_policy(provider_arn, args.repo)
    permissions_policy = build_permissions_policy(
        args.region, account_id, args.stack_name
    )
    role_arn = upsert_role(iam, args.role_name, trust_policy, permissions_policy)

    print()
    print("Setup complete. Next steps:")
    print("  1. Open your GitHub repo -> Settings -> Secrets and variables -> Actions -> Variables tab.")
    print("  2. Add (or update) these two repository variables:")
    print(f"       AWS_ACCOUNT_ID         = {account_id}")
    print(f"       AWS_GH_OIDC_ROLE_NAME  = {args.role_name}")
    print("  3. Open a PR that touches one of the eval-relevant paths declared")
    print("     in .github/workflows/rag-eval-gate.yml to trigger the gate.")
    print()
    print(f"Role ARN: {role_arn}")


if __name__ == "__main__":
    main()
