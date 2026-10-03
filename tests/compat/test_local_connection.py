import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.codex_loop_runtime.host_config import host_config_set
from scripts.codex_loop_runtime.local_connection import resolve_execution
from scripts.codex_loop_runtime.routing_state import route_check, route_init, route_transition

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts/codex_loop.py"
CONNECTIONS = [
    {"name": "rdc-mac", "computer": "mac", "connector": "Remote Desktop Commander", "kind": "rdc"},
    {"name": "mac-first", "computer": "mac", "connector": "My Mac", "kind": "mcp", "local_root": "/work"},
    {"name": "mac-second", "computer": "mac", "connector": "Other Mac MCP", "kind": "mcp"},
    {"name": "pc", "computer": "pc", "connector": "My PC", "kind": "mcp"},
]


class LocalConnectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.env = patch.dict(os.environ, {"CODEX_LOOP_HOME": str(self.home)})
        self.env.start()
        self.routing = patch("scripts.codex_loop_runtime.routing_state._routing_root",
                             return_value=Path(self.tmp.name) / "routes")
        self.routing.start()
        host_config_set("execution.connections", CONNECTIONS)

    def tearDown(self):
        self.routing.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_custom_priority_live_availability_and_rdc_fallback(self):
        resolve = lambda available: resolve_execution(target="mac", available_connections=available)["local_connection"]["name"]
        self.assertEqual(resolve(["mac-first", "mac-second", "rdc-mac"]), "mac-first")
        self.assertEqual(resolve(["mac-second", "rdc-mac"]), "mac-second")
        self.assertEqual(resolve(["rdc-mac"]), "rdc-mac")
        with self.assertRaises(RuntimeError):
            resolve_execution(target="mac", available_connections=["pc"])
        with self.assertRaises(RuntimeError):
            resolve_execution(target="mac", available_connections=[])

    def test_manual_choice_is_exact_and_never_falls_back(self):
        result = resolve_execution(connection="mac-second", available_connections=["mac-first", "mac-second"])
        self.assertEqual(result["local_connection"]["name"], "mac-second")
        with self.assertRaises(RuntimeError):
            resolve_execution(connection="mac-second", available_connections=["mac-first", "rdc-mac"])
        with self.assertRaises(ValueError):
            resolve_execution(target="mac", connection="pc")
        with self.assertRaises(ValueError):
            resolve_execution(target="web", connection="mac-first")

    def test_rdc_without_registration_and_unobserved_candidates(self):
        host_config_set("execution.connections", [])
        candidate = resolve_execution(target="local")
        self.assertEqual(candidate["status"], "needs_observation")
        with self.assertRaises(RuntimeError):
            route_init(workspace_target="local")
        web = route_init()
        with self.assertRaises(RuntimeError):
            route_transition(session_id=web["session_id"], workspace_target="local",
                             current_user_selection_observed=True, selection_evidence="Use local")
        actual = resolve_execution(target="local", available_connections=["rdc"])
        self.assertEqual(actual["status"], "resolved")
        self.assertEqual(actual["local_connection"]["kind"], "rdc")

    def test_saved_default_explicit_override_and_pinned_session(self):
        self.assertEqual(resolve_execution()["workspace_mode"], "web")
        host_config_set("execution.default_target", "mac")
        state = route_init(host_surface="chatgpt_web", available_connections=["mac-second"])
        self.assertEqual(state["local_connection"]["name"], "mac-second")
        denied = route_check(action="repository_mutate", session_id=state["session_id"])
        self.assertFalse(denied["allowed"])
        host_config_set("execution.default_target", "web")
        same = route_init(session_id=state["session_id"], host_surface="chatgpt_web")
        self.assertEqual(same["local_connection"], state["local_connection"])
        self.assertEqual(route_init(host_surface="chatgpt_web")["workspace_mode"], "web")
        with self.assertRaises(PermissionError):
            route_transition(session_id=state["session_id"], connection="pc")
        changed = route_transition(session_id=state["session_id"], workspace_target="pc", connection="pc",
                                   available_connections=["pc"], current_user_selection_observed=True,
                                   selection_evidence="Use PC for a new objective")
        self.assertEqual(changed["local_connection"]["computer"], "pc")

    def test_invalid_profile_cannot_silently_route_to_web(self):
        path = self.home / "host.json"
        path.write_text("invalid JSON")
        with self.assertRaises(RuntimeError):
            resolve_execution()

    def test_reject_duplicate_names_secrets_and_unknown_default_computer(self):
        for value in [CONNECTIONS + [CONNECTIONS[0]],
                      [{**CONNECTIONS[1], "api_key": "secret"}],
                      [{**CONNECTIONS[1], "name": "rdc"}],
                      [{**CONNECTIONS[1], "connector": "https://example.com/mcp?key=secret"}]]:
            with self.assertRaises(ValueError):
                host_config_set("execution.connections", value)
        with self.assertRaises(ValueError):
            host_config_set("execution.default_target", "unknown-computer")

    def test_resume_dispatch_pins_custom_connector_and_rejects_rdc(self):
        state = route_init(host_surface="chatgpt_web", workspace_target="mac",
                           available_connections=["mac-first", "rdc-mac"])
        sid = state["session_id"]
        missing = route_check(action="local_lifecycle", session_id=sid)
        self.assertFalse(missing["allowed"])
        custom = route_check(action="local_lifecycle", session_id=sid, dispatch_connector="My Mac")
        self.assertTrue(custom["allowed"])
        self.assertTrue(custom["dispatch_connector_verified"])
        for action in ["local_lifecycle", "local_repository", "repository_observe", "repository_mutate"]:
            wrong = route_check(action=action, session_id=sid,
                                dispatch_connector="Remote Desktop Commander",
                                workspace_granted=True, local_source_mutation_authorized=True)
            self.assertFalse(wrong["allowed"])
            self.assertFalse(wrong["dispatch_connector_verified"])
        initialized = subprocess.run([sys.executable, str(CLI), "route-init", "--workspace-target", "mac",
                                      "--available-connections-json", '["mac-first"]'],
                                     env=os.environ.copy(), capture_output=True, text=True, check=True)
        cli_state = json.loads(initialized.stdout)["data"]
        self.addCleanup(Path(cli_state["state_path"]).unlink)
        cli = subprocess.run([sys.executable, str(CLI), "route-check", "--session-id", cli_state["session_id"],
                              "--action", "local_lifecycle", "--dispatch-connector", "My Mac"],
                             env=os.environ.copy(), capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(cli.stdout)["data"]["allowed"])
        route_transition(session_id=sid, workspace_target="mac", connection="rdc-mac",
                         available_connections=["rdc-mac"], current_user_selection_observed=True,
                         selection_evidence="Use RDC on the same Mac for this continuation")
        self.assertTrue(route_check(action="local_lifecycle", session_id=sid,
                                    dispatch_connector="Remote Desktop Commander")["allowed"])
        self.assertFalse(route_check(action="local_lifecycle", session_id=sid,
                                     dispatch_connector="My Mac")["allowed"])

    def test_cli_reads_private_settings_across_processes_and_override(self):
        host_config_set("execution.default_target", "mac")
        command = [sys.executable, str(CLI), "route-init", "--host-surface", "chatgpt_web",
                   "--workspace-target", "web"]
        proc = subprocess.run(command, cwd=ROOT, env=os.environ.copy(), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        state = json.loads(proc.stdout)["data"]
        Path(state["state_path"]).unlink()
        self.assertEqual(state["workspace_mode"], "web")
        proc = subprocess.run([sys.executable, str(CLI), "execution-resolve", "--connection", "mac-second",
                               "--available-connections-json", '["mac-second"]'],
                              cwd=ROOT, env=os.environ.copy(), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(json.loads(proc.stdout)["data"]["local_connection"]["name"], "mac-second")
        self.assertFalse(self.home.is_relative_to(ROOT))


if __name__ == "__main__":
    unittest.main()
