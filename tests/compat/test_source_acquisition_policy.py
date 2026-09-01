import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SourceAcquisitionPolicyTests(unittest.TestCase):
    def test_verified_latest_installed_skill_can_bootstrap_fresh_workspace(self):
        skill = (ROOT / "SKILL.md").read_text()
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        completion = (ROOT / "references" / "completion-criteria.md").read_text()
        runtime = (ROOT / "references" / "runtime-protocol.md").read_text()
        readme = (ROOT / "README.md").read_text()

        self.assertIn("one-time bootstrap source", skill)
        self.assertIn("latest observed target-branch HEAD", skill)
        self.assertIn("never edit the installed directory in place", skill)
        self.assertIn("Verified-latest installed Skill bootstrap", acquisition)
        self.assertIn("full 40-hex commit", acquisition)
        self.assertIn("version string", acquisition)
        self.assertIn("fresh development workspace", acquisition)
        self.assertIn("installed-Skill bootstrap", deployment)
        self.assertIn("exact repository/commit freshness evidence", completion)
        self.assertIn("verified-latest installed Skill", runtime)
        self.assertIn("installed Skill may be copied into a fresh workspace", readme)

    def test_explicit_github_to_web_acquisition_uses_actions_artifact_path(self):
        skill = (ROOT / "SKILL.md").read_text()
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        readme = (ROOT / "README.md").read_text()

        self.assertIn("Web source acquisition gate", skill)
        self.assertIn(".github/workflows/workspace-download.yml", skill)
        self.assertIn("artifact digest and source-archive SHA-256 verification", skill)
        self.assertIn("GitHub -> Web workspace: required path", acquisition)
        self.assertIn("workflow run whose head_sha == exact target commit", acquisition)
        self.assertIn("download_workflow_artifact", acquisition)
        self.assertIn("Do not substitute", acquisition)
        self.assertIn("shell `git clone`", acquisition)
        self.assertIn("explicitly asked for GitHub source", acquisition)
        self.assertIn("source path is fixed", deployment)
        self.assertIn("Acquiring GitHub source into Web mode", readme)

    def test_observability_gap_is_not_workflow_failure(self):
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        runtime = (ROOT / "references" / "runtime-protocol.md").read_text()
        readme = (ROOT / "README.md").read_text()

        self.assertIn("WORKSPACE_DOWNLOAD_OBSERVABILITY_UNAVAILABLE", acquisition)
        self.assertIn("not proof that the workflow never ran", acquisition)
        self.assertIn("observability limitation", runtime)
        self.assertIn("do not conclude that the workflow failed", readme)

    def test_workspace_download_workflow_supports_manual_dispatch(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-download.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("git archive", workflow)
        self.assertIn("sha256sum", workflow)
        self.assertIn("name: codex-loop-source", workflow)

    def test_verified_incremental_replay_and_receipt_bound_source_are_documented(self):
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        workflow = (ROOT / ".github" / "workflows" / "workspace-import.yml").read_text()
        self.assertIn("verified incremental replay", acquisition.lower())
        self.assertIn("complete Git tree SHA", acquisition)
        self.assertIn("receipt-bound source artifact", acquisition)
        self.assertIn("Build published source artifact", workflow)
        self.assertIn("published_source_sha256", workflow)
        self.assertIn("published-source-${{ github.run_id }}", workflow)



if __name__ == "__main__":
    unittest.main()
