import unittest

from scripts.codex_loop_runtime.lifecycle import derive_capability_state


class LifecycleTests(unittest.TestCase):
    def test_capabilities_are_projected_without_secondary_admission(self):
        state = derive_capability_state(
            generation=2, validation_status="stale", active_isolation=False,
            has_external_actions=False, has_managed_processes=False,
        )
        self.assertEqual(state["mode"], "durable")
        self.assertIn("mutation_tracking", state["active_capabilities"])
        self.assertEqual(state["requirements"]["validation"], "required")
        self.assertNotIn("change_review", state["requirements"])

    def test_optional_capabilities_activate_only_when_present(self):
        state = derive_capability_state(
            generation=0, validation_status="waived", active_isolation=True,
            has_external_actions=True, has_managed_processes=True,
            has_repository_instructions=True, completion_status="CONTINUE",
        )
        for name in ("delegation", "external_actions", "managed_processes", "repository_instructions"):
            self.assertIn(name, state["active_capabilities"])
        self.assertNotIn("validation", state["requirements"])


if __name__ == "__main__":
    unittest.main()
