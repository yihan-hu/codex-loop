import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "scripts" / "build_self_update_bridge.py"


class SelfUpdateBridgeTests(unittest.TestCase):
    def test_generator_reproduces_proven_minimal_install_profile_with_fresh_name(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(GEN), "--output-dir", td, "--instance-id", "a91d4", "--json"],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(proc.stdout)
            bridge_name = "codex-loop-update-bridge-a91d4"
            self.assertEqual(payload["status"], "BRIDGE_SOURCE_READY")
            self.assertEqual(payload["bridge_name"], bridge_name)
            self.assertEqual(payload["bridge_name_prefix"], "codex-loop-update-bridge")
            self.assertEqual(payload["instance_id"], "a91d4")
            self.assertTrue(payload["fresh_unique_identity"])
            self.assertFalse(payload["fixed_name_reuse_allowed"])
            self.assertFalse(payload["production_package_mutation_allowed"])
            self.assertTrue(payload["minimal_profile"])
            self.assertTrue(payload["install_compatible_metadata_profile"])
            self.assertFalse(payload["policy_products_present"])
            self.assertEqual(payload["file_count"], 2)
            self.assertEqual(payload["default_prompt_self_reference"], f"${bridge_name}")

            bridge = Path(payload["path"])
            files = sorted(path.relative_to(bridge).as_posix() for path in bridge.rglob("*") if path.is_file())
            self.assertEqual(files, ["SKILL.md", "agents/openai.yaml"])

            skill = (bridge / "SKILL.md").read_text(encoding="utf-8")
            metadata = (bridge / "agents" / "openai.yaml").read_text(encoding="utf-8")
            self.assertIn(f"name: {bridge_name}", skill)
            self.assertIn("require an already-validated canonical `codex-loop` `skill.zip`", skill)
            self.assertIn("Present that exact package through the host-native Skill update surface", skill)
            self.assertIn("Do not invoke Codex Loop", skill)
            self.assertIn("allow_implicit_invocation: false", metadata)
            self.assertIn(f"default_prompt: Use ${bridge_name}", metadata)
            self.assertNotIn("products:", metadata)
            self.assertNotIn("policy.products", metadata)

    def test_generator_auto_name_is_suffixed_not_fixed_identity(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(GEN), "--output-dir", td, "--json"],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(proc.stdout)
            self.assertNotEqual(payload["bridge_name"], "codex-loop-update-bridge")
            self.assertRegex(payload["bridge_name"], r"^codex-loop-update-bridge-[a-z0-9]{5,12}$")
            self.assertRegex(payload["instance_id"], r"^[a-z0-9]{5,12}$")

    def test_docs_bind_recovery_to_fresh_bridge_identity(self):
        deployment = (ROOT / "references" / "skill-deployment.md").read_text(encoding="utf-8")
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (deployment, skill, readme):
            self.assertIn("codex-loop-update-bridge-", text)
            self.assertIn("policy.products", text)
        self.assertIn("fresh unique identity", deployment)
        self.assertIn("Try in chat", deployment)
        self.assertIn("never the unsuffixed fixed identity", skill)
        self.assertIn("fresh for every recovery attempt", readme)

    def test_generator_refuses_overwrite_same_instance(self):
        with tempfile.TemporaryDirectory() as td:
            argv = [sys.executable, str(GEN), "--output-dir", td, "--instance-id", "a91d4"]
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
