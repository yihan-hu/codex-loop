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
        self.assertIn("a new conversation starts in **web mode**", skill)
        self.assertIn("later repository tasks in the same conversation inherit the baseline", skill)
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

    def test_development_location_is_mandatory_pre_tool_gate(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        local_setup = (ROOT / "references" / "local-mode-setup.md").read_text()
        readme = (ROOT / "README.md").read_text()

        self.assertIn("Mandatory pre-tool routing gate", skill)
        self.assertIn("Before the first repository/filesystem observation or discovery", skill)
        self.assertIn("Fail-closed Web rule", skill)
        self.assertIn("RDC availability", skill)
        self.assertIn("absence of an obvious Web-mode mutation/publish bridge", skill)
        self.assertIn("Web-push then local-sync sequencing", skill)
        self.assertIn("downstream destination of the exact pushed commit", skill)

        self.assertIn("Development mode is a pre-tool gate", deployment)
        self.assertIn("Web mode fails closed", deployment)
        self.assertIn("do not inspect the local host before publication", deployment)
        self.assertIn("Development-location resolution must happen before any **repository-affecting** RDC/local-filesystem discovery", local_setup)
        self.assertIn("pre-tool routing gate", readme)
        self.assertIn("Web edit/validate/review -> verified Web publish", readme)

    def test_public_readme_and_configurable_local_root_contract(self):
        readme = (ROOT / "README.md").read_text()
        local_setup = (ROOT / "references" / "local-mode-setup.md").read_text()
        skill = (ROOT / "SKILL.md").read_text()
        self.assertIn("## What it can do", readme)
        self.assertIn("## Local mode requirements", readme)
        self.assertIn("Remote Desktop Commander", readme)
        self.assertIn("workspace-download.yml", readme)
        self.assertIn("## Skill packaging and installation", readme)
        self.assertIn("`LOCAL_ROOT`", local_setup)
        self.assertIn("Otherwise ask once for the exact absolute root", local_setup)
        self.assertIn("references/local-mode-setup.md", skill)
        self.assertIn("Windows Local mode is supported on a best-effort/beta basis", skill)
        self.assertIn("C:\\Users\\Alice\\PiWork", readme)
        self.assertIn("Host platform contract", local_setup)
        self.assertIn("do not reject Local mode solely because RDC reports Windows", local_setup)
        self.assertIn("references/web-to-local-handoff.md", skill)
        self.assertIn("never an automatic downgrade", skill)
        handoff = (ROOT / "references" / "web-to-local-handoff.md").read_text()
        self.assertIn('route-transition --workspace-mode local --selection-evidence', handoff)
        self.assertIn("Never ask the model to recreate files", handoff)

    def test_public_docs_do_not_hardcode_author_local_root(self):
        docs = [ROOT / "SKILL.md", ROOT / "README.md", *sorted((ROOT / "references").glob("*.md"))]
        for path in docs:
            self.assertNotIn("/Users/yihanhu/PiWork", path.read_text(), str(path))

    def test_workflow_emits_commit_bound_source_hash(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-download.yml").read_text()
        self.assertIn("git bundle create", workflow)
        self.assertIn("git bundle verify", workflow)
        self.assertIn("HEAD", workflow)
        self.assertIn("sha256sum", workflow)
        self.assertNotIn("git archive", workflow)
        self.assertIn("name: codex-loop-source", workflow)
        self.assertIn("workflow_dispatch:", workflow)


if __name__ == "__main__":
    unittest.main()
