#!/usr/bin/env python3
import ipaddress
import json
import os
from pathlib import Path
import tempfile
import re
import subprocess
import sys

outputs = json.load(sys.stdin)
nodes = outputs["nodes"]["value"]
repository = outputs["app_image_repository"]["value"]

if not re.fullmatch(
    r"cr\.yandex/[a-z0-9]+/devops-diplom-app",
    repository,
):
    raise SystemExit("Неожиданный адрес репозитория образов")

worker_ips = []
for name in ("worker-1", "worker-2"):
    address = str(ipaddress.IPv4Address(nodes[name]["public_ip"]))
    worker_ips.append(address)

if len(set(worker_ips)) != 2:
    raise SystemExit("Ожидались разные публичные адреса workers")

values = {
    "IMAGE_REPOSITORY": repository,
    "APP_WORKER_IPS": " ".join(worker_ips),
}

for name, value in values.items():
    subprocess.run(
        [
            "gh", "variable", "set", name,
            "--repo", "victoryurochkin/devops-diplom-app",
            "--body", value,
        ],
        check=True,
    )
    print(f"{name}={value}")

# Maintenance uses only public resource metadata, never state or credentials.
project = Path(__file__).resolve().parent.parent
path = project / ".secrets/maintenance-outputs.json"
path.parent.mkdir(parents=True, exist_ok=True)
selected = {name: outputs[name] for name in ("folder_id", "nodes")}
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
    temporary = Path(output.name)
    os.fchmod(output.fileno(), 0o600)
    json.dump(selected, output, indent=2)
    output.write("\n")
try:
    os.replace(temporary, path)
finally:
    temporary.unlink(missing_ok=True)
print("Maintenance node configuration updated")
