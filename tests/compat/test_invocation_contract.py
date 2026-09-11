import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InvocationContractTests(unittest.TestCase):
    def test_frontmatter_routes_long_or_routing_sensitive_objectives(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(r'^description: "(.*)"$', skill, re.MULTILINE)
        self.assertIsNotNone(match)
        description = match.group(1).lower()
        for term in (
            "repository/filesystem",
            "git/source publication",
            "skill update/deploy",
            "web/local routing",
            "multi-step",
            "resume",
        ):
            self.assertIn(term, description)
        self.assertIn("native codex-style agent execution", description)
        self.assertNotIn("workflow engine", description)

    def test_body_uses_thin_native_agent_loop(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Default execution model", skill)
        self.assertIn("execute <-> inspect/test/repair -> optional one review -> final acceptance -> done", skill)
        self.assertIn("Do not bootstrap durable state merely because Codex Loop was selected", skill)
        self.assertIn("Optional capabilities", skill)
        self.assertIn("Activate them only for tasks that actually need them", skill)

    def test_repository_routing_stays_at_side_effect_boundary(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Repository and host routing", skill)
        self.assertIn("Web is the default workspace until the user explicitly selects Local", skill)
        self.assertIn("Keep routing checks at the action boundary", skill)
        self.assertIn("Do not force unrelated reasoning/edit/test steps through routing state", skill)

    def test_implicit_invocation_stays_enabled(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('icon_small: "./assets/icon.svg"', metadata)
        self.assertIn('icon_large: "./assets/icon.svg"', metadata)
        self.assertNotIn("products:", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)


if __name__ == "__main__":
    unittest.main()
