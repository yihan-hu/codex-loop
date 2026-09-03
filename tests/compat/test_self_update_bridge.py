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

    def test_docs_make_verified_bridge_the_only_default_self_install_path(self):
        deployment = (ROOT / "references" / "skill-deployment.md").read_text(encoding="utf-8")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (deployment, skill, readme):
            self.assertIn("b5a748", text.lower())
            self.assertIn("build_self_update_bridge.py", text)
            self.assertIn("Library not found", text)
            self.assertNotIn("HOST_SAME_NAME_SKILL_UPDATE_SURFACE_UNSTABLE", text)
            self.assertNotIn("Try in chat", text)
            self.assertNotIn("A/B", text)
            self.assertIn("do not emit a follow-up bridge command", text.lower())
            self.assertNotIn("explicitly invoke that exact bridge", text.lower())
        self.assertIn("Default and only Codex Loop self-update Library path", deployment)
        self.assertIn("every", deployment.lower())
        self.assertIn("do not attempt the standard same-name/native production update", deployment.lower())
        self.assertIn("do not first try a standard same-name/native production update", readme.lower())
        self.assertIn("install_strategy=verified_library_bridge", skill)
        self.assertIn("native_self_update_attempt_allowed=false", skill)
        self.assertIn("exactly `SKILL.md` and `agents/openai.yaml`", deployment)
        self.assertIn("quoted", deployment)
        self.assertIn("no `policy.products`", deployment)

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
