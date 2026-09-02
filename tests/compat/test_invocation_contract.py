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

    def test_target_pursuit_is_opt_in_fail_closed_and_reuses_existing_completion_semantics(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("### Target-pursuit continuation policy", skill)
        self.assertIn("explicitly asks Codex Loop to keep iterating until a concrete objective is achieved", skill)
        self.assertIn("it is not a second mutable state machine and does not create a separate Skill", skill)
        self.assertIn("If the objective is still unmet and a useful next action is available, continue", skill)
        self.assertIn("Do not blindly retry the same failed action", skill)
        self.assertIn("Treat an unmodeled surprise that prevents the intended direct publish, deploy, install, or other external-action path as a **design defect**", skill)
        self.assertIn("Fail closed before the external action", skill)
        self.assertIn("make design repair the immediate next objective", skill)
        self.assertIn("An alternate route is allowed only when it was already part of the explicit design contract", skill)
        self.assertIn("Target-pursuit never implies background, asynchronous, hidden, or indefinitely running execution", skill)
        self.assertIn("`CONTINUE` means keep pursuing", skill)
        self.assertIn("`PASS` requires the ordinary fresh validation/review/evidence/objective-audit gates", skill)

    def test_implicit_invocation_stays_enabled(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('short_description: "Adaptive lifecycle for multi-step objectives"', metadata)
        self.assertIn('icon_small: "./assets/icon.svg"', metadata)
        self.assertIn('icon_large: "./assets/icon.svg"', metadata)
        self.assertNotIn("products:", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)


if __name__ == "__main__":
    unittest.main()
