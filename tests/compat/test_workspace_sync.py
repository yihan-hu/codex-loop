import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


class WorkspaceSyncOfferTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), "workspace-sync-offer", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_full_commit_generates_opt_in_sync_offer(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        proc = self.run_cli("--repository", "owner/repo", "--commit", sha)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(data["repository"], "owner/repo")
        self.assertEqual(data["commit"], sha)
        self.assertEqual(data["workflow_path"], ".github/workflows/workspace-download.yml")
        self.assertEqual(data["artifact_name"], "repo-source")
        self.assertEqual(data["sync_method"], "github_actions_artifact")
        self.assertIn("Sync this commit", data["offer_text"])
        self.assertIn("explicitly accepts", data["next_action"])

    def test_short_commit_fails_closed(self):
        proc = self.run_cli("--repository", "owner/repo", "--commit", "deadbeef")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("full 40-hex", proc.stdout + proc.stderr)

    def test_invalid_repository_fails_closed(self):
        proc = self.run_cli("--repository", "owner/repo/extra", "--commit", "0" * 40)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("OWNER/REPO", proc.stdout + proc.stderr)

    def test_docs_make_web_new_conversation_default_and_local_mode_conversation_persistent(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        verified_git = (ROOT / "references" / "verified-native-git.md").read_text()
        self.assertIn("A new conversation starts in **web mode**", skill)
        self.assertIn("later repository tasks in the same conversation inherit local mode", skill)
        self.assertIn("A new conversation resets to web mode", skill)
        self.assertIn("Local mode is explicit once per conversation", deployment)
        self.assertIn("local-mode state does not persist across conversations", deployment)
        self.assertIn("without requiring the user to repeat the mode selection", verified_git)
        self.assertIn("workspace-sync-offer", skill)
        self.assertNotIn("chatbox-handoff", skill)
        self.assertIn("Local post-push workspace synchronization", deployment)
        self.assertIn("WORKSPACE_SYNCED", deployment)
        self.assertIn("head_sha", deployment)
        self.assertIn("download_workflow_artifact", deployment)

    def test_workflow_emits_commit_bound_source_hash(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-download.yml").read_text()
        self.assertIn("git archive", workflow)
        self.assertIn("HEAD", workflow)
        self.assertIn("sha256sum", workflow)
        self.assertIn("name: codex-loop-source", workflow)


if __name__ == "__main__":
    unittest.main()
