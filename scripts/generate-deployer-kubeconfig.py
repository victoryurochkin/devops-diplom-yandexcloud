#!/usr/bin/env python3
import base64
import json
import os
from pathlib import Path
import subprocess
import time

os.umask(0o077)
project = Path(__file__).resolve().parent.parent

def kubectl_json(*args):
    return json.loads(subprocess.check_output(
        ["kubectl", "--request-timeout=20s", *args],
        text=True,
    ))

cluster = kubectl_json(
    "config", "view", "--minify", "--flatten", "--raw",
    "-o", "jsonpath={.clusters[0].cluster}",
)
server = cluster["server"]
ca = cluster.get("certificate-authority-data")
if not server.startswith("https://") or not ca:
    raise SystemExit("Ожидались HTTPS API и сертификат CA")

for attempt in range(30):
    secret = kubectl_json(
        "-n", "diplom-app", "get", "secret",
        "app-deployer-token", "-o", "json",
    )
    token_data = secret.get("data", {}).get("token")
    if token_data:
        break
    time.sleep(1)
else:
    raise SystemExit("Контроллер пока не создал токен")

config = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [{
        "name": "diplom",
        "cluster": {
            "server": server,
            "certificate-authority-data": ca,
        },
    }],
    "users": [{
        "name": "app-deployer",
        "user": {
            "token": base64.b64decode(token_data).decode(),
        },
    }],
    "contexts": [{
        "name": "app-deployer",
        "context": {
            "cluster": "diplom",
            "user": "app-deployer",
            "namespace": "diplom-app",
        },
    }],
    "current-context": "app-deployer",
}

path = project / ".secrets/app-deployer.kubeconfig"
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("w") as output:
    os.fchmod(output.fileno(), 0o600)
    json.dump(config, output, indent=2)
    output.write("\n")

print("Kubeconfig app-deployer создан; токен не выводится")
