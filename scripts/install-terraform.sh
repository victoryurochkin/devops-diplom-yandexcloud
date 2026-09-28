#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TF_VERSION="$(cat "$PROJECT_DIR/.terraform-version")"
[[ "$TF_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
test "$(uname -s)" = Linux
test "$(uname -m)" = x86_64
TF_TMP="$(mktemp -d)"
trap 'rm -rf -- "$TF_TMP"' EXIT
TF_ARCHIVE="terraform_${TF_VERSION}_linux_amd64.zip"
TF_BASE="https://releases.hashicorp.com/terraform/$TF_VERSION"
curl --fail --location --retry 3 --connect-timeout 10 --max-time 180 \
  "$TF_BASE/$TF_ARCHIVE" -o "$TF_TMP/$TF_ARCHIVE"
curl --fail --location --retry 3 --connect-timeout 10 --max-time 60 \
  "$TF_BASE/terraform_${TF_VERSION}_SHA256SUMS" -o "$TF_TMP/SHA256SUMS"
(
  cd "$TF_TMP"
  awk -v name="$TF_ARCHIVE" '$2 == name {print}' SHA256SUMS > selected-checksum
  test "$(wc -l < selected-checksum)" -eq 1
  sha256sum --check selected-checksum
)
python3 - "$TF_TMP/$TF_ARCHIVE" "$TF_TMP" <<'PY'
import sys
import zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    archive.extract('terraform', sys.argv[2])
PY
sudo install -o root -g root -m 0755 "$TF_TMP/terraform" /usr/local/bin/terraform
/usr/local/bin/terraform version
