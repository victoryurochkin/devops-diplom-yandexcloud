#!/usr/bin/env python3
"""Pause automation, archive a running stand, and prepare its destroy plan.

Does not apply a Terraform plan or delete cloud resources. Monitoring writers are
stopped for a consistent filesystem backup and restored in a finally block.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time


PROJECT = Path(__file__).resolve().parent.parent
REPOS = ("victoryurochkin/devops-diplom-yandexcloud", "victoryurochkin/devops-diplom-app")
RUNNER = "actions.runner.victoryurochkin-devops-diplom-app.diplom-app-deploy-it.service"
WORKLOADS = (
    ("deployment", "monitoring-grafana", "deployment/monitoring-grafana"),
    ("prometheus", "monitoring-prometheus", "statefulset/prometheus-monitoring-prometheus"),
    ("alertmanager", "monitoring-alertmanager", "statefulset/alertmanager-monitoring-alertmanager"),
)
VOLUMES = {"worker-1": ["grafana", "alertmanager"], "worker-2": ["prometheus"]}


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE, text=True).stdout.strip()


def document(*args):
    return json.loads(output(*args))


def save_command(path, *args):
    with path.open("wb") as stream:
        run(*args, stdout=stream)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def kubectl(*args):
    return ["kubectl", "--request-timeout=30s", *args]


def tf(*args):
    return [PROJECT / "scripts/with-cloud-env.sh", "terraform", "-chdir=terraform/infrastructure", *args]


def wait_until(check, seconds, message):
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() >= deadline:
            raise RuntimeError(message)
        time.sleep(3)


def no_actions():
    active = []
    for repo in REPOS:
        ids = output("gh", "api", "--paginate", f"repos/{repo}/actions/runs?per_page=100",
                     "--jq", '.workflow_runs[] | select(.status != "completed") | .id')
        active.extend(f"{repo}: {i}" for i in ids.splitlines())
    if active:
        print("Waiting for Actions: " + ", ".join(active), flush=True)
    return not active


def pause_automation():
    (PROJECT / ".secrets/maintenance.pause").touch(mode=0o600)
    run("sudo", "systemctl", "disable", "--now", "diplom-maintenance.timer")
    wait_until(lambda: output("systemctl", "show", "diplom-maintenance.service",
                              "--property=ActiveState", "--value") in ("inactive", "failed"),
               660, "Maintenance has not finished")
    for repo, workflow in zip(REPOS, ("terraform.yml", "app.yml")):
        run("gh", "workflow", "disable", workflow, "--repo", repo)
        state = output("gh", "api", f"repos/{repo}/actions/workflows/{workflow}", "--jq", ".state")
        if state != "disabled_manually":
            raise RuntimeError(f"Workflow is still enabled: {repo}")
    wait_until(no_actions, 1200, "Actions have not finished; no resources were deleted")
    run("sudo", "systemctl", "disable", "--now", RUNNER)


def verify_tar(path):
    run("gzip", "-t", path)
    with tarfile.open(path, "r:gz") as archive:
        if not archive.getmembers():
            raise RuntimeError(f"Empty archive: {path}")


def check_space(backup, nodes, ssh_key):
    required = 1024 ** 3
    for worker, directories in VOLUMES.items():
        ip = str(ipaddress.IPv4Address(nodes[worker]["public_ip"]))
        paths = ["/var/lib/diplom-monitoring/" + name for name in directories]
        command = shlex.join(["sudo", "-n", "du", "-sb", "--", *paths])
        sizes = output("ssh", "-i", ssh_key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                       "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15",
                       f"ubuntu@{ip}", command)
        required += sum(int(line.split()[0]) for line in sizes.splitlines())
    available = shutil.disk_usage(backup).free
    if available < required:
        raise RuntimeError(f"Insufficient backup space: need {required} bytes, have {available}")
    print(f"Backup space: {available // 1024**2} MiB available, {required // 1024**2} MiB required",
          flush=True)


def backup_monitoring(backup, nodes, ssh_key):
    resources = [document(*kubectl("-n", "monitoring", "get", kind, name, "-o", "json"))
                 for kind, name, _ in WORKLOADS]
    if any(r.get("spec", {}).get("replicas", 1) != 1 for r in resources):
        raise RuntimeError("Expected one replica for each monitoring writer")
    write_json(backup / "monitoring-workloads.json", resources)
    owners = {}
    grafana_uid = resources[0]["metadata"]["uid"]
    replicasets = document(*kubectl("-n", "monitoring", "get", "replicasets", "-o", "json"))
    for item in replicasets["items"]:
        if any(o["uid"] == grafana_uid for o in item["metadata"].get("ownerReferences", [])):
            owners[item["metadata"]["uid"]] = "grafana"
    for _, _, target in WORKLOADS[1:]:
        item = document(*kubectl("-n", "monitoring", "get", target, "-o", "json"))
        owners[item["metadata"]["uid"]] = target

    def writers_stopped():
        pods = document(*kubectl("-n", "monitoring", "get", "pods", "-o", "json"))["items"]
        active = [p["metadata"]["name"] for p in pods
                  if any(o["uid"] in owners for o in p["metadata"].get("ownerReferences", []))]
        if active:
            print("Waiting for monitoring writers: " + ", ".join(active), flush=True)
        return not active

    changed = []
    try:
        for resource, (kind, name, _) in zip(resources, WORKLOADS):
            changed.append((kind, name, resource["spec"].get("replicas", 1)))
            run(*kubectl("-n", "monitoring", "patch", kind, name, "--type=merge",
                         "-p", '{"spec":{"replicas":0}}'))
        wait_until(writers_stopped, 300, "Monitoring writers are still running")
        for worker, directories in VOLUMES.items():
            ip = str(ipaddress.IPv4Address(nodes[worker]["public_ip"]))
            if nodes[worker]["ssh_user"] != "ubuntu":
                raise RuntimeError("Unexpected SSH user")
            command = shlex.join(["sudo", "-n", "tar", "--numeric-owner", "--acls", "--xattrs",
                                  "-C", "/var/lib/diplom-monitoring", "-czpf", "-", "--", *directories])
            path = backup / f"monitoring-{worker}.tar.gz"
            print("Archiving monitoring data: " + worker, flush=True)
            with path.open("wb") as stream:
                run("ssh", "-i", ssh_key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=15",
                    "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
                    f"ubuntu@{ip}", command, stdin=subprocess.DEVNULL, stdout=stream, timeout=1800)
            verify_tar(path)
    finally:
        failed = []
        for kind, name, replicas in changed:
            try:
                run(*kubectl("-n", "monitoring", "patch", kind, name, "--type=merge",
                             "-p", json.dumps({"spec": {"replicas": replicas}})))
            except subprocess.CalledProcessError:
                failed.append(name)
        if failed:
            raise RuntimeError("Restore monitoring replicas manually: " + ", ".join(failed))
    for _, _, target in WORKLOADS:
        # The operator reconciles StatefulSet replica counts asynchronously.
        wait_until(lambda target=target: document(*kubectl("-n", "monitoring", "get", target,
                                                          "-o", "json"))["spec"].get("replicas") == 1,
                   120, "Operator did not restore replicas: " + target)
        run("kubectl", "--request-timeout=330s", "-n", "monitoring", "rollout", "status",
            target, "--timeout=300s")


def validate_destroy(plan, state, folder_id):
    expected = {"yandex_vpc_network.diplom", "yandex_container_registry.diplom",
                "yandex_vpc_security_group.cluster", "yandex_vpc_security_group.web"}
    expected.update(f'yandex_vpc_subnet.diplom["{zone}"]' for zone in ("a", "b", "d"))
    for name in ("cp-1", "worker-1", "worker-2"):
        expected.update((f'yandex_compute_instance.node["{name}"]', f'yandex_vpc_address.node["{name}"]'))
    changes = [r for r in plan.get("resource_changes", [])
               if r.get("mode") == "managed" and r["change"]["actions"] != ["no-op"]]
    if {r["address"] for r in changes} != expected or len(changes) != 13:
        raise RuntimeError("Destroy plan differs from the expected 13 infrastructure resources")
    if any(r["change"]["actions"] != ["delete"] for r in changes):
        raise RuntimeError("Unexpected non-delete action")
    saved_ids = set()
    for resource in state.get("resources", []):
        if resource.get("mode") == "managed":
            saved_ids.update(instance["attributes"]["id"] for instance in resource["instances"])
    planned_ids = {r["change"]["before"]["id"] for r in changes}
    if len(saved_ids) != 13 or planned_ids != saved_ids:
        raise RuntimeError("Planned resource IDs differ from the archived state")
    if any(r["change"]["before"].get("folder_id") != folder_id for r in changes):
        raise RuntimeError("Planned resources belong to an unexpected folder")
    return [f'delete: {r["address"]} — {r["change"]["before"]["id"]}' for r in changes]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path, default=Path.home() / "devops-diplom-app")
    parser.add_argument("--ssh-key", type=Path, default=Path.home() / ".ssh/id_ed25519")
    args = parser.parse_args()
    os.umask(0o077)
    os.chdir(PROJECT)
    application = args.application.expanduser().resolve()
    ssh_key = args.ssh_key.expanduser().resolve()
    os.environ.setdefault("KUBECONFIG", str(Path.home() / ".kube/config"))
    os.environ.setdefault("TF_CLI_CONFIG_FILE", str(PROJECT / ".secrets/terraformrc"))
    for command in ("git", "gh", "terraform", "kubectl", "helm", "docker", "skopeo", "ssh", "gzip"):
        if not shutil.which(command):
            raise RuntimeError("Missing command: " + command)
    for path in (PROJECT / ".secrets/terraform-sa-key.json", PROJECT / ".secrets/registry-puller-key.json",
                 PROJECT / "terraform/bootstrap/terraform.tfstate", ssh_key, Path(str(ssh_key) + ".pub")):
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError("Missing required file: " + str(path))
    for path in (PROJECT, application):
        if output("git", "-C", path, "status", "--porcelain"):
            raise RuntimeError("Worktree must be clean: " + str(path))
    cleanup_python = PROJECT / ".secrets/registry-tools/bin/python"
    if not os.access(cleanup_python, os.X_OK):
        raise RuntimeError("Registry cleanup environment is missing")
    run(cleanup_python, PROJECT / "scripts/cleanup-registry.py", "--help", stdout=subprocess.DEVNULL)
    run("sudo", "-v")
    pause_automation()

    parent = Path.home() / "diplom-backups"
    parent.mkdir(mode=0o700, exist_ok=True)
    parent.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = Path(tempfile.mkdtemp(prefix=f"final-{stamp}-", dir=parent))
    print("Backup directory: " + str(backup), flush=True)
    for name, repo in (("infrastructure", PROJECT), ("application", application)):
        run("git", "-C", repo, "bundle", "create", backup / f"{name}.bundle", "--all")
        run("git", "-C", repo, "bundle", "verify", backup / f"{name}.bundle")
    save_command(backup / "infrastructure.tfstate", *tf("state", "pull"))
    save_command(backup / "infrastructure-outputs.json", *tf("output", "-json"))
    outputs = json.loads((backup / "infrastructure-outputs.json").read_text())
    nodes = outputs["nodes"]["value"]
    if set(nodes) != {"cp-1", "worker-1", "worker-2"}:
        raise RuntimeError("Unexpected Terraform nodes")
    check_space(backup, nodes, ssh_key)
    run(PROJECT / "scripts/with-cloud-env.sh", cleanup_python, "scripts/cleanup-registry.py",
        "--registry-id", outputs["registry_id"]["value"], "--folder-id", outputs["folder_id"]["value"])
    save_command(backup / "local-state-and-config.tar.gz", "sudo", "tar",
                 "--exclude=.secrets/registry-tools", "--exclude=.secrets/kube-cache-backup-*",
                 "--exclude=.secrets/maintenance.pause", "--exclude=*.tfplan", "--exclude=*/.terraform",
                 "--numeric-owner", "--acls", "--xattrs", "-czpf", "-",
                 ".secrets", "terraform", "ansible/inventory/diplom")
    verify_tar(backup / "local-state-and-config.tar.gz")
    shutil.copyfile(ssh_key, backup / "ssh-key")
    shutil.copyfile(Path(str(ssh_key) + ".pub"), backup / "ssh-key.pub")
    shutil.copyfile(Path.home() / ".ssh/known_hosts", backup / "known_hosts")
    save_command(backup / "admin.kubeconfig", *kubectl("config", "view", "--raw", "--flatten", "--minify"))
    save_command(backup / "grafana-admin-secret.json", *kubectl("-n", "monitoring", "get", "secret", "grafana-admin", "-o", "json"))
    for release, namespace in (("monitoring", "monitoring"), ("traefik", "ingress-system")):
        save_command(backup / f"{release}-helm-values.json", "helm", "get", "values", release,
                     "--namespace", namespace, "--all", "--output", "json")

    deploy = document(*kubectl("-n", "diplom-app", "get", "deployment", "diplom-app", "-o", "json"))
    write_json(backup / "app-deployment.json", deploy)
    images = [c["image"] for c in deploy["spec"]["template"]["spec"]["containers"] if c["name"] == "nginx"]
    if len(images) != 1 or not re.fullmatch(r"cr\.yandex/[a-z0-9]+/devops-diplom-app@sha256:[0-9a-f]{64}", images[0]):
        raise RuntimeError("Expected exactly one digest-pinned application image")
    image = images[0]
    if image.split("@")[0] != outputs["app_image_repository"]["value"]:
        raise RuntimeError("Deployment registry differs from Terraform")
    (backup / "app-image.txt").write_text(image + "\n")
    with tempfile.TemporaryDirectory(prefix="diplom-archive-") as temporary:
        temporary = Path(temporary)
        key = (PROJECT / ".secrets/registry-puller-key.json").read_bytes()
        auth = base64.b64encode(b"json_key:" + key).decode("ascii")
        authfile = temporary / "auth.json"
        write_json(authfile, {"auths": {"cr.yandex": {"auth": auth}}})
        run("skopeo", "copy", "--all", "--preserve-digests", "--retry-times", "3",
            "--src-authfile", authfile, "docker://" + image, "dir:" + str(backup / "app-image"))
        raw = (backup / "app-image/manifest.json").read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != image.split("@")[1]:
            raise RuntimeError("Archived manifest digest differs from Deployment")
        tag = "devops-diplom-app:archive-" + stamp
        run("skopeo", "copy", "dir:" + str(backup / "app-image"),
            "docker-archive:" + str(temporary / "test.tar") + ":" + tag)
        run("docker", "load", "--input", temporary / "test.tar")
        run(application / "scripts/test-image.sh", tag)
    print("Image preserved by digest; offline archive load and HTTP test passed", flush=True)
    backup_monitoring(backup, nodes, ssh_key)

    save_command(backup / "destroy-plan.log", *tf("plan", "-destroy", "-input=false", "-no-color",
                                                "-out=" + str(backup / "destroy.tfplan")))
    save_command(backup / "destroy-plan.json", *tf("show", "-json", backup / "destroy.tfplan"))
    actions = validate_destroy(json.loads((backup / "destroy-plan.json").read_text()),
                               json.loads((backup / "infrastructure.tfstate").read_text()),
                               outputs["folder_id"]["value"])
    (backup / "destroy-plan-summary.txt").write_text("\n".join(actions) + "\nPlan: 0 create, 0 update, 13 delete.\n")
    print("\n".join(actions), flush=True)
    write_json(backup / "archive-info.json", {
        "created_at": datetime.now(timezone.utc).isoformat(), "folder_id": outputs["folder_id"]["value"],
        "infrastructure_commit": output("git", "rev-parse", "HEAD"),
        "application_commit": output("git", "-C", application, "rev-parse", "HEAD"), "image": image,
        "terraform_version": document("terraform", "version", "-json")["terraform_version"],
    })
    sums = []
    for path in sorted(backup.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            sums.append(f"{digest}  {path.relative_to(backup)}")
    (backup / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    run("sha256sum", "--check", "SHA256SUMS", cwd=backup)
    (PROJECT / ".secrets/decommission-backup-path").write_text(str(backup) + "\n")
    print("\nVerified archive: " + str(backup))
    print("Destroy plan: 13 resources; apply has NOT been run.")
    print("Monitoring restored. Automation and the dedicated runner remain disabled.")


if __name__ == "__main__":
    main()
