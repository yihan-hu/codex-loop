from __future__ import annotations

import re
import unittest
import uuid
from pathlib import Path

from scripts.codex_loop_runtime.routing_state import route_check, route_init, route_transition

ROOT = Path(__file__).resolve().parents[2]


class CrossChatAdmissionTests(unittest.TestCase):
    def sid(self) -> str:
        return f"cross-chat-admission-{uuid.uuid4().hex}"

    def cleanup(self, state: dict | None) -> None:
        if not state:
            return
        path = Path(state["state_path"])
        for candidate in (path, path.with_suffix(".capabilities.json")):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass

    def test_frontmatter_admits_short_routing_sensitive_intents(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(r'^description: "(.*)"$', skill, re.MULTILINE)
        self.assertIsNotNone(match)
        description = match.group(1).lower()
        for required in (
            "repository/filesystem",
            "install/update/deploy",
            "one/two-step",
            "pull main and install",
            "prior-chat authorization",
        ):
            self.assertIn(required, description)

    def test_new_web_session_does_not_inherit_prior_local_selection(self):
        previous = route_init(session_id=self.sid(), host_surface="chatgpt_web")
        current = None
        try:
            route_transition(
                session_id=previous["session_id"],
                workspace_mode="local",
                selection_evidence="user explicitly selected local in the previous conversation",
                current_user_selection_observed=True,
            )
            self.assertEqual(previous["host_surface"], "chatgpt_web")

            current = route_init(session_id=self.sid(), host_surface="chatgpt_web")
            self.assertEqual(current["workspace_mode"], "web")
            blocked = route_check(action="rdc_repository", session_id=current["session_id"])
            self.assertFalse(blocked["allowed"])
            self.assertEqual(blocked["effective_workspace"], "web")
        finally:
            self.cleanup(previous)
            self.cleanup(current)


if __name__ == "__main__":
    unittest.main()
