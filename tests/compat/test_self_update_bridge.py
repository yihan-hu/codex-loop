import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "scripts" / "build_self_update_bridge.py"


class SelfUpdateBridgeTests(unittest.TestCase):
    def test_generator_reproduces_proven_minimal_install_profile(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(GEN), "--output-dir", td, "--json"],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "BRIDGE_SOURCE_READY")
            self.assertEqual(payload["bridge_name"], "codex-loop-update-bridge")
            self.assertFalse(payload["production_package_mutation_allowed"])
            self.assertTrue(payload["minimal_profile"])
            self.assertEqual(payload["file_count"], 2)
            self.assertEqual(payload["default_prompt_self_reference"], "$codex-loop-update-bridge")

            bridge = Path(payload["path"])
            files = sorted(path.relative_to(bridge).as_posix() for path in bridge.rglob("*") if path.is_file())
            self.assertEqual(files, ["SKILL.md", "agents/openai.yaml"])

            skill = (bridge / "SKILL.md").read_text(encoding="utf-8")
            metadata = (bridge / "agents" / "openai.yaml").read_text(encoding="utf-8")
            self.assertIn("name: codex-loop-update-bridge", skill)
            self.assertIn("require an already-validated canonical `codex-loop` `skill.zip`", skill)
            self.assertIn("Present that exact package through the host-native Skill update surface", skill)
            self.assertIn("Do not invoke Codex Loop", skill)
            self.assertIn("allow_implicit_invocation: false", metadata)
            self.assertIn("default_prompt: Use $codex-loop-update-bridge", metadata)
            self.assertIn("  products:\n  - chatgpt\n  - codex\n  - api\n  - atlas\n", metadata)

    def test_generator_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run([sys.executable, str(GEN), "--output-dir", td], cwd=ROOT, check=True, capture_output=True)
            proc = subprocess.run([sys.executable, str(GEN), "--output-dir", td], cwd=ROOT, text=True, capture_output=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("refusing to overwrite", proc.stderr + proc.stdout)


if __name__ == "__main__":
    unittest.main()
