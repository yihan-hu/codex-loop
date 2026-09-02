import os
import stat
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from scripts.codex_loop_runtime.routing_state import (
    route_check,
    route_init,
    route_show,
    route_transition,
)

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


class RoutingStateTests(unittest.TestCase):
    def sid(self) -> str:
        return f"routing-state-test-{uuid.uuid4().hex}"

    def cleanup(self, state: dict) -> None:
        path = Path(state["state_path"])
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def test_new_chatgpt_web_session_is_file_backed_and_defaults_web(self):
        state = route_init(session_id=self.sid(), host_surface="chatgpt_web")
        try:
            self.assertEqual(state["workspace_mode"], "web")
            self.assertEqual(state["interaction_target"], "none")
            self.assertIsNone(state["deployment_target"])
            path = Path(state["state_path"])
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_relative_to(ROOT))
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        finally:
            self.cleanup(state)

    def test_bare_skill_install_on_chatgpt_web_never_auto_selects_local_codex(self):
        state = route_init(session_id=self.sid(), host_surface="chatgpt_web")
        try:
            generic = route_check(action="skill_install", session_id=state["session_id"])
            self.assertTrue(generic["allowed"])
            self.assertEqual(generic["effective_deployment_target"], "chatgpt_web_skill")
            self.assertEqual(generic["deployment_source"], "host_surface_native_default")
            self.assertFalse(generic["local_codex_auto_selected"])
            local = route_check(action="local_skill_install", session_id=state["session_id"])
            self.assertFalse(local["allowed"])
            self.assertEqual(local["effective_deployment_target"], "chatgpt_web_skill")
        finally:
            self.cleanup(state)

    def test_workspace_and_deployment_axes_do_not_redirect_each_other(self):
        state = route_init(session_id=self.sid(), host_surface="chatgpt_web")
        sid = state["session_id"]
        try:
            route_transition(
                session_id=sid,
                workspace_mode="local",
                selection_evidence="user explicitly selected the local repository baseline",
            )
            generic = route_check(action="skill_install", session_id=sid)
            self.assertTrue(generic["allowed"])
            self.assertEqual(generic["effective_deployment_target"], "chatgpt_web_skill")
            self.assertFalse(route_check(action="local_skill_install", session_id=sid)["allowed"])

            route_transition(
                session_id=sid,
                workspace_mode="web",
                deployment_target="local_codex_skill",
                selection_evidence="user explicitly selected local Codex as the deployment target",
            )
            observed = route_check(action="repository_observe", session_id=sid)
            self.assertTrue(observed["allowed"])
            self.assertEqual(observed["effective_workspace"], "web")
            self.assertFalse(route_check(action="rdc_repository", session_id=sid)["allowed"])
        finally:
            self.cleanup(state)

    def test_unknown_host_generic_install_fails_closed(self):
        state = route_init(session_id=self.sid(), host_surface="unknown")
        try:
            result = route_check(action="skill_install", session_id=state["session_id"])
            self.assertFalse(result["allowed"])
            self.assertIsNone(result["effective_deployment_target"])
            self.assertIn("host_surface_or_explicit_deployment_target", result["requirements"])
        finally:
            self.cleanup(state)

    def test_local_deployment_target_requires_explicit_selection_and_current_task_install_authorization(self):
        state = route_init(session_id=self.sid(), host_surface="chatgpt_web")
        sid = state["session_id"]
        try:
            with self.assertRaises(PermissionError):
                route_transition(session_id=sid, deployment_target="local_codex_skill")
            changed = route_transition(
                session_id=sid,
                deployment_target="local_codex_skill",
                selection_evidence="user explicitly requested local Codex installation",
            )
            self.assertEqual(changed["deployment_basis"], "explicit_user_target")
            blocked = route_check(action="local_skill_install", session_id=sid)
            self.assertFalse(blocked["allowed"])
            self.assertIn("current_task_explicit_local_skill_install_authorization", blocked["requirements"])
            allowed = route_check(action="local_skill_install", session_id=sid, local_install_authorized=True)
            self.assertTrue(allowed["allowed"])
            self.assertFalse(allowed["local_codex_auto_selected"])
        finally:
            self.cleanup(state)

    def test_rdc_repository_route_fails_closed_until_local_mode_and_grant(self):
        state = route_init(session_id=self.sid(), host_surface="chatgpt_web")
        sid = state["session_id"]
        try:
            blocked = route_check(action="rdc_repository", session_id=sid)
            self.assertFalse(blocked["allowed"])
            self.assertEqual(blocked["effective_workspace"], "web")
            with self.assertRaises(PermissionError):
                route_transition(session_id=sid, workspace_mode="local")
            route_transition(
                session_id=sid,
                workspace_mode="local",
                selection_evidence="user explicitly selected the local repository baseline",
            )
            needs_grant = route_check(action="rdc_repository", session_id=sid)
            self.assertFalse(needs_grant["allowed"])
            self.assertIn("current_conversation_workspace_grant", needs_grant["requirements"])
            allowed = route_check(action="rdc_repository", session_id=sid, workspace_granted=True)
            self.assertTrue(allowed["allowed"])
            self.assertEqual(allowed["effective_workspace"], "local")
        finally:
            self.cleanup(state)

    def test_host_surface_is_immutable_within_session(self):
        state = route_init(session_id=self.sid(), host_surface="chatgpt_web")
        try:
            with self.assertRaises(ValueError):
                route_init(session_id=state["session_id"], host_surface="codex_local")
            shown = route_show(session_id=state["session_id"])
            self.assertEqual(shown["host_surface"], "chatgpt_web")
        finally:
            self.cleanup(state)

    def test_cli_exposes_routing_primitives(self):
        sid = self.sid()
        proc = subprocess.run(
            [sys.executable, str(CLI), "route-init", "--session-id", sid, "--host-surface", "chatgpt_web"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        import json
        state = json.loads(proc.stdout)["data"]
        try:
            checked = subprocess.run(
                [sys.executable, str(CLI), "route-check", "--session-id", sid, "--action", "skill_install"],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            payload = json.loads(checked.stdout)["data"]
            self.assertEqual(payload["effective_deployment_target"], "chatgpt_web_skill")
        finally:
            self.cleanup(state)


if __name__ == "__main__":
    unittest.main()
