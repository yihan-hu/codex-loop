import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SemanticCompatibilityRoutingTests(unittest.TestCase):
    def test_common_web_operations_are_treated_as_intent_not_literal_transport(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        acquisition = (ROOT / "references" / "source-acquisition.md").read_text()
        publish = (ROOT / "references" / "web-mode-publish.md").read_text()

        self.assertIn("Semantic compatibility routing", routing)
        self.assertIn("user intent", routing)
        self.assertIn("pre-registered semantic equivalent", routing)
        self.assertIn("requires_host_visible_execution", routing)
        self.assertIn("logical-isolation/serialized delegation", routing)
        self.assertIn("Workspace Cache", routing)
        self.assertIn("chatgpt_web_skill", routing)
        self.assertIn("local Chrome profile/session", routing)
        self.assertIn("not “stop the objective.”", routing)

        self.assertIn("COLD_ACQUIRE_REQUIRED", acquisition)
        self.assertIn("not automatically source-acquisition intent", acquisition)
        self.assertIn("repository-enter", acquisition)
        self.assertIn("fetch only the missing remote objects", acquisition)
        self.assertIn("Local mode uses native Git after routing", acquisition)
        self.assertIn("canonical path itself", acquisition)
        self.assertIn("integrate in that same workspace", acquisition)

        self.assertIn("Publication intent translation", publish)
        self.assertIn("publication intent", publish)
        self.assertIn("absence of native `git push`", publish)
        self.assertIn("canonical Web publication path itself", publish)
        self.assertIn("published_tree == audited source_tree", publish)

    def test_skill_keeps_intent_translation_in_routing_reference(self):
        skill = (ROOT / "SKILL.md").read_text()
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        self.assertIn("references/interaction-routing.md", skill)
        self.assertIn("Keep routing checks at the action boundary", skill)
        self.assertNotIn("Common command intent interception", skill)
        self.assertIn("`git clone`, `git pull`, `git fetch`", routing)
        self.assertIn("`git push`", routing)
        self.assertIn("intercept before literal Git", routing)
        self.assertIn("Ordinary target repositories never need to contain Codex Loop runtime files", routing)
        self.assertIn("Drive staging -> RDC", routing)
        self.assertIn("validated `skill.zip`", routing)


    def test_equivalence_rule_does_not_weaken_unique_capability_boundaries(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text()

        self.assertIn("Only **pre-registered semantic equivalents** qualify", routing)
        self.assertIn("authorization boundary", routing)
        self.assertIn("security property", routing)
        self.assertIn("unique host capability", routing)
        self.assertIn("unless the user explicitly selects a different target", routing)


if __name__ == "__main__":
    unittest.main()
