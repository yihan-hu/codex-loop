import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from scripts.codex_loop_runtime.release_lineage import capture_workspace_binding
from scripts.codex_loop_runtime.routing_state import route_init, record_permission_observation
from scripts.codex_loop_runtime.state import StateStore
from scripts.codex_loop_runtime.web_publish import (
    begin_web_publish_continuation,
    build_web_publish_bundle,
    publish_continuation_state,
    web_publish_plan,
)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()


def init_repo(root, *, with_fast_workflow=True):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "tracked.txt").write_text("x\n")
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "workspace-import.yml").write_text("name: Standard Import\n")
    if with_fast_workflow:
        (workflow_dir / "workspace-import-fast.yml").write_text("name: Fast Import\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    return git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")


def ready_store(root):
    store = StateStore(root.parent / (root.name + "-state.sqlite3"))
    store.configure_task(root.name, "publish", ["publish"], requires_validation=False, no_validation_reason="test fixture uses no executable workload")
    store.set_meta("workspace_binding", capture_workspace_binding(root))
    store.set_meta("changes_reviewed_generation", 0)
    return store


def scopes():
    return {"github_push": "repo:owner/repo", "google_drive_write": "drive:staging"}


class FastPublishTests(unittest.TestCase):
    def route(self):
        return route_init(session_id="fast-" + uuid.uuid4().hex, host_surface="chatgpt_web")

    def cleanup(self, r):
        p = Path(r["state_path"])
        for x in (p, p.with_suffix(".capabilities.json")):
            try:
                x.unlink()
            except FileNotFoundError:
                pass

    def caps(self, sid):
        for capability, scope in scopes().items():
            record_permission_observation(session_id=sid, capability=capability, scope=scope, evidence="live probe")

    def test_web_publish_rejects_disconnected_bound_history_before_transport(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            try:
                subprocess.run(["git", "checkout", "-q", "--orphan", "disconnected"], cwd=root, check=True)
                subprocess.run(["git", "rm", "-q", "-rf", "."], cwd=root, check=True)
                (root / "tracked.txt").write_text("replacement\n")
                workflow_dir = root / ".github" / "workflows"
                workflow_dir.mkdir(parents=True, exist_ok=True)
                (workflow_dir / "workspace-import.yml").write_text("name: Standard Import\n")
                (workflow_dir / "workspace-import-fast.yml").write_text("name: Fast Import\n")
                subprocess.run(["git", "add", "."], cwd=root, check=True)
                subprocess.run(["git", "commit", "-qm", "disconnected root"], cwd=root, check=True)
                with self.assertRaisesRegex(RuntimeError, "history no longer descends from bound base commit"):
                    web_publish_plan(
                        root, store, session_id=route["session_id"], repository="owner/repo",
                        branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(),
                    )
            finally:
                self.cleanup(route)

    def test_fast_publish_reuses_fresh_observations(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            head, _tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            self.caps(route["session_id"])
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree="0" * 40, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["mode"], "FAST_PUBLISH")
                self.assertTrue(plan["validation_reused"])
                self.assertEqual(len(plan["capability_observations_reused"]), 2)
            finally:
                self.cleanup(route)

    def test_fast_publish_treats_actions_as_post_trigger_runtime_proof(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
            store = ready_store(root)
            route = self.route(); self.caps(route["session_id"])
            try:
                plan = web_publish_plan(
                    root, store, session_id=route["session_id"], repository="owner/repo",
                    branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(),
                )
                self.assertEqual(plan["mode"], "FAST_PUBLISH")
                self.assertEqual(plan["host_permission_capabilities_required"], ["github_push", "google_drive_write"])
                self.assertNotIn("github_actions", plan["capability_observations"])
                self.assertTrue(plan["github_actions_runtime_proof"]["required"])
                self.assertEqual(plan["github_actions_runtime_proof"]["mode"], "matching_push_triggered_import_run")
            finally:
                self.cleanup(route)

    def test_workflow_delta_requires_connector_control_plane_refresh_before_fast_transport(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root)
            workflow = root / ".github" / "workflows" / "workspace-import.yml"
            workflow.write_text("name: Standard Import\n# refreshed\n")
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "workflow and source"], cwd=root, check=True)
            store = ready_store(root)
            route = self.route(); self.caps(route["session_id"])
            try:
                plan = web_publish_plan(
                    root, store, session_id=route["session_id"], repository="owner/repo",
                    branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(),
                )
                self.assertEqual(plan["mode"], "FAST_PUBLISH_CONTROL_PLANE_REFRESH_REQUIRED")
                self.assertTrue(plan["control_plane_refresh_required"])
                self.assertTrue(plan["control_plane_reacquisition_required"])
                self.assertEqual(
                    plan["control_plane_workflow_updates"],
                    [{"path": ".github/workflows/workspace-import.yml", "action": "update"}],
                )
                self.assertEqual(
                    plan["control_plane_refresh_reason"],
                    "github_actions_token_cannot_publish_workflow_file_changes",
                )
                self.assertIsNone(plan["workflow_path"])
                self.assertIsNone(plan["request_directory"])
                self.assertIsNone(plan["bundle_action"])
                self.assertIn("GitHub Connector", plan["next"])
                self.assertIn("Workspace Download", plan["next"])
            finally:
                self.cleanup(route)

    def test_publish_only_continuation_freezes_fresh_evidence_for_fast_publish(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
            store = ready_store(root)
            route = self.route(); self.caps(route["session_id"])
            try:
                continuation = begin_web_publish_continuation(
                    root, store, repository="owner/repo", branch="main"
                )
                self.assertTrue(continuation["active"])
                self.assertTrue(continuation["validation_reused"])
                self.assertTrue(continuation["review_reused"])
                self.assertTrue(continuation["revalidation_forbidden"])
                self.assertFalse(continuation["semantic_plan_change"])
                self.assertTrue(publish_continuation_state(store)["active"])
                plan = web_publish_plan(
                    root, store, session_id=route["session_id"], repository="owner/repo",
                    branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(),
                )
                self.assertEqual(plan["mode"], "FAST_PUBLISH")
                self.assertTrue(plan["publish_continuation"]["active"])
                self.assertTrue(plan["redundant_validation_forbidden"])
                self.assertEqual(plan["fast_path_budget"]["validation_commands"], 0)
            finally:
                self.cleanup(route)

    def test_fast_publish_is_the_function_default(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
            store = ready_store(root)
            route = self.route(); self.caps(route["session_id"])
            try:
                plan = web_publish_plan(
                    root, store, session_id=route["session_id"], repository="owner/repo",
                    branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(),
                )
                self.assertEqual(plan["mode"], "FAST_PUBLISH")
                self.assertEqual(plan["planner_default"], "FAST_PUBLISH")
                self.assertFalse(plan["standard_publish_explicitly_selected"])
                self.assertEqual(plan["workflow_path"], ".github/workflows/workspace-import-fast.yml")
            finally:
                self.cleanup(route)

    def test_dirty_workspace_fails_closed_for_direct_fast_publish(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            self.caps(route["session_id"])
            (root / "tracked.txt").write_text("dirty\n")
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree=tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["mode"], "FAIL_CLOSED")
                self.assertTrue(plan["fail_closed"])
                self.assertTrue(plan["design_repair_required"])
                self.assertTrue(plan["fallback_allowed"])
                self.assertTrue(plan["fallback_requires_explicit_user_selection"])
                self.assertEqual(plan["recommended_recovery"], "standard_web")
                self.assertEqual({x["id"] for x in plan["fallback_options"]}, {"retry_fast", "standard_web", "local_handoff"})
                self.assertIn("workspace_not_clean", plan["surprise_reasons"])
                self.assertIsNone(plan["workflow_path"])
                self.assertIsNone(plan["request_directory"])
                self.assertIn("present the modeled recovery options", plan["next"])
            finally:
                self.cleanup(route)

    def test_fast_publish_stale_gate_refreshes_only_missing_fast_gates(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
            store = ready_store(root)
            route = self.route()
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes())
                self.assertEqual(plan["mode"], "FAST_PUBLISH_REFRESH_REQUIRED")
                self.assertFalse(plan["fail_closed"])
                self.assertFalse(plan["design_repair_required"])
                self.assertFalse(plan["fallback_allowed"])
                self.assertEqual(plan["recommended_recovery"], "retry_fast")
                self.assertEqual(plan["planner_default"], "FAST_PUBLISH")
                self.assertTrue(plan["fast_path_refresh_required"])
                self.assertEqual(plan["surprise_reasons"], [])
                self.assertEqual(
                    plan["required_refresh_actions"],
                    [
                        "refresh_capability:github_push",
                        "refresh_capability:google_drive_write",
                    ],
                )
                self.assertIn("workspace-import.yml", plan["forbidden_before_fast_retry"])
                self.assertIsNone(plan["workflow_path"])
                self.assertIn("refresh only required_refresh_actions", plan["next"])
            finally:
                self.cleanup(route)

    def test_explicit_standard_publish_remains_available_but_is_not_fast_fallback(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree=tree, capability_scopes=scopes(), verified_tree_fast_path=False)
                self.assertEqual(plan["mode"], "ALREADY_PUBLISHED")
                # Change HEAD so transport is needed and prove standard mode is an explicit selection, not a fast fallback.
                (root / "second.txt").write_text("second\n")
                subprocess.run(["git", "add", "."], cwd=root, check=True)
                subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
                store = ready_store(root)
                standard = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree=tree, capability_scopes=scopes(), verified_tree_fast_path=False)
                self.assertEqual(standard["mode"], "FULL_VERIFIED_PUBLISH")
                self.assertFalse(standard["fallback_allowed"])
                self.assertTrue(standard["standard_publish_explicitly_selected"])
                self.assertEqual(standard["workflow_path"], ".github/workflows/workspace-import.yml")
            finally:
                self.cleanup(route)

    def test_bundle_receipt_reuse_is_exact(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
            head, tree = git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")
            store = ready_store(root)
            route = self.route()
            self.caps(route["session_id"])
            bundle = root.parent / (root.name + "-fast-publish.bundle")
            try:
                receipt = build_web_publish_bundle(root, store, output=bundle, prerequisite_commit=base)
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["bundle_action"], "reuse")
                self.assertEqual(plan["bundle_strategy"], "reuse_exact_bundle")
                self.assertEqual(plan["bundle_build_prerequisite_commit"], base)
                self.assertEqual(plan["bundle"]["sha256"], receipt["sha256"])
                self.assertEqual(plan["bundle"]["source_commit"], head)
                self.assertEqual(plan["bundle"]["source_tree"], tree)
            finally:
                self.cleanup(route)
                bundle.unlink(missing_ok=True)

    def test_bundle_can_use_exact_ancestor_as_prerequisite(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base_commit, _base_tree = init_repo(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
            head = git(root, "rev-parse", "HEAD")
            store = ready_store(root)
            bundle = root.parent / (root.name + "-thin.bundle")
            try:
                receipt = build_web_publish_bundle(root, store, output=bundle, prerequisite_commit=base_commit)
                self.assertEqual(receipt["source_commit"], head)
                self.assertEqual(receipt["prerequisite_commit"], base_commit)
                verify = subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(verify.returncode, 0, verify.stderr)
            finally:
                bundle.unlink(missing_ok=True)

    def test_fast_plan_selects_one_thin_bundle_directly(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
            store = ready_store(root)
            route = self.route(); self.caps(route["session_id"])
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["mode"], "FAST_PUBLISH")
                self.assertEqual(plan["bundle_strategy"], "thin_from_remote_head")
                self.assertEqual(plan["bundle_build_prerequisite_commit"], base)
                self.assertTrue(plan["remote_head_is_local_ancestor"])
                self.assertEqual(plan["fast_path_budget"]["permission_smoke_probes"], 0)
                self.assertEqual(plan["fast_path_budget"]["validation_commands"], 0)
                self.assertEqual(plan["fast_path_budget"]["change_review_repeats"], 0)
                self.assertEqual(plan["fast_path_budget"]["full_bundle_attempts"], 0)
                self.assertEqual(plan["fast_path_budget"]["production_packaging_steps"], 0)
                self.assertEqual(plan["fast_path_budget"]["bundle_build_attempts"], 1)
                self.assertEqual(plan["fast_path_budget"]["workflow_artifact_uploads"], 1)
                self.assertEqual(plan["workflow_path"], ".github/workflows/workspace-import-fast.yml")
                self.assertEqual(plan["request_directory"], ".github/fast-import-requests")
                self.assertEqual(plan["receipt_mode"], "structured_log_with_published_source_artifact")
            finally:
                self.cleanup(route)


    def test_missing_fast_workflow_can_be_bootstrapped_by_control_plane_refresh(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root, with_fast_workflow=False)
            workflow = root / ".github" / "workflows" / "workspace-import-fast.yml"
            workflow.parent.mkdir(parents=True, exist_ok=True)
            workflow.write_text("name: Fast Import\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "add fast importer"], cwd=root, check=True)
            store = ready_store(root)
            route = self.route(); self.caps(route["session_id"])
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["mode"], "FAST_PUBLISH_CONTROL_PLANE_REFRESH_REQUIRED")
                self.assertFalse(plan["remote_has_fast_import_workflow"])
                self.assertTrue(plan["local_has_fast_import_workflow"])
                self.assertEqual(
                    plan["control_plane_workflow_updates"],
                    [{"path": ".github/workflows/workspace-import-fast.yml", "action": "create"}],
                )
                self.assertIsNone(plan["bundle_strategy"])
                self.assertIsNone(plan["workflow_path"])
                self.assertIsNone(plan["request_directory"])
            finally:
                self.cleanup(route)

    def test_missing_fast_workflow_without_local_replacement_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base, base_tree = init_repo(root, with_fast_workflow=False)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "source only"], cwd=root, check=True)
            store = ready_store(root)
            route = self.route(); self.caps(route["session_id"])
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=base, remote_tree=base_tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["mode"], "FAIL_CLOSED")
                self.assertIn("fast_import_workflow_not_in_remote_base", plan["surprise_reasons"])
            finally:
                self.cleanup(route)

    def test_only_exact_remote_commit_and_tree_short_circuit_transport(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            self.caps(route["session_id"])
            try:
                exact = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree=tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertTrue(exact["already_published_exactly"])
                self.assertIn("skip transport", exact["next"])
                tree_only = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head="f" * 40, remote_tree=tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertFalse(tree_only["already_published_exactly"])
            finally:
                self.cleanup(route)


if __name__ == "__main__":
    unittest.main()
