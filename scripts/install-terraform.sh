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
awk -v name="$TF_ARCHIVE" '$2 == name {print}' \
  "$PROJECT_DIR/terraform/SHA256SUMS" > "$TF_TMP/selected-checksum"
test "$(wc -l < "$TF_TMP/selected-checksum")" -eq 1
TF_DOWNLOADED=false
for TF_HOST in releases.hashicorp.com hashicorp-releases.yandexcloud.net; do
  if curl --fail --location --retry 3 --connect-timeout 10 --max-time 180 \
    "https://$TF_HOST/terraform/$TF_VERSION/$TF_ARCHIVE" \
    -o "$TF_TMP/$TF_ARCHIVE"
  then
    TF_DOWNLOADED=true
    break
  fi
done
test "$TF_DOWNLOADED" = true
(
  cd "$TF_TMP"
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
