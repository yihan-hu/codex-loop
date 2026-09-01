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
    def test_missing_config_uses_enhanced_defaults_without_writing_file(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            shown, _ = call(home, "progress-config")
            data = shown["data"]
            self.assertEqual(data["mode"], "enhanced")
            self.assertEqual(data["interval_seconds"], 15)
            self.assertEqual(data["tool_call_interval"], 3)
            self.assertTrue(data["upfront_plan"])
            self.assertTrue(data["material_event_updates"])
            self.assertEqual(data["source"], "default")
            self.assertFalse(data["repository_persisted"])
            self.assertFalse((home / "host.json").exists())

            durable, _ = call(home, "progress-policy", "--lifecycle-mode", "durable")
            self.assertEqual(durable["data"]["visibility_mode"], "enhanced")
            self.assertTrue(durable["data"]["periodic_updates"])
            self.assertEqual(durable["data"]["interval_seconds"], 15)
            self.assertEqual(durable["data"]["tool_call_interval"], 3)

            direct, _ = call(home, "progress-policy", "--lifecycle-mode", "direct")
            self.assertEqual(direct["data"]["visibility_mode"], "low_noise")
            self.assertFalse(direct["data"]["periodic_updates"])
            self.assertFalse(direct["data"]["emit_upfront_plan"])

            assessed, _ = call(home, "lifecycle-assess", "--multiple-dependent-steps")
            self.assertEqual(assessed["data"]["mode"], "durable")
            self.assertEqual(assessed["data"]["progress"]["visibility_mode"], "enhanced")
            self.assertEqual(assessed["data"]["progress"]["tool_call_interval"], 3)


    def test_overrides_are_private_and_preserve_unrelated_host_config(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            path = home / "host.json"
            path.write_text(json.dumps({"schema_version": 1, "default_local_workspace": "piwork"}))
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
            self.assertEqual(raw["schema_version"], 2)
            self.assertEqual(raw["workspace"]["default_local_workspace"], "piwork")
            self.assertEqual(raw["progress_visibility"]["interval_seconds"], 22)
            self.assertEqual(raw["progress_visibility"]["tool_call_interval"], 5)
            self.assertFalse(raw["progress_visibility"]["upfront_plan"])
            self.assertTrue(raw["progress_visibility"]["material_event_updates"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse(path.is_relative_to(ROOT))

            reset, _ = call(home, "progress-config", "--reset")
            self.assertTrue(reset["data"]["reset_to_defaults"])
            raw = json.loads(path.read_text())
            self.assertEqual(raw["schema_version"], 2)
            self.assertEqual(raw["workspace"]["default_local_workspace"], "piwork")
            self.assertNotIn("progress_visibility", raw)
            self.assertEqual(reset["data"]["mode"], "enhanced")

    def test_invalid_read_falls_back_but_write_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            path = home / "host.json"
            original = "{not-json\n"
            path.write_text(original)
            os.chmod(path, 0o600)

            policy, _ = call(home, "progress-policy", "--lifecycle-mode", "durable")
            self.assertEqual(policy["data"]["visibility_mode"], "enhanced")
            self.assertIn("invalid_host_config_json_using_defaults", policy["data"]["config"]["warnings"])

            failed, proc = call(home, "progress-config", "--interval-seconds", "20", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(failed["ok"])
            self.assertEqual(path.read_text(), original)

    def test_unsafe_host_config_path_does_not_block_read_policy(self):
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
            policy, _ = call(home, "progress-policy", "--lifecycle-mode", "durable")
            self.assertEqual(policy["data"]["visibility_mode"], "enhanced")
            self.assertTrue(any(x.startswith("unsafe_host_config_using_defaults:") for x in policy["data"]["config"]["warnings"]))

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
        self.assertIn("skill-deploy-handoff", proc.stdout)

    def test_skill_and_docs_bind_progress_policy_to_durable_lifecycle(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        ref = (ROOT / "references" / "progress-visibility.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("### Progress visibility", skill)
        self.assertIn("progress-policy --lifecycle-mode durable", skill)
        self.assertIn("Direct/trivial work remains low-noise", skill)
        self.assertIn("~/.codex-loop/host.json", skill)
        self.assertIn("15 seconds", ref)
        self.assertIn("3 substantive tool calls", ref)
        self.assertIn("progress-config --reset", ref)
        self.assertIn("Adaptive progress visibility", readme)


if __name__ == "__main__":
    unittest.main()
