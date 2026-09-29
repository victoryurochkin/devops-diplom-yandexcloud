import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location(
    "retire", Path(__file__).resolve().parents[1] / "scripts/retire-bootstrap.py"
)
retire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retire)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.resources = {name: {"id": name, "folder_id": "folder"} for name in retire.EXPECTED}
        for name, label in retire.ACCOUNTS.items():
            self.resources["yandex_iam_service_account." + name]["name"] = label
        self.resources["yandex_iam_service_account_static_access_key.state"]["service_account_id"] = "yandex_iam_service_account.terraform"
        self.resources["yandex_storage_bucket.state"]["bucket"] = "diplom-tfstate-folder"
        for name, roles in (("terraform", retire.ROLES), ("registry_puller", ("container-registry.images.puller",)),
                            ("registry_pusher", ("container-registry.images.pusher",))):
            for role in roles:
                address = "yandex_resourcemanager_folder_iam_member." + name
                if name == "terraform":
                    address += "[" + json.dumps(role) + "]"
                self.resources[address].update(role=role, member="serviceAccount:yandex_iam_service_account." + name)
        self.plan = {"resource_changes": [
            {"address": name, "mode": "managed", "change": {"actions": ["delete"], "before": copy.deepcopy(attrs)}}
            for name, attrs in self.resources.items()
        ]}

    def check(self):
        return retire.validate_plan(self.plan, self.resources, "folder")

    def test_known_bootstrap(self):
        self.assertEqual(len(self.check()), 13)

    def test_wrong_id(self):
        self.plan["resource_changes"][0]["change"]["before"]["id"] = "other"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_wrong_folder(self):
        item = next(i for i in self.plan["resource_changes"] if i["address"] == "yandex_storage_bucket.state")
        item["change"]["before"]["folder_id"] = "other"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_wrong_member(self):
        item = next(i for i in self.plan["resource_changes"] if i["address"].endswith(".registry_pusher") and "iam_member" in i["address"])
        item["change"]["before"]["member"] = "serviceAccount:someone-else"
        with self.assertRaises(RuntimeError):
            self.check()

    def test_wrong_action(self):
        self.plan["resource_changes"][0]["change"]["actions"] = ["delete", "create"]
        with self.assertRaises(RuntimeError):
            self.check()


class BucketTests(unittest.TestCase):
    def setUp(self):
        self.s3 = Mock()
        self.version_pages = Mock()
        self.object_pages = Mock()
        self.object_pages.paginate.return_value = [{"Contents": [{"Key": retire.STATE_KEY}]}]
        self.s3.get_paginator.side_effect = lambda name: {
            "list_object_versions": self.version_pages, "list_objects_v2": self.object_pages
        }[name]
        self.s3.list_multipart_uploads.return_value = {}

    def test_pagination_and_delete_markers(self):
        self.version_pages.paginate.return_value = [
            {"Versions": [{"Key": retire.STATE_KEY, "VersionId": "v1", "Size": 12}]},
            {"DeleteMarkers": [{"Key": retire.STATE_KEY + ".tflock", "VersionId": "v2"}]}
        ]
        result = retire.versions(self.s3, "bucket")
        self.assertEqual({i["VersionId"] for i in result}, {"v1", "v2"})

    def test_unknown_key_blocks_deletion(self):
        self.version_pages.paginate.return_value = [{"Versions": [{"Key": "unrelated", "VersionId": "v1"}]}]
        with self.assertRaises(RuntimeError):
            retire.purge_versions(self.s3, "bucket", [])
        self.s3.delete_object.assert_not_called()

    def test_active_lock_blocks_deletion(self):
        self.object_pages.paginate.return_value = [{"Contents": [{"Key": retire.STATE_KEY + ".tflock"}]}]
        with self.assertRaises(RuntimeError):
            retire.purge_versions(self.s3, "bucket", [])
        self.s3.delete_object.assert_not_called()

    def test_changed_bucket_blocks_deletion(self):
        self.version_pages.paginate.return_value = [{"Versions": [{"Key": retire.STATE_KEY, "VersionId": "new"}]}]
        with self.assertRaises(RuntimeError):
            retire.purge_versions(self.s3, "bucket", [])
        self.s3.delete_object.assert_not_called()

    def test_deletes_explicit_versions_and_markers(self):
        pages = [{"Versions": [{"Key": retire.STATE_KEY, "VersionId": "v1", "Size": 12}],
                  "DeleteMarkers": [{"Key": retire.STATE_KEY + ".tflock", "VersionId": "v2"}]}]
        self.version_pages.paginate.side_effect = [pages, pages, [{}]]
        saved = retire.versions(self.s3, "bucket")
        with contextlib.redirect_stdout(io.StringIO()):
            retire.purge_versions(self.s3, "bucket", saved)
        calls = [call.kwargs for call in self.s3.delete_object.call_args_list]
        self.assertEqual(calls, [{"Bucket": "bucket", "Key": i["Key"], "VersionId": i["VersionId"]} for i in saved])


if __name__ == "__main__":
    unittest.main()
