import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.codex_loop_runtime.interaction_routing import resolve_interaction_target

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


def call(home: Path, *args: str, check: bool = True):
    env = os.environ.copy()
    env["CODEX_LOOP_HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    if check and proc.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    return payload, proc


class HostConfigTests(unittest.TestCase):
    def test_missing_config_uses_v3_safe_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            shown, _ = call(home, "host-config", "show")
            data = shown["data"]
            self.assertEqual(data["schema_version"], 3)
            self.assertEqual(data["progress_visibility"]["mode"], "enhanced")
            self.assertEqual(data["browser"]["preferred_target"], "cloud_browser")
            self.assertEqual(data["persistence"]["task_backend"], "off")
            self.assertEqual(data["persistence"]["host_profile_backend"], "local_only")
            self.assertFalse((home / "host.json").exists())

    def test_v1_migrates_to_v3_on_write_and_moves_workspace_alias(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"; home.mkdir()
            path = home / "host.json"
            path.write_text(json.dumps({"schema_version": 1, "default_local_workspace": "piwork", "progress_visibility": {"mode": "quiet"}}))
            os.chmod(path, 0o600)
            shown, _ = call(home, "host-config", "show")
            self.assertEqual(shown["data"]["workspace"]["default_local_workspace"], "piwork")
            self.assertEqual(shown["data"]["progress_visibility"]["mode"], "quiet")
            call(home, "host-config", "set", "browser.preferred_target", "cloud_browser")
            raw = json.loads(path.read_text())
            self.assertEqual(raw["schema_version"], 3)
            self.assertEqual(raw["workspace"]["default_local_workspace"], "piwork")
            self.assertNotIn("default_local_workspace", raw)

    def test_get_set_unset_reset(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            call(home, "host-config", "set", "web_publish.staging_folder_id", "folder123")
            got, _ = call(home, "host-config", "get", "web_publish.staging_folder_id")
            self.assertEqual(got["data"]["value"], "folder123")
            call(home, "host-config", "unset", "web_publish.staging_folder_id")
            got, _ = call(home, "host-config", "get", "web_publish.staging_folder_id")
            self.assertIsNone(got["data"]["value"])
            call(home, "host-config", "set", "progress_visibility.mode", "quiet")
            call(home, "host-config", "reset", "progress_visibility")
            got, _ = call(home, "host-config", "get", "progress_visibility.mode")
            self.assertEqual(got["data"]["value"], "enhanced")

    def test_unknown_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            payload, proc = call(home, "host-config", "set", "browser.secret_token", "x", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(payload["ok"])

    @unittest.skipIf(os.name == "nt", "POSIX permission model")
    def test_wrong_permissions_fall_back_on_read_and_fail_closed_on_write(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"; home.mkdir()
            path = home / "host.json"
            path.write_text(json.dumps({"schema_version": 2, "browser": {"preferred_target": "local_chrome"}}))
            os.chmod(path, 0o644)
            shown, _ = call(home, "host-config", "show")
            self.assertEqual(shown["data"]["browser"]["preferred_target"], "cloud_browser")
            self.assertTrue(shown["data"]["warnings"])
            before = path.read_text()
            payload, proc = call(home, "host-config", "set", "browser.preferred_target", "cloud_browser", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(payload["ok"])
            self.assertEqual(path.read_text(), before)

    def test_symlink_read_falls_back_and_write_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); home = root / "home"; home.mkdir()
            outside = root / "outside.json"; outside.write_text(json.dumps({"schema_version": 2}))
            path = home / "host.json"
            try:
                path.symlink_to(outside)
            except OSError:
                self.skipTest("symlink unavailable")
            shown, _ = call(home, "host-config", "show")
            self.assertEqual(shown["data"]["source"], "default")
            _, proc = call(home, "host-config", "set", "browser.preferred_target", "cloud_browser", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertTrue(path.is_symlink())

    def test_atomic_write_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            call(home, "host-config", "set", "workspace.default_local_workspace", "piwork")
            path = home / "host.json"
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["schema_version"], 3)


class BrowserRoutingTests(unittest.TestCase):
    def test_web_interaction_defaults_cloud_browser(self):
        result = resolve_interaction_target(requires_web_interaction=True, available_targets=["cloud_browser", "local_chrome"])
        self.assertEqual(result["target"], "cloud_browser")
        self.assertEqual(result["status"], "resolved")

    def test_explicit_local_chrome_requires_current_task_authorization(self):
        result = resolve_interaction_target(requires_web_interaction=True, explicit_target="local_chrome", available_targets=["local_chrome"])
        self.assertEqual(result["status"], "authorization_required")
        resolved = resolve_interaction_target(requires_web_interaction=True, explicit_target="local_chrome", available_targets=["local_chrome"], local_computer_authorized=True)
        self.assertEqual(resolved["status"], "resolved")

    def test_cloud_failure_never_silently_activates_local_chrome(self):
        result = resolve_interaction_target(requires_web_interaction=True, available_targets=["local_chrome"])
        self.assertEqual(result["target"], "cloud_browser")
        self.assertEqual(result["status"], "capability_missing")
        self.assertFalse(result["local_chrome_auto_activated"])


if __name__ == "__main__":
    unittest.main()
