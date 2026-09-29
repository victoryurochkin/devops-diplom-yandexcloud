import copy
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "archive_stand", Path(__file__).resolve().parents[1] / "scripts/archive-stand.py"
)
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class DestroyPlanTests(unittest.TestCase):
    def setUp(self):
        addresses = ["yandex_vpc_network.diplom", "yandex_container_registry.diplom",
                     "yandex_vpc_security_group.cluster", "yandex_vpc_security_group.web"]
        addresses += [f'yandex_vpc_subnet.diplom["{z}"]' for z in ("a", "b", "d")]
        for name in ("cp-1", "worker-1", "worker-2"):
            addresses += [f'yandex_compute_instance.node["{name}"]',
                          f'yandex_vpc_address.node["{name}"]']
        self.plan = {"resource_changes": [
            {"address": address, "mode": "managed", "change": {
                "actions": ["delete"], "before": {"id": str(i), "folder_id": "diplom"}
            }} for i, address in enumerate(addresses)
        ]}
        self.state = {"resources": [{"mode": "managed", "instances": [
            {"attributes": copy.deepcopy(r["change"]["before"])}
        ]} for r in self.plan["resource_changes"]]}

    def check(self):
        return archive.validate_destroy(self.plan, self.state, "diplom")

    def test_expected_plan_accepted(self):
        self.assertEqual(len(self.check()), 13)

    def test_missing_resource_rejected(self):
        self.plan["resource_changes"].pop()
        with self.assertRaises(RuntimeError):
            self.check()

    def test_bootstrap_resource_rejected(self):
        self.plan["resource_changes"][0]["address"] = "yandex_storage_bucket.state"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_replacement_rejected(self):
        self.plan["resource_changes"][0]["change"]["actions"] = ["delete", "create"]
        with self.assertRaises(RuntimeError):
            self.check()

    def test_wrong_resource_id_rejected(self):
        self.plan["resource_changes"][0]["change"]["before"]["id"] = "unrelated"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_wrong_folder_rejected(self):
        self.plan["resource_changes"][0]["change"]["before"]["folder_id"] = "unrelated"
        with self.assertRaises(RuntimeError):
            self.check()


if __name__ == "__main__":
    unittest.main()
