import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WebPublishContractTests(unittest.TestCase):
    def test_skill_routes_web_push_to_verified_exact_identity_contract(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        web_publish = (ROOT / "references" / "web-mode-publish.md").read_text()
        self.assertIn("references/web-mode-publish.md", skill)
        self.assertIn("Web-mode GitHub publishing", deployment)
        self.assertIn("ChatGPT-GitHub-Staging", web_publish)
        self.assertIn("binary Git bundle", web_publish)
        self.assertIn("anyone: reader", web_publish)
        self.assertIn("GitHub Connector is control plane only", web_publish)
        self.assertIn("remote commit == audited source commit", web_publish)
        self.assertIn("remote tree == audited source tree", web_publish)
        self.assertIn("force-with-lease", web_publish)
        self.assertIn("web-publish-plan", web_publish)

    def test_local_mode_remains_native_git_only(self):
        skill = (ROOT / "SKILL.md").read_text()
        release = (ROOT / "references" / "release-lineage.md").read_text()
        web_publish = (ROOT / "references" / "web-mode-publish.md").read_text()
        self.assertIn("native Git", release)
        self.assertIn("GitHub connector/object-API source upload is not a supported fallback", release)
        self.assertIn("This path is Web mode only", web_publish)
        self.assertIn("RDC + native Git", web_publish)
        self.assertIn("Local mode", skill)

    def test_import_workflow_binds_and_verifies_git_bundle(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-import.yml").read_text()
        self.assertIn(".github/import-requests/*.json", workflow)
        self.assertIn("permissions:\n  contents: write", workflow)
        self.assertIn("github.event.before", workflow)
        self.assertIn("github.ref_name", workflow)
        self.assertIn("bundle_file_id", workflow)
        self.assertIn("bundle_size", workflow)
        self.assertIn("bundle_sha256", workflow)
        self.assertIn("bundle_ref", workflow)
        self.assertIn("drive.usercontent.google.com", workflow)
        self.assertIn("stat -c %s", workflow)
        self.assertIn("sha256sum -c -", workflow)
        self.assertIn("git bundle verify", workflow)
        self.assertIn("git fetch /tmp/source.bundle", workflow)
        self.assertIn("source_commit", workflow)
        self.assertIn("source_tree", workflow)

    def test_import_workflow_only_replaces_its_own_trigger_and_reads_back_identity(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-import.yml").read_text()
        self.assertIn("git ls-remote origin", workflow)
        self.assertIn("test \"$remote_head\" = \"$GITHUB_SHA\"", workflow)
        self.assertIn("--force-with-lease=\"refs/heads/$GITHUB_REF_NAME:$GITHUB_SHA\"", workflow)
        self.assertIn("$source_commit:refs/heads/$GITHUB_REF_NAME", workflow)
        self.assertIn("published_commit", workflow)
        self.assertIn("published_tree", workflow)
        self.assertIn("workspace-import-receipt-${{ github.run_id }}", workflow)
        self.assertNotIn("git commit -m 'Import verified ChatGPT workspace source'", workflow)

    def test_fast_import_workflow_emits_self_contained_receipt_bound_source_artifact(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-import-fast.yml").read_text()
        self.assertIn(".github/fast-import-requests/*.json", workflow)
        self.assertIn("permissions:\n  contents: write", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("git bundle verify", workflow)
        self.assertIn("--force-with-lease", workflow)
        self.assertIn("Build and fresh-restore published acquisition bundle", workflow)
        self.assertIn("git clone -q /tmp/published-source.bundle", workflow)
        self.assertIn("fresh_restore=PASS", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)
        self.assertIn("published_source_sha256", workflow)
        self.assertIn("published_source_artifact_id", workflow)
        self.assertIn("CODEX_LOOP_FAST_IMPORT_RECEIPT=", workflow)

    def test_skill_description_stays_within_package_limit(self):
        skill = (ROOT / "SKILL.md").read_text()
        description_line = next(line for line in skill.splitlines() if line.startswith("description: "))
        description = description_line.removeprefix("description: ").strip().strip(chr(34))
        self.assertLessEqual(len(description), 1024)
        self.assertIn("Git/deployment", description)
        self.assertIn("Web/Local routing", description)

    def test_public_docs_explain_web_publish_prerequisites(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("Publishing from Web mode", readme)
        self.assertIn("Google Drive", readme)
        self.assertIn("ChatGPT-GitHub-Staging", readme)
        self.assertIn("anyone-with-link", readme)
        self.assertIn("workspace-import.yml", readme)
        self.assertIn("remote commit == audited commit and remote tree == audited tree", readme)


if __name__ == "__main__":
    unittest.main()
