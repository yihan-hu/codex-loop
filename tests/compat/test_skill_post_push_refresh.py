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

    def route(self):
        proc = subprocess.run(
            [sys.executable, str(CLI), "route-init", "--host-surface", "chatgpt_web"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return json.loads(proc.stdout)["data"]["session_id"]

    def self_handoff(self, root, commit, repository="owner/repo"):
        return call(
            root,
            "skill-deploy-handoff",
            "--skill-name",
            "codex-loop",
            "--repository",
            repository,
            "--commit",
            commit,
            "--routing-session-id",
            self.route(),
        )

    def self_install_begin(self, root, commit, repository="owner/repo"):
        return call(
            root,
            "skill-deploy-install-begin",
            "--skill-name",
            "codex-loop",
            "--repository",
            repository,
            "--commit",
            commit,
        )

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

    def test_handoff_preserves_result_turn_and_install_begin_owns_terminal_turn(self):
        commit = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root)

            handoff, _ = self.self_handoff(root, commit)
            data = handoff["data"]
            self.assertEqual(data["source_state"], "SOURCE_PUSHED")
            self.assertEqual(data["native_update_state"], "NATIVE_UPDATE_REQUIRED")
            self.assertEqual(data["native_surface_state"], "NATIVE_SURFACE_NOT_OBSERVED")
            self.assertEqual(data["ui_state"], "UI_NOT_OBSERVED")
            self.assertEqual(data["deployment_state"], "DEPLOY_PENDING")
            self.assertEqual(data["install_state"], "INSTALL_READY")
            self.assertEqual(data["required_action"], "begin_native_install_in_dedicated_turn")
            self.assertEqual(data["handoff_mode"], "self_update_install_ready")
            self.assertIsNone(data["terminal_owner"])
            self.assertTrue(data["codex_loop_resume_allowed"])
            self.assertFalse(data["same_turn_codex_loop_followup_forbidden"])
            self.assertFalse(data["reconcile_on_next_turn"])
            self.assertEqual(data["next_install_command"], "skill-deploy-install-begin")
            self.assertFalse(data["handoff_is_ui_evidence"])
            self.assertFalse(data["handoff_is_deployment_evidence"])
            self.assertTrue(data["completion_blocking_until_reconciled"])

            # Planning the install must not consume the current response slot or activate the terminal barrier.
            still_working, _ = call(root, "completion")
            self.assertEqual(still_working["data"]["status"], "CONTINUE")

            premature_surface, proc = call(
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
                "surface was claimed before the dedicated install turn",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("only after skill-deploy-install-begin", premature_surface["error"]["message"])

            install_begin, _ = self.self_install_begin(root, commit)
            install_data = install_begin["data"]
            self.assertEqual(install_data["install_state"], "INSTALL_TURN_STARTED")
            self.assertEqual(install_data["handoff_mode"], "terminal_self_update")
            self.assertEqual(install_data["terminal_owner"], "skill-creator/host")
            self.assertFalse(install_data["codex_loop_resume_allowed"])
            self.assertTrue(install_data["same_turn_codex_loop_followup_forbidden"])
            self.assertTrue(install_data["reconcile_on_next_turn"])

            blocked, proc = call(root, "completion", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("terminal Codex Loop self-update handoff is active", blocked["error"]["message"])

    def test_native_surface_and_deployment_are_separate_observed_states(self):
        commit = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root)
            handoff, _ = self.self_handoff(root, commit)
            self.self_install_begin(root, commit)
            resumed, _ = call(
                root,
                "skill-deploy-resume",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--later-host-turn-observed",
                "--evidence",
                "a later user turn is now active",
            )
            self.assertEqual(resumed["data"]["terminal_barrier_state"], "RELEASED_ON_LATER_TURN")

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
            self.self_handoff(root, commit)
            self.self_install_begin(root, commit)
            call(
                root,
                "skill-deploy-resume",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--later-host-turn-observed",
                "--evidence",
                "later host turn observed",
            )
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
            self.self_handoff(root, commit)
            self.self_install_begin(root, commit)
            call(
                root,
                "skill-deploy-resume",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--later-host-turn-observed",
                "--evidence",
                "later host turn observed",
            )
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
            repeated, _ = self.self_handoff(root, commit)
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

    def test_self_update_resume_requires_explicit_later_turn_observation(self):
        commit = "c" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root, criterion=False)
            self.self_handoff(root, commit)
            self.self_install_begin(root, commit)
            out, proc = call(
                root,
                "skill-deploy-resume",
                "--skill-name",
                "codex-loop",
                "--repository",
                "owner/repo",
                "--commit",
                commit,
                "--evidence",
                "same turn cannot count",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("only on a later host turn", out["error"]["message"])


    def test_same_conversation_resume_reuses_handoff_routing_session(self):
        commit = "d" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            self.bootstrap(root, criterion=False)
            sid = self.route()
            subprocess.run(
                [sys.executable, str(CLI), "permission-observation-record", "--session-id", sid,
                 "--capability", "github_push", "--scope", "repo:owner/repo", "--evidence", "live probe"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            call(
                root, "skill-deploy-handoff", "--skill-name", "codex-loop", "--repository", "owner/repo",
                "--commit", commit, "--routing-session-id", sid,
            )
            call(
                root, "skill-deploy-install-begin", "--skill-name", "codex-loop", "--repository", "owner/repo",
                "--commit", commit, "--routing-session-id", sid,
            )
            resumed, _ = call(
                root, "skill-deploy-resume", "--skill-name", "codex-loop", "--repository", "owner/repo",
                "--commit", commit, "--later-host-turn-observed", "--same-conversation-observed",
                "--evidence", "later user turn in the same conversation",
            )
            self.assertTrue(resumed["data"]["routing_session_reused"])
            self.assertEqual(resumed["data"]["routing_session_id"], sid)
            status = subprocess.run(
                [sys.executable, str(CLI), "permission-observation-status", "--session-id", sid,
                 "--capability", "github_push", "--scope", "repo:owner/repo"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            self.assertTrue(json.loads(status.stdout)["data"]["fresh"])

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
                "--routing-session-id",
                self.route(),
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
        self.assertIn("skill-deploy-install-begin", deployment)
        self.assertIn("INSTALL_READY", deployment)
        self.assertIn("skill-deploy-resume", deployment)
        self.assertIn("--same-conversation-observed", deployment)
        self.assertIn("routing_session_id", deployment)
        self.assertIn("thin_from_remote_head", web_publish)
        self.assertIn("Do not attempt a full-history bundle first", web_publish)
        self.assertIn("skill-deploy-surface-record", deployment)
        self.assertIn("skill-deploy-complete", deployment)
        self.assertIn("FAST_PUBLISH", web_publish)
        self.assertIn("source-only", web_publish)
        self.assertIn("terminal ownership boundary", deployment)
        self.assertIn("skill-creator", deployment)
        self.assertIn("UI_SURFACED", runtime)
        self.assertIn("skill-deploy-install-begin", runtime)
        self.assertIn("skill-deploy-resume", runtime)
        self.assertIn("active workspace Skill", completion)
        self.assertIn("terminal handoff", completion)
        self.assertIn("native Skill installation/update surface", readme)
        self.assertIn("terminal self-update", readme)
        self.assertIn("Canonical Codex Loop self-update recovery", deployment)
        self.assertIn("build_self_update_bridge.py", skill)
        self.assertIn("b5a748", skill.lower())
        self.assertIn("b5a748", deployment.lower())
        self.assertIn("b5a748", readme.lower())
        self.assertIn("Library not found", deployment)
        self.assertIn("exactly `SKILL.md` and `agents/openai.yaml`", deployment)
        self.assertIn("quoted", deployment)
        self.assertIn("no `policy.products`", deployment)
        self.assertNotIn("HOST_SAME_NAME_SKILL_UPDATE_SURFACE_UNSTABLE", deployment)
        self.assertNotIn("Try in chat", deployment)
        self.assertNotIn("A/B", deployment)


if __name__ == "__main__":
    unittest.main()
