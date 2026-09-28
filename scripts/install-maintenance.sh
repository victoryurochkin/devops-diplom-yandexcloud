#!/usr/bin/env bash
set -euo pipefail
umask 077

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ADMIN_CONFIG="${1:?Usage: sudo $0 /absolute/path/to/admin.kubeconfig}"
test "$(id -u)" -eq 0
[[ "$PROJECT_DIR" =~ ^/[a-zA-Z0-9_./-]+$ ]]
[[ "$ADMIN_CONFIG" =~ ^/[a-zA-Z0-9_./-]+$ ]]
test -s "$ADMIN_CONFIG"
test -s "$PROJECT_DIR/.secrets/maintenance-outputs.json"
test -s "$PROJECT_DIR/.secrets/terraform-sa-key.json"
test -x "$PROJECT_DIR/.secrets/registry-tools/bin/python"
id diplom-runner >/dev/null

cat > /etc/systemd/system/diplom-maintenance.service <<UNIT
[Unit]
Description=Restart diploma workers and renew CD access
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_DIR
Environment=KUBECONFIG=$ADMIN_CONFIG
Environment=YC_SERVICE_ACCOUNT_KEY_FILE=$PROJECT_DIR/.secrets/terraform-sa-key.json
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$PROJECT_DIR/.secrets/registry-tools/bin/python $PROJECT_DIR/scripts/maintain-stand.py --apply
TimeoutStartSec=10min
UMask=0077
UNIT

cat > /etc/systemd/system/diplom-maintenance.timer <<'UNIT'
[Unit]
Description=Check diploma workers and CD access every two minutes

[Timer]
OnBootSec=1min
OnUnitInactiveSec=2min
AccuracySec=15s
Unit=diplom-maintenance.service

[Install]
WantedBy=timers.target
UNIT

chmod 0644 /etc/systemd/system/diplom-maintenance.service \
  /etc/systemd/system/diplom-maintenance.timer
systemctl daemon-reload
systemctl enable --now diplom-maintenance.timer
systemctl start diplom-maintenance.service
systemctl --no-pager status diplom-maintenance.timer
