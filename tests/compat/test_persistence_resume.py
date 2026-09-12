import tempfile
import unittest
import uuid
from pathlib import Path

from scripts.codex_loop_runtime.persistence import (
    build_resume_plan,
    build_state_manifest,
    resume_state_manifest,
)
from scripts.codex_loop_runtime.state import StateStore


class PersistenceResumeTests(unittest.TestCase):
    def _source_store(self, root: Path):
        state = StateStore(root / "source-state.sqlite3")
        task_id = uuid.uuid4().hex
        state.configure_task(
            task_id,
            "Resume this objective safely",
            ["Functional result", "Publication reconciled"],
            profile="feature",
            requires_validation=False,
            request_anchor="Resume this objective safely",
        )
        state.set_meta("workspace_binding", {"base_commit": "1" * 40, "base_tree": "2" * 40})
        state.set_plan([
            {"step": "finished", "status": "completed"},
            {"step": "remaining", "status": "in_progress"},
        ])
        state.record_steer("preserve this correction")
        return state

    def _runtime_dir(self, root: Path):
        runtime = root / "runtime"
        runtime.mkdir(exist_ok=True)
        old = tempfile.tempdir
        tempfile.tempdir = str(runtime)
        self.addCleanup(setattr, tempfile, "tempdir", old)

    def test_resume_plan_requires_current_source_observations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source_store(root)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            plan = build_resume_plan(manifest)
            kinds = [item["kind"] for item in plan["required_observations"]]
            self.assertIn("workspace_presence", kinds)
            self.assertIn("repository_head", kinds)
            self.assertIn("repository_tree", kinds)
            self.assertEqual(plan["freshness_rules"]["validation"], "HISTORICAL")
            self.assertEqual(plan["prior_task_id"], source.task_id)

    def test_resume_restores_same_lifecycle_id_and_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._runtime_dir(root)
            source = self._source_store(root)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": True,
                "repository_head": "1" * 40,
                "repository_tree": "2" * 40,
                "external_actions": [],
            })
            self.assertEqual(result["status"], "RESUMED")
            resumed = StateStore(Path(result["state"]))
            self.assertEqual(resumed.task_id, source.task_id)
            self.assertEqual(resumed.plan(), source.plan())
            self.assertEqual([x["text"] for x in resumed.request_steers()], ["preserve this correction"])
            self.assertEqual(resumed.validation_state_for_generation(resumed.generation())["passed_count"], 0)
            self.assertEqual(resumed.get_meta("historical_recovery_evidence")["validation"], "HISTORICAL")

    def test_missing_workspace_still_restores_same_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._runtime_dir(root)
            source = self._source_store(root)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": False,
                "repository_head": None,
                "repository_tree": None,
                "external_actions": [],
            })
            self.assertEqual(result["status"], "NEEDS_RECONCILIATION")
            self.assertTrue(result["created_task"])
            self.assertEqual(result["task_id"], source.task_id)
            resumed = StateStore(Path(result["state"]))
            self.assertIsNone(resumed.get_meta("workspace_binding"))
            self.assertEqual(resumed.get_meta("resume_expected_workspace")["base_commit"], "1" * 40)

    def test_source_divergence_is_explicit_and_old_pass_is_not_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._runtime_dir(root)
            source = self._source_store(root)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": True,
                "repository_head": "3" * 40,
                "repository_tree": "4" * 40,
                "external_actions": [],
            })
            self.assertEqual(result["status"], "SOURCE_DIVERGED")
            resumed = StateStore(Path(result["state"]))
            self.assertEqual(resumed.validation_state_for_generation(resumed.generation())["passed_count"], 0)
            self.assertIsNone(resumed.get_meta("workspace_binding"))
            self.assertFalse(result["workspace_bound"])

    def test_dispatched_non_idempotent_action_requires_reconciliation_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._runtime_dir(root)
            source = self._source_store(root)
            action_id = source.record_external("github_push", "planned", "push:abc", action_class="external_non_idempotent")
            source.record_external("github_push", "dispatched", "push:abc", action_class="external_non_idempotent", action_id=action_id)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            identity_hash = manifest["external_actions"][0]["identity_sha256"]
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": False,
                "repository_head": None,
                "repository_tree": None,
                "external_actions": [],
            })
            self.assertEqual(result["status"], "NEEDS_RECONCILIATION")
            resumed = StateStore(Path(result["state"]))
            rows = resumed.external_actions()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["state"], "dispatched")
            self.assertEqual(rows[0]["identity"], f"resume-sha256:{identity_hash}")
            self.assertEqual(result["unresolved_external_actions"][0]["state"], "missing_observation")

    def test_current_terminal_observation_reconciles_prior_dispatched_action(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._runtime_dir(root)
            source = self._source_store(root)
            action_id = source.record_external("github_push", "planned", "push:abc", action_class="external_non_idempotent")
            source.record_external("github_push", "dispatched", "push:abc", action_class="external_non_idempotent", action_id=action_id)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            identity_hash = manifest["external_actions"][0]["identity_sha256"]
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": True,
                "repository_head": "1" * 40,
                "repository_tree": "2" * 40,
                "external_actions": [{
                    "kind": "github_push",
                    "identity_sha256": identity_hash,
                    "state": "terminal_success",
                    "evidence": "remote ref matches the previously dispatched target",
                }],
            })
            self.assertEqual(result["status"], "RESUMED")
            resumed = StateStore(Path(result["state"]))
            self.assertEqual(resumed.external_actions()[0]["state"], "terminal_success")

    def test_outcome_unknown_never_turns_into_success_without_current_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._runtime_dir(root)
            source = self._source_store(root)
            action_id = source.record_external("deploy", "planned", "deploy:abc", action_class="external_non_idempotent")
            source.record_external("deploy", "dispatched", "deploy:abc", action_class="external_non_idempotent", action_id=action_id)
            source.record_external("deploy", "outcome_unknown", "deploy:abc", {"observed": "ambiguous"}, action_class="external_non_idempotent", action_id=action_id)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            identity_hash = manifest["external_actions"][0]["identity_sha256"]
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": True,
                "repository_head": "1" * 40,
                "repository_tree": "2" * 40,
                "external_actions": [{
                    "kind": "deploy",
                    "identity_sha256": identity_hash,
                    "state": "outcome_unknown",
                    "evidence": "provider still cannot determine terminal state",
                }],
            })
            self.assertEqual(result["status"], "EXTERNAL_ACTION_UNRESOLVED")
            resumed = StateStore(Path(result["state"]))
            self.assertEqual(resumed.external_actions()[0]["state"], "outcome_unknown")


if __name__ == "__main__":
    unittest.main()
