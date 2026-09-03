import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ConsumerOnboardingTests(unittest.TestCase):
    def test_skill_declares_base_use_has_no_external_setup(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Base use has zero external setup", skill)
        self.assertIn("consumer package has no repository binding", skill)
        self.assertIn("references/consumer-onboarding.md", skill)

    def test_onboarding_is_progressive_and_covers_optional_integrations(self):
        guide = (ROOT / "references" / "consumer-onboarding.md").read_text(encoding="utf-8")
        for required in (
            "Level 0",
            "Not required: GitHub, Google Drive",
            "Level 1",
            "Level 2",
            "ChatGPT-GitHub-Staging",
            "Anyone with the link -> Viewer/reader",
            "contents: write",
            "Level 3",
            "Remote Desktop Commander",
            "LOCAL_ROOT",
            "Never present all four integrations as a mandatory installation checklist",
        ):
            self.assertIn(required, guide)

    def test_consumer_guidance_does_not_bind_maintainer_repository(self):
        guide = (ROOT / "references" / "consumer-onboarding.md").read_text(encoding="utf-8")
        self.assertIn("provenance context, not the consumer's repository", guide)
        self.assertIn("Never ask a consumer to connect, fork, or authorize", guide)


if __name__ == "__main__":
    unittest.main()
