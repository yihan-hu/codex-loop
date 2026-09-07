import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


class ManualCodexLoopPackagePolicyTests(unittest.TestCase):
    def test_companion_installer_and_bridge_are_absent(self):
        self.assertFalse((ROOT / "skills" / "codex-loop-install").exists())
        self.assertFalse((ROOT / "scripts" / "build_self_update_bridge.py").exists())

    def test_docs_define_manual_package_as_terminal_update_deliverable(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        deployment = (ROOT / "references" / "skill-deployment.md").read_text(encoding="utf-8")
        runtime = (ROOT / "references" / "runtime-protocol.md").read_text(encoding="utf-8")
        for text in (skill, readme, deployment, runtime):
            self.assertIn("skill.zip", text)
            self.assertIn("codex-loop.zip", text)
        self.assertIn("Installation is manual", skill)
        self.assertIn("return only `codex-loop.zip`", skill)
        self.assertIn("manual installation", readme.lower())
        self.assertIn("normal chat download artifact", readme)
        self.assertIn("Stop there", deployment)
        self.assertIn("terminal state", runtime)

    def test_self_install_runtime_commands_are_removed(self):
        proc = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for command in (
            "skill-deploy-handoff",
            "skill-deploy-install-begin",
            "skill-deploy-resume",
            "skill-deploy-artifact-record",
            "skill-deploy-surface-record",
            "skill-deploy-complete",
        ):
            self.assertNotIn(command, proc.stdout)

    def test_no_companion_or_self_install_protocol_tokens_remain(self):
        roots = [
            ROOT / "SKILL.md", ROOT / "README.md", ROOT / "references", ROOT / "scripts",
        ]
        forbidden = [
            "codex-loop-install", "fixed_codex_loop_installer", "ARTIFACT_PREPARATION_READY",
            "skill_self_update_terminal_barrier", "verified_library_bridge",
        ]
        for base in roots:
            paths = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file() and p.suffix in {".md", ".py", ".yaml", ".yml"}]
            for path in paths:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for token in forbidden:
                    self.assertNotIn(token, text, f"{token} remains in {path.relative_to(ROOT)}")


if __name__ == "__main__":
    unittest.main()
