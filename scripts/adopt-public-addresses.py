#!/usr/bin/env python3
"""Reserve and import existing VM IPs without replacing network interfaces."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import grpc
from google.protobuf.field_mask_pb2 import FieldMask
from yandex.cloud.compute.v1.instance_service_pb2 import GetInstanceRequest
from yandex.cloud.compute.v1.instance_service_pb2_grpc import InstanceServiceStub
from yandex.cloud.vpc.v1.address_service_pb2 import (
    ListAddressesRequest, UpdateAddressRequest,
)
from yandex.cloud.vpc.v1.address_service_pb2_grpc import AddressServiceStub

from cloud_runtime import client, wait_operation, write_json


def tf(*args):
    return subprocess.check_output(
        ["terraform", "-chdir=terraform/infrastructure", *args], text=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--adopt", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    project = Path(__file__).resolve().parent.parent
    os.chdir(project)
    nodes = json.loads(tf("output", "-json", "nodes"))
    if set(nodes) != {"cp-1", "worker-1", "worker-2"}:
        raise RuntimeError("Expected exactly three diploma nodes")

    sdk = client()
    instances = sdk.client(InstanceServiceStub)
    addresses = sdk.client(AddressServiceStub)
    all_addresses = []
    token = ""
    seen = set()
    while True:
        page = addresses.List(ListAddressesRequest(
            folder_id=args.folder_id, page_token=token, page_size=1000,
        ), timeout=30)
        all_addresses.extend(page.addresses)
        token = page.next_page_token
        if not token:
            break
        if token in seen:
            raise RuntimeError("Repeated address pagination token")
        seen.add(token)

    state = json.loads(tf("show", "-json"))
    tracked = {
        item["address"]: item["values"]["id"]
        for item in state.get("values", {}).get("root_module", {}).get("resources", [])
        if item.get("mode") == "managed" and item["type"] == "yandex_vpc_address"
    }
    candidates = []
    for name, node in sorted(nodes.items()):
        vm = instances.Get(GetInstanceRequest(instance_id=node["id"]), timeout=30)
        public_ips = [
            nic.primary_v4_address.one_to_one_nat.address
            for nic in vm.network_interfaces
        ]
        if (vm.folder_id != args.folder_id or vm.name != "diplom-" + name
                or vm.labels.get("project") != "devops-diplom"
                or public_ips != [node["public_ip"]]):
            raise RuntimeError("VM identity or current IP differs from state: " + name)
        matches = [
            ip for ip in all_addresses
            if ip.external_ipv4_address.address == node["public_ip"]
            and ip.external_ipv4_address.zone_id == node["zone"] and ip.used
        ]
        if len(matches) != 1:
            raise RuntimeError("Expected one attached public address: " + name)
        address = matches[0]
        resource = 'yandex_vpc_address.node["' + name + '"]'
        if resource in tracked and tracked[resource] != address.id:
            raise RuntimeError("Terraform already tracks another address: " + resource)
        candidates.append((resource, address))
        print(f"{name}: {node['public_ip']} / {address.id}; reserved={address.reserved}")

    if not args.adopt:
        print("Read-only check complete. Use --adopt to reserve and import these IPs.")
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = project / ".secrets" / ("state-before-ip-adoption-" + stamp + ".json")
    write_json(backup, json.loads(tf("state", "pull")))
    for resource, address in candidates:
        if not address.reserved:
            try:
                operation = addresses.Update(UpdateAddressRequest(
                    address_id=address.id, reserved=True,
                    update_mask=FieldMask(paths=["reserved"]),
                ), timeout=30)
            except grpc.RpcError as error:
                if (error.code() == grpc.StatusCode.RESOURCE_EXHAUSTED
                        and "vpc.externalStaticAddresses.count" in (error.details() or "")):
                    raise SystemExit(
                        "Static public IP quota exhausted for " + resource + ". "
                        "Increase vpc.externalStaticAddresses.count in the cloud quotas. "
                        "Completed reservations and imports are preserved. "
                        "Rerun --adopt after the quota increase; completed imports are skipped."
                    ) from None
                raise
            wait_operation(sdk, operation)
        if resource not in tracked:
            subprocess.run([
                "terraform", "-chdir=terraform/infrastructure", "import",
                "-input=false", "-lock-timeout=5m", resource, address.id,
            ], check=True)
    print("Existing addresses reserved/imported. Review terraform plan before apply.")


if __name__ == "__main__":
    main()
