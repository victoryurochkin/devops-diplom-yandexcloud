#!/usr/bin/env python3
"""Create a kubeconfig using a short-lived Kubernetes TokenRequest."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile


def kubectl_json(*args):
    command = ["kubectl", "--request-timeout=30s"]
    cache = os.environ.get("DIPLOM_KUBECTL_CACHE_DIR")
    if cache:
        command += ["--cache-dir", cache]
    return json.loads(subprocess.check_output(
        [*command, *args], text=True,
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=(
        Path(__file__).resolve().parent.parent / ".secrets/app-deployer.kubeconfig"
    ))
    args = parser.parse_args()
    os.umask(0o077)
    cluster = kubectl_json(
        "config", "view", "--minify", "--flatten", "--raw",
        "-o", "jsonpath={.clusters[0].cluster}",
    )
    if not cluster["server"].startswith("https://") or not cluster.get("certificate-authority-data"):
        raise SystemExit("Expected an HTTPS API endpoint and a CA certificate")
    request = kubectl_json(
        "-n", "diplom-app", "create", "token", "app-deployer",
        "--duration=2h", "-o", "json",
    )
    status = request["status"]
    expiration = datetime.fromisoformat(status["expirationTimestamp"].replace("Z", "+00:00"))
    if (expiration - datetime.now(timezone.utc)).total_seconds() < 1800:
        raise SystemExit("API issued a token with less than 30 minutes remaining")
    config = {
        "apiVersion": "v1", "kind": "Config",
        "clusters": [{"name": "diplom", "cluster": {
            "server": cluster["server"],
            "certificate-authority-data": cluster["certificate-authority-data"],
        }}],
        "users": [{"name": "app-deployer", "user": {"token": status["token"]}}],
        "contexts": [{"name": "app-deployer", "context": {
            "cluster": "diplom", "user": "app-deployer", "namespace": "diplom-app",
        }}],
        "current-context": "app-deployer",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=args.output.parent,
                                         delete=False, encoding="utf-8") as output:
            temporary = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            json.dump(config, output, indent=2)
            output.write("\n")
        os.replace(temporary, args.output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print("Deployer kubeconfig created; token expires at " + status["expirationTimestamp"])


if __name__ == "__main__":
    main()
