import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.codex_loop_runtime.git_auth import local_git_auth_command
from scripts.codex_loop_runtime.host_config import validate_environment_locations


class GitAuthTests(unittest.TestCase):
    def test_host_profile_provider_is_bounded(self):
        for provider in ("osxkeychain", "windows_gcm", "gh_cli"):
            self.assertEqual(validate_environment_locations({"git_auth": provider})["git_auth"], provider)
        self.assertIsNone(validate_environment_locations({})["git_auth"])
        for invalid in ("!shell", "manager", "", ["osxkeychain"], {"token": "no"}):
            with self.assertRaises(ValueError):
                validate_environment_locations({"git_auth": invalid})

    def test_local_auth_uses_profile_without_helper_probe(self):
        from scripts.codex_loop_runtime.git_auth import local_git_auth_command
        base = ["git", "push", "--porcelain", "origin", "main:main"]
        for provider, helper in (("gh_cli", "!gh auth git-credential"),
                                 ("osxkeychain", "osxkeychain"), ("windows_gcm", "manager")):
            route = {"local_connection": {"locations": {"git_auth": provider}}}
            self.assertEqual(local_git_auth_command(route, base),
                             ["git", "-c", "credential.helper=", "-c", f"credential.helper={helper}", *base[1:]])
        self.assertEqual(local_git_auth_command({"local_connection": {"locations": {"git_auth": None}}}, base), base)

    def test_profile_round_trip_preserves_two_host_providers(self):
        from scripts.codex_loop_runtime.host_config import host_config_set, host_config_show
        from scripts.codex_loop_runtime.host_profile_sync import export_profile, import_profile
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "first"
            second = Path(td) / "second"
            envelope = Path(td) / "profile.json"
            providers = {"mac": {"git_auth": "gh_cli"}, "wsl": {"git_auth": "windows_gcm"}}
            with patch.dict(os.environ, {"CODEX_LOOP_PROFILE_HOME": str(first)}):
                host_config_set("workspace.environments", providers)
                export_profile(drive_root_id="0AexampleRoot", output=str(envelope))
            with patch.dict(os.environ, {"CODEX_LOOP_PROFILE_HOME": str(second)}):
                import_profile(drive_root_id="0AexampleRoot", input_path=str(envelope))
                actual = host_config_show()["workspace"]["environments"]
                self.assertEqual(actual["mac"]["git_auth"], "gh_cli")
                self.assertEqual(actual["wsl"]["git_auth"], "windows_gcm")

    def test_publication_entry_applies_saved_source_without_preflight(self):
        import uuid
        from scripts.codex_loop_runtime.publication_router import publication_enter
        from scripts.codex_loop_runtime.routing_state import route_init
        from test_publication_router import init_repo, ready_store

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, base_tree, head, tree = init_repo(root)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/repo.git"], cwd=root, check=True)
            store = ready_store(root)
            sid = "auth-preflight-" + uuid.uuid4().hex
            route = route_init(
                session_id=sid, host_surface="chatgpt_web",
                resolved_execution={
                    "workspace_mode": "local", "computer": "mac", "basis": "explicit_user_target",
                    "status": "resolved", "local_connection": {
                        "name": "my-mac", "computer": "mac", "connector": "My Mac",
                        "kind": "mcp", "locations": validate_environment_locations({"git_auth": "osxkeychain"}),
                    },
                },
            )
            try:
                def enter():
                    return publication_enter(
                        root, store, session_id=sid, repository="example/repo",
                        branch="main", remote_head=base, remote_tree=base_tree,
                        capability_scopes={}, workspace_granted=True,
                    )
                with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}):
                    result = enter()
                    self.assertEqual(result["status"], "LOCAL_PUBLISH_READY")
                    self.assertEqual(result["git_auth"], "osxkeychain")
                    self.assertIsNone(result.get("git_auth_preflight"))
                    self.assertEqual(result["planner_result"]["git"]["argv"][:5],
                                     ["git", "-c", "credential.helper=", "-c", "credential.helper=osxkeychain"])
                    self.assertEqual(result["planner_result"]["git"]["env"]["GIT_TERMINAL_PROMPT"], "0")
            finally:
                Path(route["state_path"]).unlink(missing_ok=True)
                Path(route["state_path"]).with_suffix(".capabilities.json").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
