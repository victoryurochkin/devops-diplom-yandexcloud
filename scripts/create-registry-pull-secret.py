#!/usr/bin/env python3
import base64
import json
from pathlib import Path
import subprocess

project = Path(__file__).resolve().parent.parent
key_path = project / ".secrets/registry-puller-key.json"
key_text = key_path.read_text()
key = json.loads(key_text)

expected_id = subprocess.check_output(
    [
        "terraform",
        f"-chdir={project / 'terraform/bootstrap'}",
        "output", "-raw", "registry_puller_service_account_id",
    ],
    text=True,
).strip()

if key.get("service_account_id") != expected_id:
    raise SystemExit("Ключ принадлежит другому сервисному аккаунту")
if not key.get("private_key"):
    raise SystemExit("В файле отсутствует приватный ключ")

auth = base64.b64encode(
    f"json_key:{key_text}".encode()
).decode()

docker_config = {
    "auths": {
        "cr.yandex": {
            "auth": auth,
        },
    },
}

secret = {
    "apiVersion": "v1",
    "kind": "Secret",
    "metadata": {
        "name": "yc-registry",
        "namespace": "diplom-app",
    },
    "type": "kubernetes.io/dockerconfigjson",
    "data": {
        ".dockerconfigjson": base64.b64encode(
            json.dumps(docker_config).encode()
        ).decode(),
    },
}

result = subprocess.run(
    [
        "kubectl", "--request-timeout=30s",
        "apply", "--server-side",
        "--field-manager=diplom-registry-secret",
        "-f", "-",
    ],
    input=json.dumps(secret),
    text=True,
    capture_output=True,
)
if result.returncode:
    raise SystemExit(
        "Не удалось применить Secret. Вывод kubectl скрыт, "
        "чтобы исключить вывод ключа. Пришли это сообщение."
    )

print("Secret diplom-app/yc-registry настроен")
