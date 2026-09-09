import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InvocationContractTests(unittest.TestCase):
    def test_frontmatter_routes_broad_multistep_objectives(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(r'^description: "(.*)"$', skill, re.MULTILINE)
        self.assertIsNotNone(match)
        description = match.group(1).lower()
        for term in ("domain-agnostic", "multi-step", "research", "writing", "artifact", "coding", "lifecycle"):
            self.assertIn(term, description)
        self.assertNotIn("default coding and computer-use workflow", description)

    def test_body_declares_broad_invocation_and_direct_lifecycle_admission(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("**Broad invocation, direct lifecycle admission.**", skill)
        self.assertIn("enter the objective lifecycle directly", skill)
        self.assertIn("Do not run a second direct-vs-durable admission classifier", skill)
        self.assertIn("Keep optional machinery lazy", skill)

    def test_repository_location_rules_are_conditional(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("This section applies only when the active objective includes repository/filesystem work", skill)
        self.assertIn("skip `workspace_mode` and Web-vs-Local development machinery", skill)

    def test_until_terminal_continuation_is_opt_in_and_reuses_upstream_semantics(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("### Continuation policy", skill)
        self.assertIn("Default to `manual`", skill)
        self.assertIn("use `until_terminal`", skill)
        self.assertIn("`CONTINUE` means choose the smallest useful next action and continue automatically", skill)
        self.assertIn("`PASS` and genuine `BLOCKED` are terminal", skill)
        self.assertIn("never implies background or asynchronous execution", skill)
        self.assertIn("upstream Codex goal-continuation semantics", skill)

    def test_implicit_invocation_stays_enabled(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('short_description: "Objective lifecycle for multi-step work"', metadata)
        self.assertIn('icon_small: "./assets/icon.svg"', metadata)
        self.assertIn('icon_large: "./assets/icon.svg"', metadata)
        self.assertNotIn("products:", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)


if __name__ == "__main__":
    unittest.main()
