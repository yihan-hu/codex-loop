import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


class ChatboxHandoffTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), "chatbox-handoff", *args], cwd=ROOT, text=True, capture_output=True)

    def test_full_commit_generates_copyable_user_message_handoff(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        proc = self.run_cli("--repository", "owner/repo", "--commit", sha)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(data["archive_url"], f"https://github.com/owner/repo/archive/{sha}.zip")
        prompt = data["copy_prompt"]
        self.assertIn(data["archive_url"], prompt)
        self.assertIn("本条用户消息", prompt)
        self.assertIn("skill.zip", prompt)
        self.assertIn("不要改用 GitHub connector", prompt)
        self.assertIn("next chatbox message", data["next_action"])

    def test_short_commit_fails_closed(self):
        proc = self.run_cli("--repository", "owner/repo", "--commit", "deadbeef")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("full 40-hex", proc.stdout + proc.stderr)

    def test_invalid_repository_fails_closed(self):
        proc = self.run_cli("--repository", "owner/repo/extra", "--commit", "0" * 40)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("OWNER/REPO", proc.stdout + proc.stderr)


    def test_docs_require_standard_post_push_handoff(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        self.assertIn("After every successful GitHub source push", skill)
        self.assertIn("append a copy/paste handoff after every successful GitHub source push", deployment)
        self.assertIn("next user message", deployment)
        self.assertIn("Never label this handoff `DEPLOYED`", deployment)


if __name__ == "__main__":
    unittest.main()
