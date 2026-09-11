import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class InteractionRoutingContractTests(unittest.TestCase):
    def test_skill_keeps_routing_lazy_and_at_side_effect_boundary(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Repository and host routing", skill)
        self.assertIn("Web is the default workspace until the user explicitly selects Local", skill)
        self.assertIn("Keep routing checks at the action boundary", skill)
        self.assertIn("Do not force unrelated reasoning/edit/test steps through routing state", skill)
        self.assertIn("GitHub, Google Drive, Remote Desktop Commander", skill)
        self.assertIn("optional", skill)

    def test_workspace_and_interaction_axes_remain_independent(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text(encoding="utf-8")
        self.assertIn("Every new conversation starts with `workspace_mode=web`", routing)
        self.assertIn("interaction_target=local_chrome", routing)
        self.assertIn("workspace_mode=web` plus `interaction_target=local_chrome", routing)
        self.assertIn("do not infer Local workspace mode", routing)

    def test_rdc_is_transport_not_semantic_grant(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text(encoding="utf-8")
        boundary = (ROOT / "references" / "remote-desktop-boundary.md").read_text(encoding="utf-8")
        self.assertIn("allowedDirectories=[]", routing)
        self.assertIn("never a semantic grant", routing)
        self.assertIn("hard capability ceiling, not semantic permission", boundary)
        self.assertIn("Never search sibling repositories", boundary)

    def test_local_source_and_computer_use_need_current_task_authorization(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text(encoding="utf-8")
        boundary = (ROOT / "references" / "remote-desktop-boundary.md").read_text(encoding="utf-8")
        self.assertIn("explicitly authorized computer use for the current task", routing)
        self.assertIn("Do **not** infer authorization", routing)
        self.assertIn("require explicit current-task local-source-mutation authorization", boundary)
        self.assertIn("generic `push` wording", boundary)

    def test_missing_browser_executor_is_not_faked_with_rdc(self):
        routing = (ROOT / "references" / "interaction-routing.md").read_text(encoding="utf-8")
        recovery = (ROOT / "references" / "browser-control-recovery.md").read_text(encoding="utf-8")
        self.assertIn("SESSION_BROWSER_CAPABILITY_MISSING", routing)
        self.assertIn("Do not silently substitute RDC-backed AppleScript", routing)
        self.assertIn("not a Browser Control executor", recovery)

    def test_skill_packaging_and_installation_stay_separate(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        deployment = (ROOT / "references" / "skill-deployment.md").read_text(encoding="utf-8")
        self.assertIn("validated `skill.zip` may be copied byte-for-byte to `codex-loop.zip`", skill)
        self.assertIn("codex-loop.zip", deployment)
        self.assertIn("manual", deployment.lower())

    def test_runtime_entrypoints_are_executable(self):
        for relative in ("scripts/codex_loop.py", "scripts/codex_loop_kernel.py"):
            mode = (ROOT / relative).stat().st_mode
            self.assertNotEqual(mode & 0o111, 0, relative)


if __name__ == "__main__":
    unittest.main()
