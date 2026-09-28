#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
test "$#" -gt 0
EXPECTED_TF="$(cat .terraform-version)"
ACTUAL_TF="$(terraform version -json | python3 -c 'import json,sys; print(json.load(sys.stdin)["terraform_version"])')"
if [ "$ACTUAL_TF" != "$EXPECTED_TF" ]; then
  printf 'Required Terraform %s; installed %s\n' "$EXPECTED_TF" "$ACTUAL_TF" >&2
  exit 1
fi
unset YC_TOKEN AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_PROFILE
export YC_SERVICE_ACCOUNT_KEY_FILE="$PROJECT_DIR/.secrets/terraform-sa-key.json"
test -s "$YC_SERVICE_ACCOUNT_KEY_FILE"
AWS_ACCESS_KEY_ID="$(terraform -chdir=terraform/bootstrap output -raw state_access_key)"
AWS_SECRET_ACCESS_KEY="$(terraform -chdir=terraform/bootstrap output -raw state_secret_key)"
test -n "$AWS_ACCESS_KEY_ID"
test -n "$AWS_SECRET_ACCESS_KEY"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_EC2_METADATA_DISABLED=true
export TF_CLI_ARGS_plan=-lock-timeout=5m
export TF_CLI_ARGS_apply=-lock-timeout=5m
export TF_CLI_ARGS_destroy=-lock-timeout=5m
export TF_CLI_ARGS_import=-lock-timeout=5m
exec "$@"
