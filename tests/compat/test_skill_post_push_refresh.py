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
    def test_handoff_creates_completion_blocking_skill_update_action(self):
        commit = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            call(
                root,
                "bootstrap",
                "--objective",
                "reconcile deployed skill",
                "--criterion",
                "deployment handoff is reconciled",
                "--no-validation",
                "--no-validation-reason",
                "test fixture has no meaningful executable validation",
            )
            call(root, "criterion", "--index", "0", "--status", "pass", "--evidence", "fixture criterion")

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
            self.assertEqual(data["deployment_state"], "DEPLOY_PENDING")
            self.assertEqual(data["target"], "current_chatgpt_workspace_skill")
            self.assertEqual(data["preferred_action"], "supported_host_managed_skill_update")
            self.assertEqual(data["fallback_action"], "surface_save_update_ui")
            self.assertFalse(data["browser_automation_authorized"])
            self.assertTrue(data["completion_blocking_until_reconciled"])
            action_id = data["external_action_id"]

            blocked, _ = call(root, "completion")
            self.assertEqual(blocked["data"]["status"], "CONTINUE")
            self.assertEqual(blocked["data"]["details"]["unresolved_external"], 1)

            call(
                root,
                "external",
                "--kind",
                "chatgpt_skill_update",
                "--state",
                "dispatched",
                "--identity",
                f"chatgpt-skill:codex-loop@{commit}",
                "--action-class",
                "external_non_idempotent",
                "--action-id",
                action_id,
            )
            call(
                root,
                "external",
                "--kind",
                "chatgpt_skill_update",
                "--state",
                "terminal_success",
                "--identity",
                f"chatgpt-skill:codex-loop@{commit}",
                "--action-class",
                "external_non_idempotent",
                "--action-id",
                action_id,
                "--details-json",
                json.dumps({"observed": "current workspace Skill reports the pushed revision"}),
            )
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

    def test_handoff_is_idempotent_for_same_skill_and_commit(self):
        commit = "f" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            call(
                root,
                "bootstrap",
                "--objective",
                "deduplicate deployment handoff",
                "--no-validation",
                "--no-validation-reason",
                "test fixture has no meaningful executable validation",
            )
            first, _ = call(root, "skill-deploy-handoff", "--skill-name", "epi-prose", "--repository", "owner/repo", "--commit", commit)
            second, _ = call(root, "skill-deploy-handoff", "--skill-name", "epi-prose", "--repository", "owner/repo", "--commit", commit)
            self.assertEqual(first["data"]["external_action_id"], second["data"]["external_action_id"])

    def test_handoff_rejects_short_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            call(
                root,
                "bootstrap",
                "--objective",
                "reject weak deployment identity",
                "--no-validation",
                "--no-validation-reason",
                "test fixture has no meaningful executable validation",
            )
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

    def test_docs_require_post_push_active_skill_reconciliation(self):
        skill = (ROOT / "SKILL.md").read_text()
        deployment = (ROOT / "references" / "skill-deployment.md").read_text()
        web_publish = (ROOT / "references" / "web-mode-publish.md").read_text()
        completion = (ROOT / "references" / "completion-criteria.md").read_text()
        runtime = (ROOT / "references" / "runtime-protocol.md").read_text()
        readme = (ROOT / "README.md").read_text()

        self.assertIn("Current-workspace Skill post-push invariant", skill)
        self.assertIn("skill-deploy-handoff", skill)
        self.assertIn("Never let `SOURCE_PUSHED` alone finish", skill)
        self.assertIn("Web workspace Skill post-push refresh", deployment)
        self.assertIn("surface the Save/Update UI handoff", deployment)
        self.assertIn("Post-push active Skill reconciliation", web_publish)
        self.assertIn("chatgpt_skill_update", runtime)
        self.assertIn("active workspace Skill", completion)
        self.assertIn("GitHub cannot silently become newer", readme)


if __name__ == "__main__":
    unittest.main()
