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

    def test_docs_make_web_new_conversation_default_and_local_selection_explicit(self):
        skill = (ROOT / "SKILL.md").read_text()
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        self.assertIn("Web is the default workspace until the user explicitly selects Local", skill)
        self.assertIn("Every new conversation starts with `workspace_mode=web`", routing)
        self.assertIn("Enter `local` only after explicit local repository-development intent", routing)
        self.assertIn("workspace-sync-offer", deployment)
        self.assertIn("WORKSPACE_SYNCED", deployment)

    def test_development_location_is_checked_at_repository_action_boundary(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        local_setup = (ROOT / "references" / "local-mode-setup.md").read_text()

        self.assertIn("Before repository/filesystem mutation, Git publication, local computer use, Skill deployment, or Web/Local transfer", skill)
        self.assertIn("Keep routing checks at the action boundary", skill)
        self.assertIn("Development mode is a pre-tool gate", deployment)
        self.assertIn("Web mode fails closed", deployment)
        self.assertIn("Development-location resolution must happen before any **repository-affecting** RDC/local-filesystem discovery", local_setup)

    def test_public_readme_and_configurable_local_root_contract(self):
        readme = (ROOT / "README.md").read_text()
        local_setup = (ROOT / "references" / "local-mode-setup.md").read_text()
        skill = (ROOT / "SKILL.md").read_text()
        handoff = (ROOT / "references" / "web-to-local-handoff.md").read_text()
        self.assertIn("## What it can do", readme)
        self.assertIn("## Local mode requirements", readme)
        self.assertIn("Remote Desktop Commander", readme)
        self.assertIn("workspace-download.yml", readme)
        self.assertIn("`LOCAL_ROOT`", local_setup)
        self.assertIn("Otherwise ask once for the exact absolute root", local_setup)
        self.assertIn("local-mode-setup.md", (ROOT / "references" / "skill-deployment.md").read_text())
        self.assertIn("references/web-to-local-handoff.md", skill)
        self.assertIn("exact self-contained verified Git bundle", handoff)
        self.assertIn("Google Drive binary staging", handoff)
        self.assertIn("RDC downloads the exact binary", handoff)
        self.assertIn("Do not choose among transports", handoff)

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
