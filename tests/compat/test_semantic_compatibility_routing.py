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
        self.assertIn("not as “stop the objective.”", routing)

        self.assertIn("source-acquisition intent", acquisition)
        self.assertIn("automatically translate that intent into this verified Git-bundle path", acquisition)
        self.assertIn("shell git clone/pull is forbidden", acquisition)
        self.assertIn("canonical path itself", acquisition)
        self.assertIn("synchronize the canonical Web repository", acquisition)

        self.assertIn("Publication intent translation", publish)
        self.assertIn("publication intent", publish)
        self.assertIn("absence of native `git push`", publish)
        self.assertIn("canonical Web publication path itself", publish)

    def test_equivalence_rule_does_not_weaken_unique_capability_boundaries(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text()

        self.assertIn("Only **pre-registered semantic equivalents** qualify", routing)
        self.assertIn("authorization boundary", routing)
        self.assertIn("security property", routing)
        self.assertIn("unique host capability", routing)
        self.assertIn("unless the user explicitly selects a different target", routing)


if __name__ == "__main__":
    unittest.main()
