import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WebPublishContractTests(unittest.TestCase):
    def test_skill_routes_web_push_to_verified_web_publish_contract(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        web_publish = (ROOT / "references" / "web-mode-publish.md").read_text()
        self.assertIn("references/web-mode-publish.md", skill)
        self.assertIn("Web-mode GitHub publishing", deployment)
        self.assertIn("ChatGPT-GitHub-Staging", web_publish)
        self.assertIn("binary `file_uri`", web_publish)
        self.assertIn("anyone: reader", web_publish)
        self.assertIn("GitHub Connector is control plane only", web_publish)
        self.assertIn("permanently delete the exact staged Drive archive", web_publish)
        self.assertIn("public transport artifact", web_publish)
        self.assertIn("does not apply here", web_publish)
        self.assertIn("FAST_PUBLISH", web_publish)
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

    def test_import_workflow_binds_and_verifies_archive(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-import.yml").read_text()
        self.assertIn(".github/import-requests/*.json", workflow)
        self.assertIn("permissions:\n  contents: write", workflow)
        self.assertIn("github.event.before", workflow)
        self.assertIn("github.ref_name", workflow)
        self.assertIn("drive.usercontent.google.com", workflow)
        self.assertIn("stat -c %s", workflow)
        self.assertIn("sha256sum -c -", workflow)
        self.assertIn("path.is_absolute() or '..' in path.parts", workflow)
        self.assertIn("member.issym() or member.islnk()", workflow)
        self.assertIn("archive must have one top-level directory", workflow)

    def test_import_workflow_protects_control_plane_and_reads_back_identity(self):
        workflow = (ROOT / ".github" / "workflows" / "workspace-import.yml").read_text()
        self.assertIn("--exclude='.git/'", workflow)
        self.assertIn("--exclude='.github/workflows/workspace-import.yml'", workflow)
        self.assertIn("--exclude='.github/import-requests/'", workflow)
        self.assertIn("git ls-remote origin", workflow)
        self.assertIn("refs/heads/$GITHUB_REF_NAME", workflow)
        self.assertIn("/tmp/workspace-import-request.json", workflow)
        self.assertIn("git push origin \"HEAD:$GITHUB_REF_NAME\"", workflow)
        self.assertIn("published_commit", workflow)
        self.assertIn("published_tree", workflow)
        self.assertIn("workspace-import-receipt-${{ github.run_id }}", workflow)

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


if __name__ == "__main__":
    unittest.main()
