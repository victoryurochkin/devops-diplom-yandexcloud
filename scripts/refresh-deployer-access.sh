#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
id diplom-runner >/dev/null

ROOT=()
if [ "$(id -u)" -ne 0 ]; then
  sudo -v
  ROOT=(sudo -n)
fi

TOKEN_TMP="$(mktemp -d)"
RUNNER_TEMP_CONFIG=""
cleanup() {
  rm -rf -- "$TOKEN_TMP"
  if [ -n "$RUNNER_TEMP_CONFIG" ]; then
    "${ROOT[@]}" rm -f -- "$RUNNER_TEMP_CONFIG"
  fi
}
trap cleanup EXIT

export DIPLOM_KUBECTL_CACHE_DIR="$TOKEN_TMP/cache"
python3 "$PROJECT_DIR/scripts/generate-deployer-kubeconfig.py" \
  --output "$TOKEN_TMP/config"
kubectl --cache-dir="$DIPLOM_KUBECTL_CACHE_DIR" \
  --kubeconfig="$TOKEN_TMP/config" --request-timeout=30s \
  -n diplom-app get deployment diplom-app >/dev/null
kubectl --cache-dir="$DIPLOM_KUBECTL_CACHE_DIR" \
  --kubeconfig="$TOKEN_TMP/config" --request-timeout=30s \
  -n diplom-app auth can-i patch deployment/diplom-app

"${ROOT[@]}" install -d -o diplom-runner -g diplom-runner -m 0700 \
  /home/diplom-runner/.kube
RUNNER_TEMP_CONFIG="$("${ROOT[@]}" mktemp /home/diplom-runner/.kube/config.XXXXXX)"
"${ROOT[@]}" install -o diplom-runner -g diplom-runner -m 0600 \
  "$TOKEN_TMP/config" "$RUNNER_TEMP_CONFIG"
"${ROOT[@]}" mv -f -- "$RUNNER_TEMP_CONFIG" /home/diplom-runner/.kube/config
RUNNER_TEMP_CONFIG=""
printf 'CD runner kubeconfig replaced atomically\n'
