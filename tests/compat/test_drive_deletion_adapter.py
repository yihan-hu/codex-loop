import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class DriveDeletionAdapterTests(unittest.TestCase):
    def test_skill_routes_destructive_drive_cleanup_through_shared_adapter(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/drive-deletion.md", skill)
        self.assertIn("same exact ID", skill)

    def test_adapter_keeps_delete_authority_separate_from_url_normalization(self):
        guide = (ROOT / "references" / "drive-deletion.md").read_text(encoding="utf-8")
        for required in (
            "never expands deletion authority",
            "Drive ID, expected title, expected parent, and object kind",
            "Invalid Google Drive URL",
            "https://drive.google.com/file/d/<EXACT_DRIVE_ID>/view",
            "retry the same delete operation once",
            "Permission, ownership, authentication, safety/confirmation, policy",
            "do not blindly retry",
            "no longer resolves",
        ):
            self.assertIn(required, guide)

    def test_cleanup_surfaces_delegate_dispatch_to_shared_adapter(self):
        publish = (ROOT / "references" / "web-mode-publish.md").read_text(encoding="utf-8")
        handoff = (ROOT / "references" / "web-to-local-handoff.md").read_text(encoding="utf-8")
        profile = (ROOT / "references" / "host-profile.md").read_text(encoding="utf-8")
        architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("drive-deletion.md", publish)
        self.assertGreaterEqual(handoff.count("drive-deletion.md"), 2)
        self.assertIn("drive-deletion.md", profile)
        self.assertIn("Drive deletion adapter", architecture)


if __name__ == "__main__":
    unittest.main()
