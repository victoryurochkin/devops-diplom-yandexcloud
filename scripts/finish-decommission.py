#!/usr/bin/env python3
"""Audit the retired folder; --cleanup-github removes only known diploma CI access."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

PROJECT = Path(__file__).resolve().parent.parent
INFRA = "victoryurochkin/devops-diplom-yandexcloud"
APP = "victoryurochkin/devops-diplom-app"
RUNNER_NAME = "diplom-app-deploy-it"
RUNNER_UNIT = "actions.runner.victoryurochkin-devops-diplom-app." + RUNNER_NAME + ".service"
KNOWN = {
    INFRA: {
        "secrets": {"YC_TERRAFORM_KEY", "TF_STATE_ACCESS_KEY_ID", "TF_STATE_SECRET_ACCESS_KEY",
                    "TF_VARS", "TF_COMPUTE_VARS", "TF_SSH_PUBLIC_KEY"},
        "variables": set(),
    },
    APP: {"secrets": {"YC_REGISTRY_PUSHER_KEY"},
          "variables": {"IMAGE_REPOSITORY", "APP_WORKER_IPS"}},
}
CLOUD_TYPES = (
    "compute instance", "compute disk", "compute snapshot", "compute image",
    "vpc address", "vpc network", "vpc subnet", "vpc security-group",
    "vpc gateway", "vpc route-table", "container registry",
    "storage bucket", "iam service-account",
)


def output(*args, env=None):
    return subprocess.check_output(args, text=True, env=env, timeout=180).strip()


def empty_state(path):
    state = json.loads(path.read_text())
    if "resources" not in state or any(
        r.get("mode") == "managed" and r.get("instances") for r in state["resources"]
    ):
        raise RuntimeError("Expected an empty Terraform state: " + str(path))


def github_names(repo, kind):
    return set(output("gh", "api", "--paginate",
                      f"repos/{repo}/actions/{kind}?per_page=100",
                      "--jq", f".{kind}[].name").splitlines())


def github_snapshot():
    result = {}
    for repo in KNOWN:
        result[repo] = {kind: sorted(github_names(repo, kind)) for kind in KNOWN[repo]}
    rows = output("gh", "api", "--paginate", f"repos/{APP}/actions/runners?per_page=100",
                  "--jq", ".runners[] | @json")
    result[APP]["runners"] = [json.loads(row) for row in rows.splitlines()]
    return result


def cleanup_targets(snapshot):
    targets = []
    for repo, kinds in KNOWN.items():
        for kind, names in kinds.items():
            for name in sorted(names.intersection(snapshot[repo][kind])):
                targets.append(f"repos/{repo}/actions/{kind}/{name}")
    runners = [r for r in snapshot[APP]["runners"] if r["name"] == RUNNER_NAME]
    if len(runners) > 1:
        raise RuntimeError("Duplicate diploma runner names; review before removal")
    for runner in runners:
        if runner.get("status") != "offline" or runner.get("busy") is not False:
            raise RuntimeError("Diploma runner must be offline and idle")
        if "diplom-deploy" not in {label["name"] for label in runner.get("labels", [])}:
            raise RuntimeError("Unexpected diploma runner labels")
        if type(runner.get("id")) is not int or runner["id"] <= 0:
            raise RuntimeError("Unexpected runner ID")
        targets.append(f"repos/{APP}/actions/runners/{runner['id']}")
    return targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup-github", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    backup = Path((PROJECT / ".secrets/decommission-backup-path").read_text().strip()).resolve()
    retired = Path((PROJECT / ".secrets/bootstrap-retirement-path").read_text().strip()).resolve()
    if not retired.is_relative_to(backup) or not (retired / "COMPLETED.txt").is_file():
        raise RuntimeError("Verified bootstrap retirement is required")
    empty_state(PROJECT / "terraform/bootstrap/terraform.tfstate")
    empty_state(retired / "main-empty.tfstate")
    info = json.loads((backup / "archive-info.json").read_text())
    folder = info["folder_id"]
    if not re.fullmatch(r"[a-z0-9]{20}", folder):
        raise RuntimeError("Invalid archived folder ID")
    if not (PROJECT / ".secrets/maintenance.pause").is_file():
        raise RuntimeError("Maintenance pause flag is missing")
    for unit in ("diplom-maintenance.timer", RUNNER_UNIT):
        for prop, expected in (("ActiveState", "inactive"), ("UnitFileState", "disabled")):
            if output("systemctl", "show", unit, "--property=" + prop, "--value") != expected:
                raise RuntimeError("Automation is not stopped/disabled: " + unit)
    if output("systemctl", "show", "diplom-maintenance.service", "--property=ActiveState", "--value") not in ("inactive", "failed"):
        raise RuntimeError("Maintenance is running")
    for repo, workflow in ((INFRA, "terraform.yml"), (APP, "app.yml")):
        state = output("gh", "api", f"repos/{repo}/actions/workflows/{workflow}", "--jq", ".state")
        if state != "disabled_manually":
            raise RuntimeError("Cloud workflow must remain disabled: " + repo)
        print(f"{repo}: {state}", flush=True)

    env = dict(os.environ)
    for name in ("YC_TOKEN", "YC_SERVICE_ACCOUNT_KEY_FILE"):
        env.pop(name, None)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "folder_id": folder, "cloud": {}}
    print("Cloud inventory (read-only), folder: " + folder, flush=True)
    for kind in CLOUD_TYPES:
        rows = json.loads(output("yc", *kind.split(), "list", "--folder-id", folder,
                                 "--format=json", env=env))
        if not isinstance(rows, list):
            raise RuntimeError("Unexpected inventory response: " + kind)
        summary = [{"id": row.get("id"), "name": row.get("name")} for row in rows]
        report["cloud"][kind] = summary
        print(f"{kind}: {len(rows)}", flush=True)
        for row in summary:
            print("  " + json.dumps(row, ensure_ascii=False), flush=True)

    before = github_snapshot()
    targets = cleanup_targets(before)
    report["github_before"] = before
    report["cleanup_requested"] = args.cleanup_github
    for endpoint in targets:
        if args.cleanup_github:
            subprocess.run(["gh", "api", "--method", "DELETE", endpoint], check=True, timeout=60)
        print(("Removed: " if args.cleanup_github else "Would remove: ") + endpoint, flush=True)
    after = github_snapshot() if args.cleanup_github else before
    report["github_after"] = after
    remaining_targets = cleanup_targets(after)
    if args.cleanup_github and remaining_targets:
        raise RuntimeError("Some known CI credentials remain; rerun to reconcile")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = backup / ("closure-check-" + stamp + ".json")
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print("Report: " + str(path), flush=True)
    for repo, values in after.items():
        for kind in ("secrets", "variables"):
            print(f"{repo} remaining {kind}: {', '.join(values[kind]) or 'none'}", flush=True)
    if any(report["cloud"].values()):
        raise SystemExit("Some cloud resources remain in the folder; review their ownership. Nothing in the cloud was deleted.")
    print("Checked cloud resource lists are empty. Automation remains disabled.")
    if remaining_targets:
        print("Read-only run; use --cleanup-github to remove the listed CI access.")
    else:
        print("Known diploma GitHub secrets, variables and runner registration are absent.")


if __name__ == "__main__":
    main()
