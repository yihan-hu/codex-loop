import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InteractionRoutingContractTests(unittest.TestCase):
    def test_rdc_does_not_select_local_workspace_mode(self):
        skill = (ROOT / "SKILL.md").read_text()
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        self.assertIn("does **not** enter Local mode", skill)
        self.assertIn("workspace_mode=web", routing)
        self.assertIn("interaction_target=local_chrome", routing)
        self.assertIn("must not inspect or mutate a local repository", routing)

    def test_local_chrome_requires_supported_browser_executor(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        recovery = (ROOT / "references" / "browser-control-recovery.md").read_text()
        self.assertIn("Keep ChatGPT as the reasoning/orchestration authority", routing)
        self.assertIn("supported host-exposed Chrome/Computer Use executor", routing)
        self.assertIn("SESSION_BROWSER_CAPABILITY_MISSING", routing)
        self.assertIn("RDC -> AppleScript", recovery)
        self.assertIn("not a Browser Control executor", recovery)
        self.assertNotIn("RDC-backed structured Chrome automation on macOS", routing)

    def test_capability_preflight_batches_predictable_permissions(self):
        skill = (ROOT / "SKILL.md").read_text()
        preflight = (ROOT / "references" / "capability-preflight.md").read_text()
        self.assertIn("Capability and permission preflight", skill)
        self.assertIn("Batch missing connection", preflight)
        self.assertIn("Google Drive", preflight)
        self.assertIn("local_chrome", preflight)
        self.assertIn("cannot bypass host-enforced per-action confirmation", preflight)

    def test_host_local_root_default_is_non_sensitive_and_does_not_select_local_mode(self):
        setup = (ROOT / "references" / "local-mode-setup.md").read_text()
        readme = (ROOT / "README.md").read_text()
        self.assertIn("~/.codex-loop/host.json", setup)
        self.assertIn('"default_local_workspace": "piwork"', setup)
        self.assertIn("historical `default_local_root` remain compatibility/migration inputs only", setup)
        self.assertIn("neither selects Local mode", setup)
        self.assertIn("New conversations still start in Web mode", readme)
        self.assertIn("Git/OAuth tokens", setup)

    def test_rdc_boundary_has_separate_interaction_only_contract(self):
        boundary = (ROOT / "references" / "remote-desktop-boundary.md").read_text()
        self.assertIn("Interaction-only RDC boundary", boundary)
        self.assertIn("workspace_mode=web", boundary)
        self.assertIn("must not touch the local checkout", boundary)
        self.assertIn("never change them silently", boundary)

    def test_local_source_mutation_requires_explicit_current_task_authorization(self):
        skill = (ROOT / "SKILL.md").read_text()
        setup = (ROOT / "references" / "local-mode-setup.md").read_text()
        boundary = (ROOT / "references" / "remote-desktop-boundary.md").read_text()
        preflight = (ROOT / "references" / "capability-preflight.md").read_text()
        readme = (ROOT / "README.md").read_text()
        self.assertIn("Explicit local-source-mutation authorization gate", skill)
        self.assertIn("Local mode is routing state, not write consent", skill)
        self.assertIn("does **not** persist permission to mutate local source", setup)
        self.assertIn("does not authorize source mutation", preflight)
        self.assertIn("generic `push` wording", boundary)
        self.assertIn("does not carry forward permission to modify local source", readme)

    def test_computer_use_requires_explicit_current_task_authorization(self):
        skill = (ROOT / "SKILL.md").read_text()
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        preflight = (ROOT / "references" / "capability-preflight.md").read_text()
        self.assertIn("Explicit computer-use authorization gate", skill)
        self.assertIn("explicitly authorized computer use for the current task", routing)
        self.assertIn("Do **not** infer authorization", routing)
        self.assertIn("do not inspect tabs/windows", preflight)

    def test_any_workspace_resident_skill_or_package_does_not_imply_browser_ui_install(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        readme = (ROOT / "README.md").read_text()
        self.assertIn("For **any** Skill or Skill installation package", skill)
        self.assertIn("Workspace-resident Skill/package update", deployment)
        self.assertIn("For any Skill or Skill installation package", deployment)
        self.assertIn("all Skills and Skill installation packages", readme)
        self.assertIn("never treat deployment intent as permission to automate browser clicks", readme)

    def test_browser_recovery_separates_host_and_session_health(self):
        recovery = (ROOT / "references" / "browser-control-recovery.md").read_text()
        preflight = (ROOT / "references" / "capability-preflight.md").read_text()
        skill = (ROOT / "SKILL.md").read_text()
        self.assertIn("browser_host_health", recovery)
        self.assertIn("browser_session_health", recovery)
        self.assertIn("NATIVE_HOST_MISSING", recovery)
        self.assertIn("BRIDGE_HEALTHY", recovery)
        self.assertIn("SESSION_BROWSER_CAPABILITY_MISSING", preflight)
        self.assertIn("Browser Control evidence gate", skill)

    def test_browser_recovery_uses_supported_product_path_not_manual_manifest(self):
        recovery = (ROOT / "references" / "browser-control-recovery.md").read_text()
        boundary = (ROOT / "references" / "remote-desktop-boundary.md").read_text()
        completion = (ROOT / "references" / "completion-criteria.md").read_text()
        self.assertIn("Settings", recovery)
        self.assertIn("Computer use", recovery)
        self.assertIn("Google Chrome", recovery)
        self.assertIn("Manage / Reconnect", recovery)
        self.assertIn("Do not synthesize or repair the manifest manually", recovery)
        self.assertIn("do not use AppleScript", boundary)
        self.assertIn("RDC/AppleScript", completion)

    def test_local_mac_gui_uses_semantic_targeting_real_mouse_and_readback(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        gui = (ROOT / "references" / "local-mac-gui.md").read_text()
        boundary = (ROOT / "references" / "remote-desktop-boundary.md").read_text()
        preflight = (ROOT / "references" / "capability-preflight.md").read_text()
        readme = (ROOT / "README.md").read_text()
        self.assertIn("local_mac_gui` routing", routing)
        self.assertIn("AXIdentifier", gui)
        self.assertIn("CoreGraphics", gui)
        self.assertIn("Derive element centers dynamically", gui)
        self.assertIn("current result/input view contains `4`", gui)
        self.assertIn("not Browser Control", gui)
        self.assertIn("Restore transient mouse/focus state", boundary)
        self.assertIn("independently verify GUI results", preflight)
        self.assertIn("Global keystrokes are a last resort", readme)

    def test_local_mac_gui_does_not_claim_unverified_silent_or_locked_support(self):
        gui = (ROOT / "references" / "local-mac-gui.md").read_text()
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        self.assertIn("silent/background execution without stealing focus", gui)
        self.assertIn("reliable operation while the Mac is locked", gui)
        self.assertIn("Do not claim silent/background or locked-Mac support", routing)

    def test_runtime_entrypoints_are_executable(self):
        for relative in ("scripts/codex_loop.py", "scripts/codex_loop_kernel.py"):
            mode = (ROOT / relative).stat().st_mode
            self.assertNotEqual(mode & 0o111, 0, relative)

    def test_readme_explains_browser_host_session_recovery(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("Workspace mode versus interaction target", readme)
        self.assertIn("Capability and permission preflight", readme)
        self.assertIn("Remembering `LOCAL_ROOT` across conversations", readme)
        self.assertIn("browser_host_health", readme)
        self.assertIn("browser_session_health", readme)
        self.assertIn("SESSION_BROWSER_CAPABILITY_MISSING", readme)
        self.assertIn("Settings -> Computer use -> Google Chrome -> Manage / Reconnect", readme)
        self.assertNotIn("RDC-backed Chrome path has been validated end to end", readme)


if __name__ == "__main__":
    unittest.main()
