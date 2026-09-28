#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

# Эти ресурсы подготавливаются до установки Helm-релиза.
kubectl --request-timeout=30s -n monitoring \
  get secret grafana-admin >/dev/null

kubectl --request-timeout=30s get pv \
  monitoring-prometheus \
  monitoring-grafana \
  monitoring-alertmanager >/dev/null

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

terraform -chdir=terraform/infrastructure output -json nodes |
  python3 scripts/generate-monitoring-values.py

unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

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
