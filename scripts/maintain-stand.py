#!/usr/bin/env python3
"""Restart stopped diploma workers and renew the restricted CD credential."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from yandex.cloud.compute.v1.instance_pb2 import Instance
from yandex.cloud.compute.v1.instance_service_pb2 import GetInstanceRequest, StartInstanceRequest
from yandex.cloud.compute.v1.instance_service_pb2_grpc import InstanceServiceStub
from yandex.cloud.vpc.v1.address_service_pb2 import ListAddressesRequest
from yandex.cloud.vpc.v1.address_service_pb2_grpc import AddressServiceStub

from cloud_runtime import client, wait_operation

PROJECT = Path(__file__).resolve().parent.parent
PAUSE = PROJECT / ".secrets/maintenance.pause"


def workers(apply):
    outputs = json.loads((PROJECT / ".secrets/maintenance-outputs.json").read_text())
    folder = outputs["folder_id"]["value"]
    nodes = outputs["nodes"]["value"]
    if set(nodes) != {"cp-1", "worker-1", "worker-2"}:
        raise RuntimeError("Unexpected node names in maintenance configuration")
    sdk = client()
    api = sdk.client(InstanceServiceStub)
    address_api = sdk.client(AddressServiceStub)
    reserved = set()
    token = ""
    seen = set()
    while True:
        page = address_api.List(ListAddressesRequest(
            folder_id=folder, page_size=1000, page_token=token,
        ), timeout=30)
        reserved.update(a.external_ipv4_address.address for a in page.addresses if a.reserved)
        token = page.next_page_token
        if not token:
            break
        if token in seen:
            raise RuntimeError("Repeated address pagination token")
        seen.add(token)
    candidates = []
    for name in ("worker-1", "worker-2"):
        node = nodes[name]
        vm = api.Get(GetInstanceRequest(instance_id=node["id"]), timeout=30)
        if (vm.folder_id != folder or vm.name != "diplom-" + name
                or vm.labels.get("project") != "devops-diplom"
                or vm.labels.get("managed_by") != "terraform"
                or vm.labels.get("role") != "worker"
                or not vm.scheduling_policy.preemptible
                or node["public_ip"] not in reserved):
            raise RuntimeError("Worker identity or reserved IP check failed: " + name)
        candidates.append((name, vm))
        print(name + ": " + Instance.Status.Name(vm.status), flush=True)
    failures = []
    for name, vm in candidates:
        if PAUSE.exists():
            return
        if vm.status == Instance.STOPPED and apply:
            try:
                operation = api.Start(StartInstanceRequest(instance_id=vm.id), timeout=30)
                wait_operation(sdk, operation)
                print(name + ": start completed", flush=True)
            except Exception as error:
                failures.append(name + ": " + str(error))
    if failures:
        raise RuntimeError("; ".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    os.chdir(PROJECT)
    if PAUSE.exists():
        print("Stand maintenance paused")
        return
    failures = []
    try:
        workers(args.apply)
    except Exception as error:
        failures.append("Workers: " + str(error))
    # Renewal remains available when the cloud API is temporarily unavailable.
    if args.apply and not PAUSE.exists():
        result = subprocess.run(["bash", str(PROJECT / "scripts/refresh-deployer-access.sh")])
        if result.returncode:
            failures.append("Deployer token renewal failed")
    if failures:
        raise SystemExit("\n".join(failures))
    if not args.apply:
        print("Read-only check complete; neither VMs nor credentials changed")


if __name__ == "__main__":
    main()
