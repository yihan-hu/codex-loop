import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DriveDeletionAdapterTests(unittest.TestCase):
    def test_skill_routes_drive_storage_and_cleanup_through_shared_contracts(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/drive-storage.md", skill)
        self.assertIn("authoritative terminal evidence", skill)

    def test_adapter_keeps_delete_authority_separate_from_url_normalization(self):
        guide = (ROOT / "references" / "drive-deletion.md").read_text(encoding="utf-8")
        for required in (
            "never expands cleanup authority",
            "Drive ID, expected title, expected parent, and object kind",
            "Prefer a real provider trash operation",
            "delete_file` as **permanent deletion**",
            "Invalid Google Drive URL",
            "https://drive.google.com/file/d/<EXACT_DRIVE_ID>/view",
            "retry once",
            "Permission, ownership, authentication, safety/confirmation, policy",
            "terminal provider success completes cleanup",
            "outcome is unknown",
        ):
            self.assertIn(required, guide)

    def test_cleanup_surfaces_delegate_dispatch_to_shared_adapter(self):
        publish = (ROOT / "references" / "web-mode-publish.md").read_text(encoding="utf-8")
        handoff = (ROOT / "references" / "web-to-local-handoff.md").read_text(encoding="utf-8")
        profile = (ROOT / "references" / "host-profile.md").read_text(encoding="utf-8")
        architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        storage = (ROOT / "references" / "drive-storage.md").read_text(encoding="utf-8")
        self.assertIn("drive-deletion.md", publish)
        self.assertGreaterEqual(handoff.count("drive-deletion.md"), 2)
        self.assertIn("drive-deletion.md", profile)
        self.assertIn("ChatGPT-Temporary", architecture)
        self.assertIn("ChatGPT-Temporary/codex-loop/workspace-cache", storage)


if __name__ == "__main__":
    unittest.main()
