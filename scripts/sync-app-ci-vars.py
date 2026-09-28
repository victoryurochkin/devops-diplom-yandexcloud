#!/usr/bin/env python3
import ipaddress
import json
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
