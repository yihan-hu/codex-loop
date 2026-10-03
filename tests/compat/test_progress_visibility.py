import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


def call(home: Path, *args: str, check: bool = True):
    env = os.environ.copy()
    env["CODEX_LOOP_HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    if check and proc.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    return payload, proc


class ProgressVisibilityTests(unittest.TestCase):
    def test_missing_config_uses_standard_defaults_without_writing_file(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            shown, _ = call(home, "progress-config")
            data = shown["data"]
            self.assertEqual(data["mode"], "standard")
            self.assertEqual(data["interval_seconds"], 15)
            self.assertEqual(data["tool_call_interval"], 3)
            self.assertTrue(data["upfront_plan"])
            self.assertTrue(data["material_event_updates"])
            self.assertEqual(data["source"], "default")
            self.assertFalse(data["repository_persisted"])
            self.assertFalse((home / "host.json").exists())

            substantive, _ = call(home, "progress-policy", "--work-shape", "substantive")
            self.assertEqual(substantive["data"]["visibility_mode"], "standard")
            self.assertEqual(substantive["data"]["periodic_updates"], "host_default")

            lightweight, _ = call(home, "progress-policy", "--work-shape", "lightweight")
            self.assertEqual(lightweight["data"]["visibility_mode"], "low_noise")
            self.assertFalse(lightweight["data"]["periodic_updates"])
            self.assertFalse(lightweight["data"]["emit_upfront_plan"])



    def test_overrides_are_private_and_preserve_unrelated_host_config(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            path = home / "host.json"
            path.write_text(json.dumps({"schema_version": 4, "workspace": {"environments": {"laptop": {"default_root": "/work"}}}}))
            os.chmod(path, 0o600)
            saved, _ = call(
                home,
                "progress-config",
                "--mode",
                "enhanced",
                "--interval-seconds",
                "22",
                "--tool-call-interval",
                "5",
                "--no-upfront-plan",
                "--material-event-updates",
            )
            self.assertTrue(saved["data"]["saved"])
            raw = json.loads(path.read_text())
            self.assertEqual(raw["schema_version"], 4)
            self.assertEqual(raw["workspace"]["environments"]["laptop"]["default_root"], "/work")
            self.assertEqual(raw["progress_visibility"]["interval_seconds"], 22)
            self.assertEqual(raw["progress_visibility"]["tool_call_interval"], 5)
            self.assertFalse(raw["progress_visibility"]["upfront_plan"])
            self.assertTrue(raw["progress_visibility"]["material_event_updates"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse(path.is_relative_to(ROOT))

            reset, _ = call(home, "progress-config", "--reset")
            self.assertTrue(reset["data"]["reset_to_defaults"])
            raw = json.loads(path.read_text())
            self.assertEqual(raw["schema_version"], 4)
            self.assertEqual(raw["workspace"]["environments"]["laptop"]["default_root"], "/work")
            self.assertNotIn("progress_visibility", raw)
            self.assertEqual(reset["data"]["mode"], "standard")

    def test_invalid_read_and_write_fail_without_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            path = home / "host.json"
            original = "{not-json\n"
            path.write_text(original)
            os.chmod(path, 0o600)

            policy, proc = call(home, "progress-policy", "--work-shape", "substantive", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(policy["ok"])

            failed, proc = call(home, "progress-config", "--interval-seconds", "20", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(failed["ok"])
            self.assertEqual(path.read_text(), original)

    def test_unsafe_host_config_path_blocks_read_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = root / "home"
            home.mkdir()
            target = root / "outside.json"
            target.write_text(json.dumps({"schema_version": 1, "progress_visibility": {"mode": "quiet"}}))
            path = home / "host.json"
            try:
                path.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            policy, proc = call(home, "progress-policy", "--work-shape", "substantive", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(policy["ok"])

            failed, proc = call(home, "progress-config", "--mode", "quiet", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(failed["ok"])
            self.assertTrue(path.is_symlink())

    def test_invalid_bounds_fail(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            for args in (
                ("--interval-seconds", "4"),
                ("--interval-seconds", "121"),
                ("--tool-call-interval", "0"),
                ("--tool-call-interval", "21"),
            ):
                payload, proc = call(home, "progress-config", *args, check=False)
                self.assertNotEqual(proc.returncode, 0)
                self.assertFalse(payload["ok"])

    def test_top_level_help_exposes_host_adapter_progress_commands(self):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Host-adapter commands:", proc.stdout)
        self.assertIn("progress-config", proc.stdout)
        self.assertIn("progress-policy", proc.stdout)
        self.assertIn("deployment-provenance-verify", proc.stdout)

    def test_progress_policy_is_optional_host_adapter_not_default_workflow(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        ref = (ROOT / "references" / "progress-visibility.md").read_text(encoding="utf-8")
        self.assertNotIn("### Progress visibility", skill)
        self.assertIn("optional", skill.lower())
        self.assertIn("host-facing behavior policy, not a second execution engine", ref)
        self.assertIn("15 seconds", ref)
        self.assertIn("3 substantive tool calls", ref)
        self.assertIn("progress-config --reset", ref)
        self.assertIn("lightweight work: no periodic progress messages", ref)


if __name__ == "__main__":
    unittest.main()
