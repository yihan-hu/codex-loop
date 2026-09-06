import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "scripts" / "build_self_update_bridge.py"


class SelfUpdateBridgeTests(unittest.TestCase):
    def test_generator_matches_user_verified_b5a748_library_save_template(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(GEN), "--output-dir", td, "--instance-id", "b5a748", "--json"],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(proc.stdout)
            bridge_name = "codex-loop-update-bridge-b5a748"
            self.assertEqual(payload["status"], "BRIDGE_SOURCE_READY")
            self.assertEqual(payload["template"], "b5a748-library-save-success")
            self.assertEqual(payload["bridge_name"], bridge_name)
            self.assertEqual(payload["instance_id"], "b5a748")
            self.assertFalse(payload["production_package_mutation_allowed"])
            self.assertFalse(payload["assistant_follow_up_command_required"])
            self.assertEqual(payload["next_step"], "package_and_save_generated_bridge_with_skill_creator_official_packager")
            self.assertEqual(payload["file_count"], 2)

            bridge = Path(payload["path"])
            files = sorted(path.relative_to(bridge).as_posix() for path in bridge.rglob("*") if path.is_file())
            self.assertEqual(files, ["SKILL.md", "agents/openai.yaml"])

            expected_skill = '''---
name: codex-loop-update-bridge-b5a748
description: "Disposable explicit-only recovery Skill for continuing the install-compatible ChatGPT Skill save path after a Library not found error. Use only when explicitly invoked during this recovery."
---

# Codex Loop Update Bridge B5A748

When explicitly invoked, require the already-validated canonical `codex-loop` `skill.zip` from the current conversation, present that exact package through the host-native Skill update surface, and end the turn immediately. Do not invoke Codex Loop and do not edit, repackage, rename, or substitute the canonical package.
'''
            expected_metadata = '''interface:
  display_name: "Codex Loop Update Bridge B5A748"
  short_description: "Install-compatible Skill save-path bridge"
  default_prompt: "Use $codex-loop-update-bridge-b5a748 to continue the install-compatible Skill save path after a Library not found error."
policy:
  allow_implicit_invocation: false
'''
            self.assertEqual((bridge / "SKILL.md").read_text(encoding="utf-8"), expected_skill)
            self.assertEqual((bridge / "agents" / "openai.yaml").read_text(encoding="utf-8"), expected_metadata)
            self.assertNotIn("products:", expected_metadata)

            installer_skill = (ROOT / "skills" / "codex-loop-install" / "SKILL.md").read_text(encoding="utf-8")
            terminal_sentence = "When explicitly invoked, require the already-validated canonical `codex-loop` `skill.zip` from the current conversation, present that exact package through the host-native Skill update surface, and end the turn immediately. Do not invoke Codex Loop and do not edit, repackage, rename, or substitute the canonical package."
            self.assertIn(terminal_sentence, installer_skill)

    def test_generator_auto_name_is_fresh_and_suffixed(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(GEN), "--output-dir", td, "--json"],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(proc.stdout)
            self.assertRegex(payload["bridge_name"], r"^codex-loop-update-bridge-[a-z0-9]{5,12}$")
            self.assertRegex(payload["instance_id"], r"^[a-z0-9]{5,12}$")

    def test_generator_has_fixed_library_not_found_recovery_for_installer_maintenance(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(GEN),
                    "--output-dir",
                    td,
                    "--target-skill",
                    "codex-loop-install",
                    "--instance-id",
                    "a1b2c3",
                    "--json",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["template"], "b5a748-library-save-envelope-installer-maintenance-v1")
            self.assertEqual(payload["bridge_name"], "codex-loop-install-update-bridge-a1b2c3")
            self.assertEqual(payload["recovery_target_skill"], "codex-loop-install")
            self.assertEqual(payload["recovery_trigger"], "Library not found")
            self.assertFalse(payload["normal_codex_loop_update_bridge_required"])
            self.assertFalse(payload["production_package_mutation_allowed"])

            bridge = Path(payload["path"])
            files = sorted(path.relative_to(bridge).as_posix() for path in bridge.rglob("*") if path.is_file())
            self.assertEqual(files, ["SKILL.md", "agents/openai.yaml"])
            skill = (bridge / "SKILL.md").read_text(encoding="utf-8")
            metadata = (bridge / "agents" / "openai.yaml").read_text(encoding="utf-8")
            self.assertIn("canonical `codex-loop-install` `skill.zip`", skill)
            self.assertIn("present that exact package through the host-native Skill update surface", skill)
            self.assertIn("Do not invoke Codex Loop or Codex Loop Install", skill)
            self.assertIn('display_name: "Codex Loop Install Update Bridge A1B2C3"', metadata)
            self.assertIn("allow_implicit_invocation: false", metadata)
            self.assertNotIn("products:", metadata)

    def test_docs_keep_bridge_as_explicit_recovery_fallback_only(self):
        deployment = (ROOT / "references" / "skill-deployment.md").read_text(encoding="utf-8")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("fixed_codex_loop_installer", deployment)
        self.assertIn("BRIDGE_NOT_SELECTED", deployment)
        self.assertIn("explicit user-requested recovery fallback", deployment)
        self.assertIn("fixed `codex-loop-install` companion", deployment)
        self.assertIn("build_self_update_bridge.py", deployment)
        self.assertIn("b5a748", deployment.lower())
        self.assertIn("visible temporary Library Skill", deployment)
        self.assertIn("Fixed `Library not found` recovery for installer maintenance", deployment)
        self.assertIn("--target-skill codex-loop-install", deployment)
        self.assertIn("normal `codex-loop` self-update path still uses no bridge", deployment)

        self.assertIn("fixed installer", skill.lower())
        self.assertIn("no automatic per-update bridge", skill.lower())
        self.assertIn("legacy", skill.lower())
        self.assertIn("explicit user-requested recovery", skill)

        self.assertIn("fixed companion Skill `codex-loop-install`", readme)
        self.assertIn("not created automatically", readme)
        self.assertIn("legacy bridge generator remains explicit recovery only", readme.lower())
        self.assertIn("Library not found", readme)
        self.assertIn("--target-skill codex-loop-install", readme)

        for text in (deployment, skill, readme):
            self.assertNotIn("HOST_SAME_NAME_SKILL_UPDATE_SURFACE_UNSTABLE", text)
            self.assertNotIn("Try in chat", text)
            self.assertNotIn("A/B", text)
        self.assertNotIn("Default and only Codex Loop self-update Library path", deployment)

    def test_generator_refuses_overwrite_same_instance(self):
        with tempfile.TemporaryDirectory() as td:
            argv = [sys.executable, str(GEN), "--output-dir", td, "--instance-id", "b5a748"]
            subprocess.run(argv, cwd=ROOT, check=True, capture_output=True)
            proc = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("refusing to overwrite", proc.stderr + proc.stdout)

    def test_generator_rejects_invalid_instance_id(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(GEN), "--output-dir", td, "--instance-id", "BAD"],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("instance id must be", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
