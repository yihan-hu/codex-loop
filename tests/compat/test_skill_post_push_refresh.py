import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


def call(root, *args, check=True):
    parts = list(args)
    if "--cwd" not in parts:
        parts = [parts[0], "--cwd", str(root), *parts[1:]]
    proc = subprocess.run(
        [sys.executable, str(CLI), *parts],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
    return json.loads(proc.stdout or b"{}"), proc


class SkillPostPushRefreshTests(unittest.TestCase):
    def bootstrap(self, root, objective="reconcile deployed skill", criterion=True):
        args = [
            "bootstrap",
            "--objective",
            objective,
            "--no-validation",
            "--no-validation-reason",
            "test fixture has no meaningful executable validation",
        ]
        if criterion:
            args.extend(["--criterion", "deployment handoff is reconciled"])
        call(root, *args)
        if criterion:
            call(root, "criterion", "--index", "0", "--status", "pass", "--evidence", "fixture criterion")

    def test_handoff_is_planning_only_and_cannot_claim_native_ui(self):
        commit = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root)

            handoff, _ = call(
                root,
                "skill-deploy-handoff",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
            )
            data = handoff["data"]
            self.assertEqual(data["source_state"], "SOURCE_PUSHED")
            self.assertEqual(data["native_update_state"], "NATIVE_UPDATE_REQUIRED")
            self.assertEqual(data["native_surface_state"], "NATIVE_SURFACE_NOT_OBSERVED")
            self.assertEqual(data["ui_state"], "UI_NOT_OBSERVED")
            self.assertEqual(data["deployment_state"], "DEPLOY_PENDING")
            self.assertEqual(data["native_handoff_owner"], "skill-creator/host")
            self.assertEqual(data["required_action"], "invoke_skill_creator_or_equivalent_native_skill_update_flow")
            self.assertFalse(data["handoff_is_ui_evidence"])
            self.assertFalse(data["handoff_is_deployment_evidence"])
            self.assertFalse(data["browser_automation_authorized"])
            self.assertTrue(data["completion_blocking_until_reconciled"])

            blocked, _ = call(root, "completion")
            self.assertEqual(blocked["data"]["status"], "CONTINUE")
            self.assertEqual(blocked["data"]["details"]["unresolved_external"], 1)

    def test_native_surface_and_deployment_are_separate_observed_states(self):
        commit = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root)
            handoff, _ = call(root, "skill-deploy-handoff", "--skill-name", "codex-loop", "--repository", "owner/repo", "--commit", commit)

            surface, _ = call(
                root,
                "skill-deploy-surface-record",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--surface-kind",
                "skill_creator_install_ui",
                "--evidence",
                "host visibly surfaced the native Skill install/update control",
            )
            self.assertEqual(surface["data"]["native_update_state"], "NATIVE_UPDATE_DISPATCHED")
            self.assertEqual(surface["data"]["native_surface_state"], "NATIVE_SURFACE_OBSERVED")
            self.assertEqual(surface["data"]["ui_state"], "UI_SURFACED")
            self.assertEqual(surface["data"]["deployment_state"], "DEPLOY_PENDING")
            self.assertFalse(surface["data"]["surface_is_deployment_evidence"])
            self.assertEqual(surface["data"]["external_action_id"], handoff["data"]["external_action_id"])

            still_blocked, _ = call(root, "completion")
            self.assertEqual(still_blocked["data"]["status"], "CONTINUE")
            self.assertEqual(still_blocked["data"]["details"]["unresolved_external"], 1)

            done_deploy, _ = call(
                root,
                "skill-deploy-complete",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--evidence",
                "current workspace Skill reports the pushed revision",
            )
            self.assertEqual(done_deploy["data"]["deployment_state"], "DEPLOYED")
            self.assertEqual(done_deploy["data"]["native_update_state"], "NATIVE_UPDATE_CONFIRMED")

            call(
                root,
                "objective-audit",
                "--audit-json",
                json.dumps({
                    "requirements": [{
                        "requirement": "reconcile deployed skill",
                        "status": "proven",
                        "evidence": "current workspace Skill reports the pushed revision",
                        "authoritative_source": "host deployment observation",
                    }]
                }),
            )
            done, _ = call(root, "completion")
            self.assertEqual(done["data"]["status"], "PASS")

    def test_deployment_completion_requires_observed_native_surface(self):
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root, criterion=False)
            call(root, "skill-deploy-handoff", "--skill-name", "codex-loop", "--repository", "owner/repo", "--commit", commit)
            out, proc = call(
                root,
                "skill-deploy-complete",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--evidence",
                "claimed installed",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("only after a native update/install surface", out["error"]["message"])

    def test_repeated_handoff_reflects_existing_deployed_state_without_becoming_evidence(self):
        commit = "b" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root, criterion=False)
            call(root, "skill-deploy-handoff", "--skill-name", "codex-loop", "--repository", "owner/repo", "--commit", commit)
            call(
                root,
                "skill-deploy-surface-record",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--surface-kind",
                "skill_creator_install_ui",
                "--evidence",
                "native install UI appeared",
            )
            call(
                root,
                "skill-deploy-complete",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--evidence",
                "intended revision is active",
            )
            repeated, _ = call(root, "skill-deploy-handoff", "--skill-name", "codex-loop", "--repository", "owner/repo", "--commit", commit)
            data = repeated["data"]
            self.assertEqual(data["external_action_state"], "terminal_success")
            self.assertEqual(data["deployment_state"], "DEPLOYED")
            self.assertEqual(data["native_update_state"], "NATIVE_UPDATE_CONFIRMED")
            self.assertFalse(data["handoff_is_ui_evidence"])
            self.assertFalse(data["handoff_is_deployment_evidence"])

    def test_handoff_is_idempotent_for_same_skill_and_commit(self):
        commit = "f" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root, objective="deduplicate deployment handoff", criterion=False)
            first, _ = call(root, "skill-deploy-handoff", "--skill-name", "epi-prose", "--repository", "owner/repo", "--commit", commit)
            second, _ = call(root, "skill-deploy-handoff", "--skill-name", "epi-prose", "--repository", "owner/repo", "--commit", commit)
            self.assertEqual(first["data"]["external_action_id"], second["data"]["external_action_id"])

    def test_handoff_rejects_short_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root, objective="reject weak deployment identity", criterion=False)
            out, proc = call(
                root,
                "skill-deploy-handoff",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                "deadbeef",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("full 40-hex", out["error"]["message"])

    def test_docs_require_native_skill_creator_handoff_and_observed_ui(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        web_publish = (ROOT / "references" / "web-mode-publish.md").read_text()
        completion = (ROOT / "references" / "completion-criteria.md").read_text()
        runtime = (ROOT / "references" / "runtime-protocol.md").read_text()
        readme = (ROOT / "README.md").read_text()

        self.assertIn("Current-workspace Skill post-push invariant", skill)
        self.assertIn("skill-creator", skill)
        self.assertIn("handoff itself is not UI evidence", skill)
        self.assertIn("Native Skill update surface", deployment)
        self.assertIn("Codex Loop must never emulate", deployment)
        self.assertIn("skill-deploy-surface-record", deployment)
        self.assertIn("skill-deploy-complete", deployment)
        self.assertIn("Post-push active Skill reconciliation", web_publish)
        self.assertIn("skill-creator", web_publish)
        self.assertIn("UI_SURFACED", runtime)
        self.assertIn("active workspace Skill", completion)
        self.assertIn("native Skill installation/update surface", readme)


if __name__ == "__main__":
    unittest.main()
