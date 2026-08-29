import json
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.codex_loop_runtime.lifecycle import assess_runtime_need, derive_capability_state


class LifecycleTests(unittest.TestCase):
    def test_trivial_request_stays_direct(self):
        view = assess_runtime_need({})
        self.assertEqual(view["mode"], "direct")
        self.assertFalse(view["requires_durable_runtime"])
        self.assertEqual(view["activation_reasons"], [])

    def test_workspace_or_delegation_escalates_to_durable(self):
        view = assess_runtime_need(workspace_observation=True, delegation=True)
        self.assertEqual(view["mode"], "durable")
        self.assertEqual(view["activation_reasons"], ["workspace_observation", "delegation"])

    def test_multiple_dependent_steps_alone_escalates_without_repository_signals(self):
        view = assess_runtime_need(multiple_dependent_steps=True)
        self.assertEqual(view["mode"], "durable")
        self.assertEqual(view["activation_reasons"], ["multiple_dependent_steps"])

    def test_durable_evidence_alone_escalates_without_repository_signals(self):
        view = assess_runtime_need(durable_evidence=True)
        self.assertEqual(view["mode"], "durable")
        self.assertEqual(view["activation_reasons"], ["durable_evidence"])

    def test_unknown_signal_fails_closed(self):
        with self.assertRaises(ValueError):
            assess_runtime_need({"complexity_level": True})

    def test_generation_drives_mutation_and_review_obligations(self):
        state = derive_capability_state(
            generation=2, validation_status="stale", review_status="stale",
            active_isolation=False, has_external_actions=False, has_managed_processes=False,
        )
        self.assertIn("mutation_tracking", state["active_capabilities"])
        self.assertEqual(state["requirements"]["validation"], "required")
        self.assertEqual(state["requirements"]["change_review"], "required")

    def test_no_mutation_means_no_change_review_obligation(self):
        state = derive_capability_state(
            generation=0, validation_status="waived", review_status="not-required",
            active_isolation=False, has_external_actions=False, has_managed_processes=False,
        )
        self.assertNotIn("mutation_tracking", state["active_capabilities"])
        self.assertNotIn("change_review", state["active_capabilities"])
        self.assertNotIn("validation", state["requirements"])
        self.assertNotIn("change_review", state["requirements"])

    def test_delegation_is_active_only_when_isolation_exists(self):
        base = dict(generation=0, validation_status="waived", review_status="not-required", has_external_actions=False, has_managed_processes=False)
        self.assertNotIn("delegation", derive_capability_state(active_isolation=False, **base)["active_capabilities"])
        self.assertIn("delegation", derive_capability_state(active_isolation=True, **base)["active_capabilities"])

    def test_external_and_process_capabilities_activate_only_when_currently_relevant(self):
        base = dict(generation=0, validation_status="waived", review_status="not-required", active_isolation=False)
        quiet = derive_capability_state(has_external_actions=False, has_managed_processes=False, **base)
        busy = derive_capability_state(has_external_actions=True, has_managed_processes=True, **base)
        self.assertNotIn("external_actions", quiet["active_capabilities"])
        self.assertNotIn("managed_processes", quiet["active_capabilities"])
        self.assertIn("external_actions", busy["active_capabilities"])
        self.assertIn("managed_processes", busy["active_capabilities"])

        self.assertEqual(busy["requirements"]["external_actions"], "required")
        self.assertEqual(busy["requirements"]["managed_processes"], "required")

    def test_repository_instructions_are_projected_only_when_discovered(self):
        base = dict(generation=0, validation_status="waived", review_status="not-required", active_isolation=False, has_external_actions=False, has_managed_processes=False)
        absent = derive_capability_state(has_repository_instructions=False, **base)
        present = derive_capability_state(has_repository_instructions=True, **base)
        self.assertNotIn("repository_instructions", absent["active_capabilities"])
        self.assertIn("repository_instructions", present["active_capabilities"])

    def test_completion_audit_reports_satisfied_after_pass(self):
        state = derive_capability_state(
            generation=0, validation_status="waived", review_status="not-required",
            active_isolation=False, has_external_actions=False, has_managed_processes=False,
            completion_status="PASS",
        )
        self.assertEqual(state["requirements"]["completion_audit"], "satisfied")


    def test_lifecycle_assess_cli_accepts_non_repository_multistep_signal(self):
        cli = Path(__file__).resolve().parents[2] / "scripts" / "codex_loop.py"
        proc = subprocess.run(
            [sys.executable, str(cli), "lifecycle-assess", "--multiple-dependent-steps"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True,
        )
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(data["mode"], "durable")
        self.assertEqual(data["activation_reasons"], ["multiple_dependent_steps"])

    def test_lifecycle_assess_cli_is_pre_runtime_and_task_independent(self):
        cli = Path(__file__).resolve().parents[2] / "scripts" / "codex_loop.py"
        proc = subprocess.run(
            [sys.executable, str(cli), "lifecycle-assess", "--workspace-observation"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True,
        )
        data = json.loads(proc.stdout)["data"]
        self.assertEqual(data["mode"], "durable")
        self.assertEqual(data["activation_reasons"], ["workspace_observation"])


if __name__ == "__main__":
    unittest.main()
