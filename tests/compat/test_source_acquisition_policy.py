import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SourceAcquisitionPolicyTests(unittest.TestCase):
    def test_installed_skill_bootstrap_is_default_off_and_explicit_only(self):
        skill = (ROOT / "SKILL.md").read_text()
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        self.assertIn("references/source-acquisition.md", skill)
        self.assertIn("Installed Skill bootstrap: default off, explicit exception only", acquisition)
        self.assertIn("not part of normal source resolution", acquisition)
        self.assertIn("current-task user authorization", acquisition)
        self.assertIn("historical_explicitly_accepted", acquisition)
        self.assertIn("unverified_user_selected", acquisition)

    def test_explicit_github_to_web_acquisition_preserves_git_identity(self):
        skill = (ROOT / "SKILL.md").read_text()
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        self.assertIn("references/source-acquisition.md", skill)
        self.assertIn("GitHub -> Web workspace: COLD required path", acquisition)
        self.assertIn("repository-enter", acquisition)
        self.assertIn("HOT_REUSE", acquisition)
        self.assertIn("workflow run whose head_sha == exact target commit", acquisition)
        self.assertIn("download_workflow_artifact", acquisition)
        self.assertIn("git bundle verify", acquisition)
        self.assertIn("restored HEAD == exact target commit", acquisition)
        self.assertIn("restored HEAD^{tree} == exact target tree", acquisition)
        self.assertIn("source-acquisition-verify", acquisition)

    def test_observability_gap_is_not_workflow_failure(self):
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        self.assertIn("WORKSPACE_DOWNLOAD_OBSERVABILITY_UNAVAILABLE", acquisition)
        self.assertIn("not proof that the workflow never ran", acquisition)
        self.assertIn("same-authority read-only", acquisition)
        self.assertIn("receipt-bound", acquisition)
        self.assertIn("--same-authority-artifact-discovery-exhausted", acquisition)
        self.assertIn("CONTINUE_DISCOVERY", acquisition)
        self.assertIn("repository Actions runs", acquisition)

    def test_workspace_download_workflow_supports_manual_dispatch_and_bundle_export(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-download.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("paths-ignore:", workflow)
        self.assertIn(".github/import-requests/**", workflow)
        self.assertIn(".github/fast-import-requests/**", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("git bundle create", workflow)
        self.assertIn("git bundle verify", workflow)
        self.assertIn("sha256sum", workflow)
        self.assertIn("name: codex-loop-source", workflow)
        self.assertNotIn("git archive", workflow)

    def test_verified_incremental_replay_and_receipt_bound_bundle_are_documented(self):
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        workflow = (ROOT / ".github" / "workflows" / "workspace-import.yml").read_text()
        self.assertIn("verified incremental replay", acquisition.lower())
        self.assertIn("complete Git commit/tree identity", acquisition)
        self.assertIn("receipt-bound Git bundle", acquisition)
        self.assertIn("bundle_sha256", workflow)
        self.assertIn("source_commit", workflow)
        self.assertIn("source_tree", workflow)
        self.assertIn("published-source-${{ github.run_id }}", workflow)


if __name__ == "__main__":
    unittest.main()
