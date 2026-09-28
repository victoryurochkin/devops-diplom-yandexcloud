#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import subprocess
from datetime import datetime, timezone

os.umask(0o077)
os.chdir(Path(__file__).resolve().parent.parent)

kubectl = ["kubectl", "--request-timeout=30s", "-n", "kube-system"]
obj = json.loads(subprocess.check_output(
    kubectl + ["get", "configmap", "kube-proxy", "-o", "json"],
    text=True,
))

config = obj["data"]["config.conf"]
pattern = r"(?m)^metricsBindAddress:[^\r\n]*"
matches = re.findall(pattern, config)
if len(matches) != 1:
    raise SystemExit("Ожидалась одна строка metricsBindAddress")

current = matches[0].split(":", 1)[1].strip().strip("\"'")
desired = "0.0.0.0:10249"
print(f"Текущий адрес: {current}", flush=True)

if current == desired:
    print("ConfigMap уже настроен")
    raise SystemExit(0)

if current != "127.0.0.1:10249":
    raise SystemExit("Неожиданный адрес. ConfigMap не изменён")

backup_dir = Path(".secrets/kube-proxy-backups")
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
backup = backup_dir / f"configmap-{stamp}.json"
backup.write_text(json.dumps(obj, indent=2) + "\n")
print(f"Резервная копия: {backup}", flush=True)

updated = re.sub(
    pattern,
    f"metricsBindAddress: {desired}",
    config,
    count=1,
)

patch = [
    {
        "op": "test",
        "path": "/metadata/resourceVersion",
        "value": obj["metadata"]["resourceVersion"],
    },
    {
        "op": "replace",
        "path": "/data/config.conf",
        "value": updated,
    },
]

subprocess.run(
    kubectl + [
        "patch", "configmap", "kube-proxy",
        "--type=json", "--patch", json.dumps(patch),
    ],
    check=True,
)
