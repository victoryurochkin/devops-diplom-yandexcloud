import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


maintenance = load("maintenance", "maintain-stand.py")
tokens = load("tokens", "generate-deployer-kubeconfig.py")


class WorkerTests(unittest.TestCase):
    def setUp(self):
        from yandex.cloud.compute.v1.instance_pb2 import Instance
        from yandex.cloud.vpc.v1.address_pb2 import Address
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        (self.project / ".secrets").mkdir()
        nodes = {name: {"id": name, "public_ip": ip} for name, ip in (
            ("cp-1", "192.0.2.1"), ("worker-1", "192.0.2.2"), ("worker-2", "192.0.2.3"),
        )}
        (self.project / ".secrets/maintenance-outputs.json").write_text(json.dumps({
            "folder_id": {"value": "test-folder"}, "nodes": {"value": nodes},
        }))
        self.instances = [Instance(
            id=name, name="diplom-" + name, folder_id="test-folder",
            status=status,
            labels={"project": "devops-diplom", "managed_by": "terraform", "role": "worker"},
            scheduling_policy={"preemptible": True},
        ) for name, status in (("worker-1", Instance.RUNNING), ("worker-2", Instance.STOPPED))]
        self.api = Mock()
        self.api.Get.side_effect = self.instances
        self.addresses = Mock()
        self.addresses.List.return_value = Mock(addresses=[Address(
            reserved=True, external_ipv4_address={"address": ip},
        ) for ip in ("192.0.2.2", "192.0.2.3")], next_page_token="")
        sdk = Mock()
        sdk.client.side_effect = [self.api, self.addresses]
        for target, value in (("PROJECT", self.project), ("PAUSE", self.project / ".secrets/maintenance.pause")):
            patcher = patch.object(maintenance, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(maintenance, "client", return_value=sdk)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_starts_only_stopped_worker(self):
        with patch.object(maintenance, "wait_operation"):
            maintenance.workers(True)
        self.api.Start.assert_called_once()
        self.assertEqual(self.api.Start.call_args.args[0].instance_id, "worker-2")

    def test_read_only_does_not_start_anything(self):
        maintenance.workers(False)
        self.api.Start.assert_not_called()

    def test_identity_mismatch_prevents_all_changes(self):
        self.instances[1].labels["project"] = "unrelated"
        with self.assertRaises(RuntimeError):
            maintenance.workers(True)
        self.api.Start.assert_not_called()

    def test_pause_prevents_start(self):
        maintenance.PAUSE.touch()
        maintenance.workers(True)
        self.api.Start.assert_not_called()

    def test_dynamic_ip_prevents_start(self):
        self.addresses.List.return_value.addresses[1].reserved = False
        with self.assertRaises(RuntimeError):
            maintenance.workers(True)
        self.api.Start.assert_not_called()


class TokenTests(unittest.TestCase):
    def test_token_is_private_and_never_printed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "config"
            expiration = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            values = [
                {"server": "https://192.0.2.1:6443", "certificate-authority-data": "dGVzdA=="},
                {"status": {"token": "private-test-token", "expirationTimestamp": expiration}},
            ]
            printed = io.StringIO()
            with patch.object(tokens, "kubectl_json", side_effect=values), \
                    patch.object(sys, "argv", ["generate", "--output", str(output)]), \
                    contextlib.redirect_stdout(printed):
                tokens.main()
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertNotIn("private-test-token", printed.getvalue())
            self.assertEqual(json.loads(output.read_text())["users"][0]["user"]["token"], "private-test-token")

    def test_short_token_does_not_overwrite_existing_config(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "config"
            output.write_text("existing")
            expiration = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
            values = [
                {"server": "https://192.0.2.1:6443", "certificate-authority-data": "dGVzdA=="},
                {"status": {"token": "private-test-token", "expirationTimestamp": expiration}},
            ]
            with patch.object(tokens, "kubectl_json", side_effect=values), \
                    patch.object(sys, "argv", ["generate", "--output", str(output)]), \
                    self.assertRaises(SystemExit):
                tokens.main()
            self.assertEqual(output.read_text(), "existing")


if __name__ == "__main__":
    unittest.main()
