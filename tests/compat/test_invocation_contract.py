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
        self.assertIn("lifecycle admission is mandatory", description)
        self.assertIn("for a new objective, bootstrap before any substantive task action", description)
        self.assertIn("for an admitted continuation, reuse the exact task_id", description)
        self.assertIn("never continue outside", description)

    def test_selection_always_admits_one_lightweight_lifecycle(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Mandatory lifecycle admission", skill)
        self.assertIn("the first task action for a new objective must be `bootstrap`", skill)
        self.assertIn("fail closed", skill)
        self.assertIn("do not silently continue the objective as ordinary chat/tool execution", skill)
        self.assertIn("Do not run a second direct-vs-durable admission decision", skill)
        self.assertIn("Never re-bootstrap merely because the user says `continue`, `resume`, or `继续`", skill)
        self.assertIn("planning, workspace binding, checkpoints, persistence, managed processes, and separate review remain lazy", skill)
        self.assertIn("Pass it explicitly to every later command that reads or mutates lifecycle state", skill)
        self.assertIn("validate --task-id TASK --cwd REPO", skill)
        self.assertIn("validation-record --task-id TASK --cwd REPO", skill)

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

    def test_implicit_invocation_stays_enabled_and_default_prompt_admits_first(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('icon_small: "./assets/icon.svg"', metadata)
        self.assertIn('icon_large: "./assets/icon.svg"', metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)
        self.assertIn("bootstrap a new lifecycle or reuse the exact task_id", metadata)
        self.assertIn("before any task action", metadata)
        self.assertIn("never continue outside that lifecycle", metadata)


if __name__ == "__main__":
    unittest.main()
