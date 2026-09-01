import json
import tempfile
import unittest
from pathlib import Path

from scripts.codex_loop_runtime.persistence import (
    build_resume_plan,
    build_state_manifest,
    resume_state_manifest,
    validate_state_manifest,
)
from scripts.codex_loop_runtime.state import StateStore


class PersistenceResumeTests(unittest.TestCase):
    def _source_store(self, root: Path):
        state = StateStore(root / "source-state.sqlite3")
        state.configure_task(
            "s" * 32,
            "Resume this objective safely",
            ["Functional result", "Publication reconciled"],
            profile="feature",
            requires_validation=False,
            no_validation_reason="fixture does not execute validation",
        )
        state.set_criterion(0, "pass", "historical proof")
        state.set_meta("changes_reviewed_generation", 0)
        state.set_meta("objective_completion_audit", {"generation": 0, "requirements": [{"status": "proven"}]})
        state.set_meta("workspace_binding", {"base_commit": "1" * 40, "base_tree": "2" * 40})
        return state

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

    def test_resume_creates_new_freshness_domain_and_stales_pass_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "file.txt").write_text("current reality\n", encoding="utf-8")
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
            self.assertNotEqual(resumed.task_id, source.task_id)
            self.assertEqual(resumed.generation(), 0)
            self.assertTrue(all(item["status"] == "pending" for item in resumed.criteria()))
            self.assertEqual(resumed.validation_state_for_generation(0)["passed_count"], 0)
            self.assertEqual(resumed.get_meta("historical_recovery_evidence")["validation"], "HISTORICAL")
            self.assertEqual(resumed.get_meta("resume_lineage")["prior_generation"], 0)

    def test_missing_source_observation_requires_reconciliation_not_divergence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source_store(root)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": True,
                "repository_head": None,
                "repository_tree": None,
                "external_actions": [],
            })
            self.assertEqual(result["status"], "NEEDS_RECONCILIATION")
            self.assertFalse(result["source_diverged"])
            self.assertEqual(set(result["missing_source_observations"]), {"repository_head", "repository_tree"})

    def test_source_divergence_is_explicit_and_old_pass_is_not_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
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
            self.assertTrue(resumed.get_meta("resume_source_observation")["source_diverged"])
            self.assertTrue(all(item["status"] == "pending" for item in resumed.criteria()))

    def test_dispatched_non_idempotent_action_requires_reconciliation_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source_store(root)
            action_id = source.record_external("github_push", "planned", "push:abc", action_class="external_non_idempotent")
            source.record_external("github_push", "dispatched", "push:abc", action_class="external_non_idempotent", action_id=action_id)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            identity_hash = manifest["external_actions"][0]["identity_sha256"]
            plan = build_resume_plan(manifest)
            self.assertTrue(any(item["kind"] == "external_action_state" for item in plan["required_observations"]))

            result = resume_state_manifest(root, manifest, {
                "workspace_presence": True,
                "repository_head": "1" * 40,
                "repository_tree": "2" * 40,
                "external_actions": [],
            })
            self.assertEqual(result["status"], "EXTERNAL_ACTION_UNRESOLVED")
            resumed = StateStore(Path(result["state"]))
            rows = resumed.external_actions()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["state"], "dispatched")
            self.assertEqual(rows[0]["identity"], f"resume-sha256:{identity_hash}")

    def test_reexport_preserves_hashed_external_action_identity_across_resume_epochs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source_store(root)
            action_id = source.record_external("github_push", "planned", "push:abc", action_class="external_non_idempotent")
            source.record_external("github_push", "dispatched", "push:abc", action_class="external_non_idempotent", action_id=action_id)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            identity_hash = manifest["external_actions"][0]["identity_sha256"]
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": True,
                "repository_head": "1" * 40,
                "repository_tree": "2" * 40,
                "external_actions": [],
            })
            resumed = StateStore(Path(result["state"]))
            reexported = build_state_manifest(root, root, resumed, repository="owner/repo")
            self.assertEqual(reexported["external_actions"][0]["identity_sha256"], identity_hash)

    def test_current_terminal_observation_reconciles_prior_dispatched_action(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
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

    def test_v1_manifest_is_migrated_as_historical_recovery_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source_store(root)
            v2 = build_state_manifest(root, root, source, repository="owner/repo")
            v1 = json.loads(json.dumps(v2))
            v1["schema_version"] = 1
            for key in ("requires_validation", "no_validation_reason", "requires_clean_process_exit"):
                v1["task"].pop(key)
            v1["resume"].pop("lineage_policy")
            v1["workspace"].pop("source_commit")
            v1["workspace"].pop("source_tree")
            v1.pop("historical")
            migrated = validate_state_manifest(v1)
            self.assertEqual(migrated["schema_version"], 2)
            self.assertEqual(migrated["historical"]["freshness_on_resume"], "HISTORICAL")

    def test_missing_workspace_never_binds_recovery_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = self._source_store(root)
            manifest = build_state_manifest(root, root, source, repository="owner/repo")
            result = resume_state_manifest(root, manifest, {
                "workspace_presence": False,
                "repository_head": None,
                "repository_tree": None,
                "external_actions": [],
            })
            self.assertEqual(result["status"], "NEEDS_RECONCILIATION")
            self.assertFalse(result["created_task"])


if __name__ == "__main__":
    unittest.main()
