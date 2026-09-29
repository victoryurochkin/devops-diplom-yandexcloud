import runpy
from pathlib import Path
import tempfile
import unittest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/finish-decommission.py"))


class CleanupScopeTests(unittest.TestCase):
    def snapshot(self):
        return {
            MODULE["INFRA"]: {"secrets": ["YC_TERRAFORM_KEY", "UNRELATED_SECRET"], "variables": ["UNRELATED_VAR"]},
            MODULE["APP"]: {"secrets": ["YC_REGISTRY_PUSHER_KEY"], "variables": ["APP_WORKER_IPS"], "runners": []},
        }

    def test_only_explicit_project_names_are_selected(self):
        targets = MODULE["cleanup_targets"](self.snapshot())
        self.assertEqual(len(targets), 3)
        self.assertFalse(any("UNRELATED" in endpoint for endpoint in targets))

    def test_other_runner_is_preserved(self):
        snapshot = self.snapshot()
        snapshot[MODULE["APP"]]["runners"] = [{"name": "another-runner", "status": "online", "busy": True}]
        self.assertEqual(len(MODULE["cleanup_targets"](snapshot)), 3)

    def test_online_or_busy_diploma_runner_blocks_removal(self):
        for status, busy in (("online", False), ("offline", True)):
            snapshot = self.snapshot()
            snapshot[MODULE["APP"]]["runners"] = [{"name": MODULE["RUNNER_NAME"], "status": status, "busy": busy}]
            with self.assertRaises(RuntimeError):
                MODULE["cleanup_targets"](snapshot)

    def test_label_mismatch_blocks_removal(self):
        snapshot = self.snapshot()
        snapshot[MODULE["APP"]]["runners"] = [{"name": MODULE["RUNNER_NAME"], "status": "offline", "busy": False, "id": 12, "labels": []}]
        with self.assertRaises(RuntimeError):
            MODULE["cleanup_targets"](snapshot)

    def test_empty_inventory_is_idempotent(self):
        snapshot = self.snapshot()
        for kinds in snapshot.values():
            for kind in kinds:
                kinds[kind] = []
        self.assertEqual(MODULE["cleanup_targets"](snapshot), [])

    def test_only_the_valid_offline_runner_is_selected(self):
        snapshot = self.snapshot()
        snapshot[MODULE["APP"]]["runners"] = [{
            "name": MODULE["RUNNER_NAME"], "id": 12, "status": "offline", "busy": False,
            "labels": [{"name": "diplom-deploy"}],
        }]
        targets = MODULE["cleanup_targets"](snapshot)
        self.assertIn(f'repos/{MODULE["APP"]}/actions/runners/12', targets)
        snapshot[MODULE["APP"]]["runners"] *= 2
        with self.assertRaises(RuntimeError):
            MODULE["cleanup_targets"](snapshot)

    def test_nonempty_or_invalid_state_blocks_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            for content in ('{}', '{"resources":[{"mode":"managed","instances":[{}]}]}'):
                path.write_text(content)
                with self.assertRaises(RuntimeError):
                    MODULE["empty_state"](path)
            path.write_text('{"resources":[]}')
            MODULE["empty_state"](path)
