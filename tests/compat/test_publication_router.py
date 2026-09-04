import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from scripts.codex_loop_runtime.publication_router import publication_enter
from scripts.codex_loop_runtime.release_lineage import capture_workspace_binding
from scripts.codex_loop_runtime.routing_state import (
    record_permission_observation,
    route_check,
    route_init,
    route_show,
    route_transition,
)
from scripts.codex_loop_runtime.state import StateStore
from scripts.codex_loop_runtime.web_publish import web_local_sync_plan


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, check=True
    ).stdout.strip()


def init_repo(root: Path) -> tuple[str, str, str, str]:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "tracked.txt").write_text("base\n")
    workflow_dir = root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow_dir / "workspace-import.yml").write_text("name: Standard Import\n")
    (workflow_dir / "workspace-import-fast.yml").write_text("name: Fast Import\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    base = git(root, "rev-parse", "HEAD")
    base_tree = git(root, "rev-parse", "HEAD^{tree}")
    (root / "tracked.txt").write_text("changed\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=root, check=True)
    head = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    return base, base_tree, head, tree


def ready_store(root: Path) -> StateStore:
    store = StateStore(root.parent / (root.name + "-router-state.sqlite3"))
    store.configure_task(
        root.name,
        "publication router",
        ["route publication"],
        requires_validation=False,
        no_validation_reason="test fixture exercises deterministic publication routing",
    )
    store.set_meta("workspace_binding", capture_workspace_binding(root))
    store.set_meta("changes_reviewed_generation", 0)
    return store


def scopes() -> dict[str, str]:
    return {
        "github_push": "repo:owner/repo",
        "google_drive_write": "drive:staging",
    }


class PublicationRouterTests(unittest.TestCase):
    def route(self):
        return route_init(session_id="router-" + uuid.uuid4().hex, host_surface="chatgpt_web")

    def cleanup_route(self, state):
        p = Path(state["state_path"])
        for path in (p, p.with_suffix(".capabilities.json")):
            path.unlink(missing_ok=True)

    def record_web_caps(self, sid: str):
        for capability, scope in scopes().items():
            record_permission_observation(
                session_id=sid,
                capability=capability,
                scope=scope,
                evidence="live test probe",
            )

    def test_web_publish_enter_uses_workspace_router_and_exact_identity_protocol(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, base_tree, head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            self.record_web_caps(route["session_id"])
            try:
                result = publication_enter(
                    root,
                    store,
                    session_id=route["session_id"],
                    repository="owner/repo",
                    branch="main",
                    remote_head=base,
                    remote_tree=base_tree,
                    capability_scopes=scopes(),
                    controller_abi=1,
                )
                self.assertEqual(result["entrypoint"], "publish-enter")
                self.assertEqual(result["router_abi"], 1)
                self.assertEqual(result["workspace_mode"], "web")
                self.assertEqual(result["publication_protocol"], {"name": "web_exact_git_identity", "version": 2})
                self.assertEqual(result["workspace_protocol_reference"], "references/web-mode-publish.md")
                self.assertTrue(result["protocol_reference_required_before_transport"])
                self.assertTrue(result["controller_contract"]["workspace_protocol_reference_authoritative"])
                self.assertTrue(result["controller_contract"]["installed_transport_instructions_must_not_override"])
                self.assertEqual(result["status"], "FAST_PUBLISH")
                self.assertEqual(result["planner_result"]["source_commit"], head)
                self.assertEqual(result["planner_result"]["source_tree"], tree)
                self.assertFalse(result["planner_result"]["remote_source_object_presence_required"])
                self.assertFalse(result["planner_result"]["remote_source_object_absence_is_blocker"])
                self.assertTrue(result["controller_contract"]["unmodeled_transport_forbidden"])
            finally:
                self.cleanup_route(route)

    def test_unsupported_controller_abi_is_deterministic_blocker(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, base_tree, _head, _tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            try:
                result = publication_enter(
                    root,
                    store,
                    session_id=route["session_id"],
                    repository="owner/repo",
                    branch="main",
                    remote_head=base,
                    remote_tree=base_tree,
                    capability_scopes={},
                    controller_abi=99,
                )
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["code"], "PUBLICATION_ROUTER_ABI_UNSUPPORTED")
                self.assertIsNone(result["planner_result"])
                self.assertIn("do not inspect GitHub object presence", result["next_action"])
            finally:
                self.cleanup_route(route)

    def test_local_publish_enter_routes_only_to_native_git(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, base_tree, head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            try:
                route_transition(
                    session_id=route["session_id"],
                    workspace_mode="local",
                    selection_evidence="user explicitly selected local repository development",
                    current_user_selection_observed=True,
                )
                result = publication_enter(
                    root,
                    store,
                    session_id=route["session_id"],
                    repository="owner/repo",
                    branch="main",
                    remote_head=base,
                    remote_tree=base_tree,
                    capability_scopes={},
                    controller_abi=1,
                    workspace_granted=True,
                )
                self.assertEqual(result["workspace_mode"], "local")
                self.assertEqual(result["publication_protocol"], {"name": "local_native_git", "version": 1})
                self.assertEqual(result["workspace_protocol_reference"], "references/verified-native-git.md")
                self.assertTrue(result["protocol_reference_required_before_transport"])
                self.assertEqual(result["planner_result"]["target"], {"commit": head, "tree": tree})
                self.assertEqual(result["planner_result"]["transport_order"], ["git"])
                self.assertEqual(result["planner_result"]["host_executor"], "remote_desktop_commander")
                self.assertIsNone(result["planner_result"]["fallback_transport"])
            finally:
                self.cleanup_route(route)

    def test_rdc_transfer_is_downstream_only_and_does_not_switch_web_mode(self):
        route = self.route()
        try:
            sid = route["session_id"]
            blocked = route_check(action="rdc_transfer", session_id=sid)
            self.assertFalse(blocked["allowed"])
            self.assertIn("current_conversation_workspace_grant", blocked["requirements"])
            allowed = route_check(
                action="rdc_transfer",
                session_id=sid,
                workspace_granted=True,
                local_computer_authorized=True,
            )
            self.assertTrue(allowed["allowed"])
            self.assertEqual(allowed["transfer_role"], "downstream_binary_destination_only")
            self.assertTrue(allowed["workspace_authority_unchanged"])
            self.assertEqual(route_show(session_id=sid)["workspace_mode"], "web")
            self.assertFalse(route_check(action="rdc_repository", session_id=sid)["allowed"])
        finally:
            self.cleanup_route(route)

    def test_web_local_sync_plan_has_only_drive_then_rdc_transport(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _base, _base_tree, head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            try:
                result = web_local_sync_plan(
                    root,
                    store,
                    session_id=route["session_id"],
                    destination_path="/Users/test/PiWork/codex-loop.bundle",
                    workspace_granted=True,
                    local_computer_authorized=True,
                )
                self.assertEqual(result["mode"], "WEB_LOCAL_SYNC_READY")
                self.assertEqual(result["source_commit"], head)
                self.assertEqual(result["source_tree"], tree)
                self.assertEqual(result["transport"]["id"], "google_drive_then_rdc_download")
                self.assertTrue(result["transport"]["fixed"])
                self.assertEqual(result["bundle_action"], "build_self_contained")
                self.assertIn("github_actions_artifact", result["forbidden_fallbacks"])
                self.assertIn("model_carried_base64_or_chunk_relay", result["forbidden_fallbacks"])
                self.assertTrue(result["workspace_authority_unchanged"])
                self.assertEqual(route_show(session_id=route["session_id"])["workspace_mode"], "web")
            finally:
                self.cleanup_route(route)

    def test_cli_help_exposes_stable_router_and_fixed_web_local_sync_planner(self):
        root = Path(__file__).resolve().parents[2]
        proc = subprocess.run(
            ["python3", str(root / "scripts" / "codex_loop.py"), "--help"],
            cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        self.assertIn("publish-enter", proc.stdout)
        self.assertIn("web-local-sync-plan", proc.stdout)

    def test_publish_enter_cli_requires_explicit_controller_abi(self):
        root = Path(__file__).resolve().parents[2]
        proc = subprocess.run(
            [
                "python3", str(root / "scripts" / "codex_loop.py"), "publish-enter",
                "--session-id", "r_test", "--repository", "owner/repo", "--branch", "main",
                "--remote-head", "1" * 40, "--remote-tree", "2" * 40,
            ],
            cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--controller-abi", proc.stderr)



if __name__ == "__main__":
    unittest.main()
