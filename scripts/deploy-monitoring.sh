#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

# Namespace, Secret и PV подготавливаются через prepare-monitoring.py.

# Terraform output читает существующий S3 state.
unset AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_PROFILE

AWS_ACCESS_KEY_ID="$(terraform -chdir=terraform/bootstrap \
  output -raw state_access_key)"
AWS_SECRET_ACCESS_KEY="$(terraform -chdir=terraform/bootstrap \
  output -raw state_secret_key)"

test -n "$AWS_ACCESS_KEY_ID"
test -n "$AWS_SECRET_ACCESS_KEY"

export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export AWS_EC2_METADATA_DISABLED=true

MONITORING_NODES="$(terraform -chdir=terraform/infrastructure output -json nodes)"

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

printf '%s\n' "$MONITORING_NODES" |
  python3 scripts/generate-monitoring-values.py

printf '%s\n' "$MONITORING_NODES" |
  python3 scripts/prepare-monitoring.py

unset MONITORING_NODES

CHART_VERSION="$(cat kubernetes/monitoring/chart-version.txt)"
test -n "$CHART_VERSION"
test -s .secrets/monitoring-runtime.json

helm repo add prometheus-community \
  https://prometheus-community.github.io/helm-charts \
  --force-update

HELM_ARGS=(
  monitoring
  prometheus-community/kube-prometheus-stack
  --namespace monitoring
  --version "$CHART_VERSION"
  --values kubernetes/monitoring/values.yaml
  --values .secrets/monitoring-runtime.json
)

helm template "${HELM_ARGS[@]}" >/dev/null

helm upgrade --install "${HELM_ARGS[@]}" \
  --wait \
  --timeout 5m

kubectl --request-timeout=30s -n monitoring get pods,pvc -o wide
