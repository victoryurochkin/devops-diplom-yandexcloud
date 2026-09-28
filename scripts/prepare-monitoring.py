#!/usr/bin/env python3
import base64
import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

os.umask(0o077)
project = Path(__file__).resolve().parent.parent
os.chdir(project)

nodes = json.load(sys.stdin)
if set(nodes) != {"cp-1", "worker-1", "worker-2"}:
    raise SystemExit("Неожиданный список узлов Terraform")

addresses = {
    name: str(ipaddress.IPv4Address(nodes[name]["public_ip"]))
    for name in ("worker-1", "worker-2")
}

ssh_key = Path(
    os.environ.get("DIPLOM_SSH_KEY", "~/.ssh/id_ed25519")
).expanduser().resolve()
known_hosts = Path(
    os.environ.get("DIPLOM_KNOWN_HOSTS", "~/.ssh/known_hosts")
).expanduser().resolve()

for path in (ssh_key, known_hosts):
    if not path.is_file():
        raise SystemExit(f"Не найден файл: {path}")

kubectl = ["kubectl", "--request-timeout=30s"]

subprocess.run(
    kubectl + [
        "apply", "-f", "kubernetes/monitoring/namespace.yaml",
    ],
    check=True,
)

raw = subprocess.check_output(
    kubectl + [
        "-n", "monitoring", "get", "secret", "grafana-admin",
        "--ignore-not-found", "-o", "json",
    ],
    text=True,
)
current = json.loads(raw) if raw.strip() else None


def secret_document(obj):
    try:
        data = {}
        for key in ("admin-user", "admin-password"):
            value = base64.b64decode(obj["data"][key], validate=True)
            if not value:
                raise ValueError("Пустое значение")
            data[key] = base64.b64encode(value).decode("ascii")
    except (KeyError, TypeError, ValueError):
        raise SystemExit("Некорректные данные Secret Grafana")

    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": "grafana-admin",
            "namespace": "monitoring",
        },
        "type": "Opaque",
        "data": data,
    }


backup = project / ".secrets/grafana-admin-secret.json"
backup.parent.mkdir(parents=True, exist_ok=True)

saved = None
if backup.exists():
    saved = secret_document(json.loads(backup.read_text()))
    backup.chmod(0o600)

if current is not None:
    desired = secret_document(current)
    if saved is not None and saved["data"] != desired["data"]:
        raise SystemExit(
            "Локальная копия и Secret Grafana различаются. "
            "Учётные данные не изменены."
        )
elif saved is not None:
    desired = saved
else:
    raise SystemExit(
        "Нет Secret Grafana и его локальной копии. "
        "Восстановление учётных данных невозможно."
    )

if saved is None:
    with backup.open("x", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        json.dump(desired, output, indent=2)
        output.write("\n")
    print("Копия Secret сохранена: .secrets/grafana-admin-secret.json",
          flush=True)
else:
    print("Локальная копия Secret проверена", flush=True)

directories = {
    "worker-1": [
        "/var/lib/diplom-monitoring/grafana",
        "/var/lib/diplom-monitoring/alertmanager",
    ],
    "worker-2": [
        "/var/lib/diplom-monitoring/prometheus",
    ],
}

for name, paths in directories.items():
    print(f"Подготовка каталогов: {name}", flush=True)
    command = shlex.join([
        "sudo", "-n", "mkdir", "-p", "-m", "0755", "--", *paths,
    ])
    subprocess.run(
        [
            "ssh",
            "-i", str(ssh_key),
            "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", "ConnectTimeout=15",
            f"ubuntu@{addresses[name]}",
            command,
        ],
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=True,
    )

subprocess.run(
    kubectl + [
        "apply", "-f", "kubernetes/monitoring/storage.json",
    ],
    check=True,
)

if current is None:
    result = subprocess.run(
        kubectl + ["create", "-f", "-"],
        input=json.dumps(desired),
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise SystemExit(
            "Не удалось восстановить Secret Grafana. "
            "Вывод команды скрыт, поскольку может содержать секрет."
        )
    print("Secret monitoring/grafana-admin восстановлен")
else:
    print("Secret monitoring/grafana-admin уже существует")

print("Подготовка мониторинга завершена")
