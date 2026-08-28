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

    def test_local_chrome_keeps_chatgpt_as_reasoning_authority(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text()
        self.assertIn("Keep ChatGPT as the reasoning/orchestration authority", routing)
        self.assertIn("RDC-backed structured Chrome automation", routing)
        self.assertIn("create `about:blank`", routing)
        self.assertIn("screenshot + mouse/keyboard GUI automation", routing)

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
        self.assertIn('"default_local_root"', setup)
        self.assertIn("does not itself select Local mode", setup)
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
        self.assertIn("do not invent a browser UI deployment step", readme)

    def test_runtime_entrypoints_are_executable(self):
        for relative in ("scripts/codex_loop.py", "scripts/codex_loop_kernel.py"):
            mode = (ROOT / relative).stat().st_mode
            self.assertNotEqual(mode & 0o111, 0, relative)

    def test_readme_explains_all_three_layers(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("Workspace mode versus interaction target", readme)
        self.assertIn("Capability and permission preflight", readme)
        self.assertIn("Remembering `LOCAL_ROOT` across conversations", readme)
        self.assertIn("RDC-backed Chrome path has been validated end to end", readme)


if __name__ == "__main__":
    unittest.main()
