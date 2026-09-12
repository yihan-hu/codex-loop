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
        self.assertIn("once selected, enter the standard codex loop lifecycle directly", description)

    def test_selection_always_creates_one_lightweight_lifecycle(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("create and enter one real Codex Loop lifecycle immediately", skill)
        self.assertIn("Do not run a second direct-vs-durable admission decision", skill)
        self.assertIn("Never re-bootstrap merely because the user says `continue`, `resume`, or `继续`", skill)
        self.assertIn("planning, workspace binding, checkpoints, persistence, managed processes, and separate review remain lazy", skill)

    def test_scope_contract_does_not_let_plan_expand_authority(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("The user owns **what** may change; the model owns **how**", skill)
        self.assertIn("may guide execution but never expand that scope", skill)

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
        self.assertIn("allow_implicit_invocation: true", metadata)


if __name__ == "__main__":
    unittest.main()
