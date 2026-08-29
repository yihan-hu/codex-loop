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
        for term in ("domain-agnostic", "multi-step", "research", "writing", "artifact", "coding", "adaptive"):
            self.assertIn(term, description)
        self.assertNotIn("default coding and computer-use workflow", description)

    def test_body_declares_broad_invocation_and_adaptive_execution(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("**Broad invocation, adaptive execution.**", skill)
        self.assertIn("Do not pre-filter Codex Loop by domain before this assessment.", skill)
        self.assertIn("Multiple dependent steps or a need for durable evidence are sufficient activation signals even when no code or repository is involved", skill)

    def test_repository_location_rules_are_conditional(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("This section applies only when the active objective includes repository/filesystem work", skill)
        self.assertIn("skip `workspace_mode` and Web-vs-Local development machinery", skill)

    def test_implicit_invocation_stays_enabled(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("short_description: Adaptive lifecycle for multi-step objectives", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)


if __name__ == "__main__":
    unittest.main()
