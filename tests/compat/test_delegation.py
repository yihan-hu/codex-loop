import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL / "scripts"
CLI = SCRIPTS / "codex_loop.py"
sys.path.insert(0, str(SCRIPTS))

from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.completion import CompletionStatus, assess
from codex_loop_context_projection import build_isolation, build_working
from codex_loop_runtime.delegation import (
    abort_isolation,
    create_isolation,
    finish_isolation,
    isolation_status,
    validate_isolation_result,
)
from codex_loop_runtime.state import create_store
from codex_loop_runtime.write_transaction import guarded_write


def call(root: Path, *args: str, check: bool = True, input_obj=None):
    parts = list(args)
    if "--cwd" not in parts:
        if parts and parts[0] not in {"bootstrap", "command-check", "source-verify"} and "--task-id" not in parts:
            parts = [parts[0], "--cwd", str(root), "--use-active-task", *parts[1:]]
        else:
            parts = [parts[0], "--cwd", str(root), *parts[1:]]
    payload = None if input_obj is None else json.dumps(input_obj).encode()
    proc = subprocess.run(
        [sys.executable, str(CLI), *parts],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
    return json.loads(proc.stdout or b"{}"), proc


class DelegationTests(unittest.TestCase):
    def make(self, root: Path, *, validation: bool = False):
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        store = create_store(root)
        store.configure_task(
            store.path.parent.name,
            "parent objective",
            ["parent acceptance"],
            requires_validation=validation,
            no_validation_reason=None if validation else "delegation fixture has no executable validation",
        )
        capture_baseline(root, store)
        return store

    def enter(self, root: Path, store, **kw):
        return create_isolation(
            root,
            root,
            store,
            role=kw.pop("role", "reviewer"),
            objective=kw.pop("objective", "independently review the implementation"),
            **kw,
        )

    def result(self, **kw):
        base = {
            "summary": "Independent review found no blocking issue.",
            "findings": [{"claim": "review completed", "evidence": ["repo evidence"], "confidence": "high"}],
            "recommended_action": "continue parent validation",
            "files_inspected": ["a.txt"],
            "limitations": [],
        }
        base.update(kw)
        return base

    def test_native_fallback_warns_but_active_isolation_is_continue_not_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            store.set_criterion(0, "pass", "parent acceptance observed")
            projection = self.enter(root, store)
            self.assertEqual(projection["executor"]["kind"], "logical_isolation")
            self.assertFalse(projection["executor"]["physical_context_isolation"])
            self.assertIn("DEGRADED_SUBAGENT_ISOLATION", [w["code"] for w in projection["warnings"]])
            decision = assess(root, store)
            self.assertEqual(decision.status, CompletionStatus.CONTINUE)
            self.assertTrue(any("active isolated task" in reason for reason in decision.reasons))

    def test_finish_closes_isolation_warning_does_not_block_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            store.set_criterion(0, "pass", "parent acceptance observed")
            iso = self.enter(root, store)
            finished = finish_isolation(root, root, store, iso["isolation_id"], self.result())
            self.assertEqual(finished["isolation"]["status"], "finished")
            self.assertIsNone(store.active_isolation())
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)
            self.assertIn("DEGRADED_SUBAGENT_ISOLATION", [w["code"] for w in finished["warnings"]])

    def test_second_enter_rejects_nesting_without_breaking_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            first = self.enter(root, store)
            with self.assertRaisesRegex(RuntimeError, "nested isolation"):
                self.enter(root, store, role="security-reviewer")
            self.assertEqual(store.active_isolation()["isolation_id"], first["isolation_id"])
            self.assertEqual(store.get_meta("task_status"), "active")

    def test_read_only_isolation_rejects_local_guarded_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("a")
            store = self.make(root)
            self.enter(root, store)
            with self.assertRaisesRegex(PermissionError, "read-only"):
                guarded_write(root, store, Path("b.txt"), b"b")

    def test_host_workspace_change_is_detected_and_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            iso = self.enter(root, store)
            parent_generation = store.generation()
            (root / "host-change.txt").write_text("changed")
            finished = finish_isolation(root, root, store, iso["isolation_id"], self.result())
            self.assertGreater(store.generation(), parent_generation)
            self.assertTrue(finished["isolation"]["workspace_changed"])
            self.assertIn("WORKSPACE_CHANGED_DURING_ISOLATION", [w["code"] for w in finished["warnings"]])
            self.assertEqual(finished["main"]["state"]["delegation"], "main")

    def test_isolation_time_mutation_makes_prior_validation_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root, validation=True)
            store.set_criterion(0, "pass", "parent acceptance observed")
            store.record_validation(store.generation(), ["pytest"], 0, cwd=root, evidence="baseline validation passed")
            self.assertEqual(build_working(root, root, store)["state"]["validation"], "fresh-pass")
            iso = self.enter(root, store)
            (root / "later.txt").write_text("later")
            finish_isolation(root, root, store, iso["isolation_id"], self.result())
            self.assertEqual(build_working(root, root, store)["state"]["validation"], "stale")

    def test_structured_result_is_scrubbed_bounded_and_no_reasoning_transcript(self):
        value = self.result(
            summary="token=abc123456789 observed in fixture",
            findings=[{"claim": "password=hunter2 should be scrubbed", "evidence": ["authorization: secretvalue"], "confidence": "medium"}],
        )
        clean = validate_isolation_result(value)
        encoded = json.dumps(clean)
        self.assertIn("[redacted]", encoded)
        self.assertNotIn("hunter2", encoded)
        self.assertNotIn("secretvalue", encoded)
        with self.assertRaisesRegex(ValueError, "unsupported field"):
            validate_isolation_result({**self.result(), "reasoning_transcript": "hidden thoughts"})

    def test_abort_returns_to_main_without_parent_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            store.set_criterion(0, "pass", "parent acceptance observed")
            iso = self.enter(root, store)
            out = abort_isolation(root, root, store, iso["isolation_id"], "insufficient evidence")
            self.assertEqual(out["isolation"]["status"], "aborted")
            self.assertEqual(store.get_meta("task_status"), "active")
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)
            self.assertIn("DELEGATION_ABORTED", [w["code"] for w in out["warnings"]])

    def test_parent_cancel_atomically_aborts_active_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            iso = self.enter(root, store)
            store.cancel("user cancelled parent")
            row = store.isolation(iso["isolation_id"])
            self.assertEqual(row["status"], "aborted")
            self.assertIsNone(store.active_isolation())
            self.assertEqual(store.get_meta("task_status"), "cancelled")

    def test_isolation_projection_does_not_include_parent_hypotheses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            projection = self.enter(
                root,
                store,
                project_files=["src/auth/token.ts"],
                facts=["login failure is intermittent"],
                criteria_refs=["C1"],
            )
            text = json.dumps(projection)
            self.assertIn("login failure is intermittent", text)
            self.assertIn("src/auth/token.ts", text)
            self.assertNotIn("parent objective", text)
            self.assertNotIn("main recommended fix", text.lower())
            self.assertIn("untrusted", text)
            self.assertFalse(projection["executor"]["physical_context_isolation"])

    def test_parallel_and_background_preferences_degrade_to_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            projection = self.enter(
                root,
                store,
                requested_capability_overrides={"parallel_execution": True, "background_execution": True},
            )
            codes = {w["code"] for w in projection["warnings"]}
            self.assertIn("SERIALIZED_DELEGATION", codes)
            self.assertIn("INLINE_DELEGATION", codes)
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)

    def test_delegated_result_never_auto_passes_parent_criterion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            iso = self.enter(root, store)
            finish_isolation(root, root, store, iso["isolation_id"], self.result(summary="Everything looks good"))
            self.assertEqual(store.criteria()[0]["status"], "pending")
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)

    def test_wrong_id_duplicate_finish_and_invalid_role_fail_locally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            iso = self.enter(root, store)
            with self.assertRaisesRegex(ValueError, "wrong isolation_id"):
                finish_isolation(root, root, store, "iso_wrong", self.result())
            finish_isolation(root, root, store, iso["isolation_id"], self.result())
            with self.assertRaisesRegex(RuntimeError, "no active isolated task"):
                finish_isolation(root, root, store, iso["isolation_id"], self.result())
            with self.assertRaisesRegex(ValueError, "invalid isolation role"):
                create_isolation(root, root, store, role="implementer", objective="write code")

    def test_isolation_status_reports_main_and_isolated_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            self.assertEqual(isolation_status(root, root, store)["mode"], "main")
            iso = self.enter(root, store)
            status = isolation_status(root, root, store)
            self.assertEqual(status["mode"], "isolated")
            self.assertEqual(status["isolation_id"], iso["isolation_id"])

    def test_native_executor_name_does_not_override_reported_missing_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            projection = self.enter(
                root,
                store,
                actual_executor="native_subagent",
                actual_capability_report={
                    "behavioral_context_isolation": True,
                    "bounded_context_projection": True,
                },
            )
            codes = {w["code"] for w in projection["warnings"]}
            self.assertIn("DEGRADED_SUBAGENT_ISOLATION", codes)
            self.assertFalse(projection["executor"]["physical_context_isolation"])

    def test_warning_event_details_are_scrubbed_and_event_journal_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            iso = self.enter(root, store)
            iid = iso["isolation_id"]
            store.record_isolation_event(iid, "warning", {"code": "TEST", "message": "token=abc123456789"})
            warnings = store.isolation_warnings(iid, limit=32)
            self.assertIn("[redacted]", json.dumps(warnings))
            self.assertNotIn("abc123456789", json.dumps(warnings))
            for i in range(520):
                store.record_isolation_event(iid, "steer", {"index": i})
            with store.connect() as db:
                count = int(db.execute("SELECT COUNT(*) FROM isolation_events").fetchone()[0])
            self.assertLessEqual(count, 512)
            retained = store.isolation_warnings(iid, limit=64)
            self.assertIn("DEGRADED_SUBAGENT_ISOLATION", {w.get("code") for w in retained})
            self.assertIn("TEST", {w.get("code") for w in retained})

    def test_cli_smoke_enter_status_finish_abort_and_help(self):
        for command in ("isolate-enter", "isolate-status", "isolate-finish", "isolate-abort"):
            proc = subprocess.run([sys.executable, str(CLI), command, "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(proc.returncode, 0, command)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            call(root, "bootstrap", "--objective", "parent", "--criterion", "review complete", "--no-validation", "--no-validation-reason", "CLI delegation fixture")
            entered, _ = call(root, "isolate-enter", "--role", "reviewer", "--objective", "independent review", "--fact", "observed failure")
            isolation_id = entered["data"]["isolation_id"]
            status, _ = call(root, "isolate-status")
            self.assertEqual(status["data"]["mode"], "isolated")
            finished, _ = call(root, "isolate-finish", "--isolation-id", isolation_id, input_obj=self.result())
            self.assertEqual(finished["data"]["isolation"]["status"], "finished")
            entered2, _ = call(root, "isolate-enter", "--role", "tester", "--objective", "independent test review")
            aborted, _ = call(root, "isolate-abort", "--isolation-id", entered2["data"]["isolation_id"], "--reason", "test done")
            self.assertEqual(aborted["data"]["isolation"]["status"], "aborted")


if __name__ == "__main__":
    unittest.main()
