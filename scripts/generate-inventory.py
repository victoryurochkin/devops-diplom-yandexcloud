#!/usr/bin/env python3
import json
import pathlib
import sys

nodes = json.load(sys.stdin)
expected = {"cp-1", "worker-1", "worker-2"}
if set(nodes) != expected:
    raise SystemExit(f"Unexpected node names: {sorted(nodes)}")

hosts = {}
for name, node in nodes.items():
    if not node["public_ip"] or not node["private_ip"]:
        raise SystemExit(f"Missing address for {name}")
    hosts[name] = {
        "ansible_host": node["public_ip"],
        "ip": node["private_ip"],
        "access_ip": node["private_ip"],
    }

inventory = {
    "all": {
        "hosts": hosts,
        "vars": {
            "ansible_user": "ubuntu",
            "ansible_become": True,
            "ansible_python_interpreter": "/usr/bin/python3",
            "container_manager": "containerd",
            "kube_network_plugin": "calico",
            "calico_network_backend": "vxlan",
            "calico_ipip_mode": "Never",
            "calico_vxlan_mode": "Always",
            "kube_service_addresses": "10.233.0.0/18",
            "kube_pods_subnet": "10.233.64.0/18",
            "supplementary_addresses_in_ssl_keys": [
                nodes["cp-1"]["public_ip"]
            ],
            "kubeconfig_localhost": True,
            "kubeconfig_localhost_ansible_host": True,
            "kubectl_localhost": True,
        },
        "children": {
            "kube_control_plane": {"hosts": {"cp-1": {}}},
            "etcd": {"hosts": {"cp-1": {}}},
            "kube_node": {
                "hosts": {"worker-1": {}, "worker-2": {}}
            },
            "k8s_cluster": {
                "children": {
                    "kube_control_plane": {},
                    "kube_node": {},
                }
            },
            "calico_rr": {"hosts": {}},
        },
    }
}

path = pathlib.Path("ansible/inventory/diplom/hosts.yml")
path.parent.mkdir(parents=True, exist_ok=True)
# JSON is valid YAML; no additional Python packages are needed.
path.write_text(json.dumps(inventory, indent=2) + "\n")
print(f"Created {path}")
for name, node in nodes.items():
    print(f"{name}: SSH={node['public_ip']}, internal={node['private_ip']}")
