#!/usr/bin/env python3
"""Archive bucket versions and retire the known bootstrap; --delete opts in."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tarfile
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
STATE_KEY = "infrastructure/terraform.tfstate"
ROLES = ("compute.editor", "vpc.publicAdmin", "vpc.securityGroups.admin",
         "vpc.privateAdmin", "container-registry.editor", "storage.editor")
ACCOUNTS = {"terraform": "diplom-terraform", "registry_puller": "diplom-registry-puller",
            "registry_pusher": "diplom-registry-pusher"}
EXPECTED = {"yandex_storage_bucket.state", "yandex_iam_service_account_static_access_key.state"}
EXPECTED.update("yandex_iam_service_account." + name for name in ACCOUNTS)
EXPECTED.update(f'yandex_resourcemanager_folder_iam_member.terraform["{role}"]' for role in ROLES)
EXPECTED.update("yandex_resourcemanager_folder_iam_member." + name
                for name in ("registry_puller", "registry_pusher"))


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def output(*args, **kwargs):
    return run(*args, stdout=subprocess.PIPE, text=True, **kwargs).stdout.strip()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def state_resources(state):
    found = {}
    for resource in state.get("resources", []):
        if resource.get("mode") != "managed":
            continue
        for instance in resource.get("instances", []):
            address = resource["type"] + "." + resource["name"]
            if resource.get("module"):
                address = resource["module"] + "." + address
            if "index_key" in instance:
                address += "[" + json.dumps(instance["index_key"]) + "]"
            if address in found or instance.get("deposed"):
                raise RuntimeError("Unexpected duplicate/deposed resource")
            found[address] = instance["attributes"]
    return found


def validate_resources(resources, folder):
    if set(resources) != EXPECTED:
        raise RuntimeError("Expected exactly 13 known bootstrap resources; review partial deletion separately")
    for address, attrs in resources.items():
        if address == "yandex_iam_service_account_static_access_key.state":
            if attrs["service_account_id"] != resources["yandex_iam_service_account.terraform"]["id"]:
                raise RuntimeError("S3 key belongs to another service account")
        elif attrs.get("folder_id") != folder:
            raise RuntimeError("Bootstrap contains a resource from another folder")
    for name, expected_name in ACCOUNTS.items():
        if resources["yandex_iam_service_account." + name]["name"] != expected_name:
            raise RuntimeError("Unexpected service account name")
    for name, roles in (("terraform", ROLES), ("registry_puller", ("container-registry.images.puller",)),
                        ("registry_pusher", ("container-registry.images.pusher",))):
        for role in roles:
            address = "yandex_resourcemanager_folder_iam_member." + name
            if name == "terraform":
                address += "[" + json.dumps(role) + "]"
            attrs = resources[address]
            member = "serviceAccount:" + resources["yandex_iam_service_account." + name]["id"]
            if attrs["role"] != role or attrs["member"] != member:
                raise RuntimeError("Unexpected IAM binding")
    if resources["yandex_storage_bucket.state"]["bucket"] != "diplom-tfstate-" + folder:
        raise RuntimeError("Unexpected state bucket name")


def validate_plan(plan, baseline, folder):
    changes = [r for r in plan.get("resource_changes", []) if r.get("mode") == "managed"]
    if len(changes) != 13 or {r["address"] for r in changes} != EXPECTED:
        raise RuntimeError("Destroy plan does not contain exactly the known bootstrap")
    if any(r["change"]["actions"] != ["delete"] for r in changes):
        raise RuntimeError("Non-delete action in bootstrap plan")
    before = {r["address"]: r["change"]["before"] for r in changes}
    validate_resources(before, folder)
    if any(before[name]["id"] != baseline[name]["id"] for name in EXPECTED):
        raise RuntimeError("Resource IDs differ from the verified archive")
    return changes


def versions(s3, bucket):
    found = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        for kind in ("Versions", "DeleteMarkers"):
            for item in page.get(kind, []):
                if item["Key"] not in (STATE_KEY, STATE_KEY + ".tflock"):
                    raise RuntimeError("Bucket contains an unexpected object; nothing else will be deleted")
                found.append({"Key": item["Key"], "VersionId": item["VersionId"],
                              "kind": kind, "size": item.get("Size", 0)})
    return sorted(found, key=lambda i: (i["Key"], i["VersionId"], i["kind"]))


def ensure_idle_bucket(s3, bucket):
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        if any(item["Key"] != STATE_KEY for item in page.get("Contents", [])):
            raise RuntimeError("Unexpected current object or active state lock in bucket")
    if s3.list_multipart_uploads(Bucket=bucket, MaxUploads=1).get("Uploads"):
        raise RuntimeError("Unexpected unfinished multipart upload; review separately")


def purge_versions(s3, bucket, saved):
    ensure_idle_bucket(s3, bucket)
    if versions(s3, bucket) != saved:
        raise RuntimeError("Bucket changed since backup; deletion cancelled")
    # Explicit version IDs remove both versions and delete markers permanently.
    for i, item in enumerate(saved, 1):
        s3.delete_object(Bucket=bucket, Key=item["Key"], VersionId=item["VersionId"])
        print(f"Removed bucket entry {i}/{len(saved)}", flush=True)
    if versions(s3, bucket):
        raise RuntimeError("Bucket is not empty; Terraform apply not started")
    ensure_idle_bucket(s3, bucket)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    os.chdir(PROJECT)
    os.environ.setdefault("TF_CLI_CONFIG_FILE", str(PROJECT / ".secrets/terraformrc"))
    os.environ["TF_IN_AUTOMATION"] = "true"
    archive = runpy.run_path(str(PROJECT / "scripts/archive-stand.py"))
    backup = Path((PROJECT / ".secrets/decommission-backup-path").read_text().strip()).resolve()
    run("sha256sum", "--check", "SHA256SUMS", cwd=backup)
    info = json.loads((backup / "archive-info.json").read_text())
    if output("git", "status", "--porcelain"):
        raise RuntimeError("Worktree must be clean")
    if not (PROJECT / ".secrets/maintenance.pause").is_file():
        raise RuntimeError("Maintenance pause flag is missing")
    for unit in ("diplom-maintenance.timer", archive["RUNNER"]):
        if (output("systemctl", "show", unit, "--property=ActiveState", "--value") != "inactive"
                or output("systemctl", "show", unit, "--property=UnitFileState", "--value") != "disabled"):
            raise RuntimeError("Automation is not disabled: " + unit)
    if output("systemctl", "show", "diplom-maintenance.service", "--property=ActiveState", "--value") not in ("inactive", "failed"):
        raise RuntimeError("Maintenance is still running")
    for repo, workflow in zip(archive["REPOS"], ("terraform.yml", "app.yml")):
        if output("gh", "api", f"repos/{repo}/actions/workflows/{workflow}", "--jq", ".state") != "disabled_manually":
            raise RuntimeError("Cloud workflow is not disabled")
    archive["wait_until"](archive["no_actions"], 600, "Actions are still running")
    latest_main = json.loads(output(*archive["tf"]("state", "pull")))
    previous_main = json.loads((backup / "infrastructure.tfstate").read_text())
    if not latest_main.get("lineage") or latest_main["lineage"] != previous_main["lineage"]:
        raise RuntimeError("Main state lineage differs from the verified archive")
    if state_resources(latest_main):
        raise RuntimeError("Main infrastructure state is not empty")

    source = PROJECT / "terraform/bootstrap"
    if (source / ".terraform.tfstate.lock.info").exists():
        raise RuntimeError("Another bootstrap operation holds the local state lock")
    original = (source / "terraform.tfstate").read_bytes()
    current = state_resources(json.loads(original))
    with tarfile.open(backup / "local-state-and-config.tar.gz", "r:gz") as tar:
        baseline = state_resources(json.load(tar.extractfile("terraform/bootstrap/terraform.tfstate")))
    validate_resources(current, info["folder_id"])
    validate_resources(baseline, info["folder_id"])
    if any(current[name]["id"] != baseline[name]["id"] for name in EXPECTED):
        raise RuntimeError("Bootstrap IDs differ from the archive")

    work = Path(tempfile.mkdtemp(prefix="bootstrap-retirement-", dir=backup))
    print("Bootstrap retirement directory: " + str(work), flush=True)
    (PROJECT / ".secrets/bootstrap-retirement-path").write_text(str(work) + "\n")
    write_json(work / "main-empty.tfstate", latest_main)
    (work / "bootstrap-before.tfstate").write_bytes(original)
    copy = work / "configuration"
    copy.mkdir(mode=0o700)
    for path in source.iterdir():
        if path.is_file() and (path.suffix in (".tf", ".tfvars") or path.name.endswith(".tfvars.json")
                               or path.name == ".terraform.lock.hcl"):
            shutil.copyfile(path, copy / path.name)
    (copy / "terraform.tfstate").write_bytes(original)
    config = copy / "main.tf"
    text = config.read_text()
    if text.count("prevent_destroy = true") != 1:
        raise RuntimeError("Unexpected bucket protection configuration")
    config.write_text(text.replace("prevent_destroy = true", "prevent_destroy = false", 1))

    env = {k: v for k, v in os.environ.items() if not k.startswith(("TF_CLI_ARGS", "TF_VAR_", "AWS_"))
           and k not in ("YC_SERVICE_ACCOUNT_KEY_FILE", "YC_TOKEN", "TF_DATA_DIR")}
    env["YC_TOKEN"] = output("yc", "iam", "create-token", env=env)
    if not env["YC_TOKEN"]:
        raise RuntimeError("User IAM token is empty")
    env["TF_INPUT"] = "false"
    terraform = ["terraform", "-chdir=" + str(copy)]
    run(*terraform, "init", "-input=false", "-lockfile=readonly", env=env)
    with (work / "plan.log").open("w") as log:
        run(*terraform, "plan", "-destroy", "-input=false", "-no-color", "-lock-timeout=60s",
            "-out=" + str(work / "destroy.tfplan"), env=env, stdout=log)
    plan = json.loads(output(*terraform, "show", "-json", work / "destroy.tfplan", env=env))
    write_json(work / "plan.json", plan)
    changes = validate_plan(plan, baseline, info["folder_id"])
    for item in changes:
        print("delete: " + item["address"], flush=True)

    # Credentials are read into memory and never printed or put into command arguments.
    outputs = json.loads(output("terraform", "-chdir=" + str(source), "output", "-json", env=env))
    bucket = current["yandex_storage_bucket.state"]["bucket"]
    if outputs["state_bucket_name"]["value"] != bucket:
        raise RuntimeError("Bucket output differs from state")
    import boto3
    from botocore.config import Config
    session = boto3.Session(aws_access_key_id=outputs["state_access_key"]["value"],
                            aws_secret_access_key=outputs["state_secret_key"]["value"],
                            region_name="ru-central1")
    s3 = session.client("s3", endpoint_url="https://storage.yandexcloud.net",
                        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                      connect_timeout=15, read_timeout=60,
                                      retries={"mode": "standard", "max_attempts": 4},
                                      request_checksum_calculation="when_required",
                                      response_checksum_validation="when_required"))
    ensure_idle_bucket(s3, bucket)
    saved = versions(s3, bucket)
    version_dir = work / "bucket-versions"
    version_dir.mkdir(mode=0o700)
    if sum(i["size"] for i in saved) + 1024**3 > shutil.disk_usage(work).free:
        raise RuntimeError("Insufficient space to archive bucket versions")
    index = []
    for i, item in enumerate(saved):
        entry = dict(item)
        if item["kind"] == "Versions":
            response = s3.get_object(Bucket=bucket, Key=item["Key"], VersionId=item["VersionId"])
            name = f"{i:06d}.bin"
            with response["Body"] as body, (version_dir / name).open("wb") as target:
                shutil.copyfileobj(body, target)
            if (version_dir / name).stat().st_size != item["size"]:
                raise RuntimeError("Object version size mismatch")
            entry["file"] = name
        index.append(entry)
    write_json(version_dir / "index.json", index)
    sums = []
    for path in (work / "bootstrap-before.tfstate", work / "main-empty.tfstate", work / "plan.json",
                 work / "destroy.tfplan", *sorted(version_dir.iterdir())):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        sums.append(f"{digest}  {path.relative_to(work)}")
    (work / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    run("sha256sum", "--check", "SHA256SUMS", cwd=work)
    print(f"Verified: 13 bootstrap resources; {len(saved)} bucket versions/delete markers archived.", flush=True)
    if not args.delete:
        print("Read-only run complete. Nothing deleted. Use --delete to repeat checks and retire bootstrap.")
        return
    if (source / "terraform.tfstate").read_bytes() != original:
        raise RuntimeError("Bootstrap state changed during preparation")
    if not archive["no_actions"]():
        raise RuntimeError("Actions started during preparation")
    purge_versions(s3, bucket, saved)
    print("Bucket is empty. Applying the verified bootstrap destroy plan.", flush=True)
    try:
        with (work / "apply.log").open("w") as log:
            command = [*terraform, "apply", "-input=false", "-no-color", str(work / "destroy.tfplan")]
            with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True) as process:
                for line in process.stdout:
                    print(line, end="", flush=True)
                    log.write(line)
                    log.flush()
                if process.wait():
                    raise RuntimeError("Bootstrap apply failed; inspect the private retirement directory")
    finally:
        # Preserve even partial Terraform progress, without silently overwriting a concurrent local change.
        if any((directory / ".terraform.tfstate.lock.info").exists() for directory in (source, copy)):
            raise RuntimeError("Bootstrap state is still locked; use the retirement directory to reconcile progress")
        updated = (copy / "terraform.tfstate").read_bytes()
        json.loads(updated)
        if (source / "terraform.tfstate").read_bytes() != original:
            raise RuntimeError("Original bootstrap state changed; reconcile with retirement directory manually")
        staging = source / "terraform.tfstate.retiring"
        staging.write_bytes(updated)
        os.replace(staging, source / "terraform.tfstate")
    if state_resources(json.loads(updated)):
        raise RuntimeError("Bootstrap state is not empty")
    (work / "COMPLETED.txt").write_text(datetime.now(timezone.utc).isoformat() + "\n")
    print("Bootstrap state is empty. Bucket, three service accounts, IAM bindings and S3 key removed.")
    print("Backups retained: " + str(backup))
    print("Automation remains disabled. Cloud inventory and GitHub credential cleanup are still required.")


if __name__ == "__main__":
    main()
