#!/usr/bin/env python3
import ipaddress
import json
import os
from pathlib import Path
import sys

os.umask(0o077)
project = Path(__file__).resolve().parent.parent
nodes = json.load(sys.stdin)

expected = {"cp-1", "worker-1", "worker-2"}
if set(nodes) != expected:
    raise SystemExit(f"Неожиданный список узлов: {sorted(nodes)}")

control_plane_ip = str(
    ipaddress.IPv4Address(nodes["cp-1"]["private_ip"])
)
grafana_ip = str(
    ipaddress.IPv4Address(nodes["worker-1"]["public_ip"])
)
grafana_url = f"http://{grafana_ip}/grafana/"

values = {
    "grafana": {
        "grafana.ini": {
            "server": {
                "root_url": grafana_url,
            },
        },
    },
    "kubeEtcd": {
        "endpoints": [control_plane_ip],
    },
    "kubeControllerManager": {
        "endpoints": [control_plane_ip],
    },
    "kubeScheduler": {
        "endpoints": [control_plane_ip],
    },
}

path = project / ".secrets/monitoring-runtime.json"
path.parent.mkdir(parents=True, exist_ok=True)

with path.open("w", encoding="utf-8") as output:
    os.fchmod(output.fileno(), 0o600)
    json.dump(values, output, indent=2)
    output.write("\n")

print("Создан .secrets/monitoring-runtime.json")
print(f"Адрес метрик control plane: {control_plane_ip}")
print(f"Grafana: {grafana_url}")
