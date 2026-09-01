import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.codex_loop_runtime.change_tracker import capture_baseline
from scripts.codex_loop_runtime.completion import CompletionStatus, assess
from scripts.codex_loop_runtime.execution_supervision import (
    CleanupStatus,
    EvidenceKind,
    ExecutionObservation,
    ProcessStatus,
    WorkloadStatus,
    legacy_observation,
    validate_observation,
)
from scripts.codex_loop_runtime.state import create_store


class ExecutionObservationTests(unittest.TestCase):
    def test_progress_only_evidence_cannot_establish_pass(self):
        with self.assertRaises(ValueError):
            validate_observation(ExecutionObservation(
                workload_status=WorkloadStatus.PASSED,
                workload_evidence_kind=EvidenceKind.WEAK_TEXTUAL,
                workload_evidence="100%",
                process_status=ProcessStatus.TIMED_OUT,
                exit_code=None,
                process_evidence="host timeout",
                cleanup_status=CleanupStatus.UNKNOWN,
            ))

    def test_teardown_stalled_requires_terminal_workload(self):
        with self.assertRaises(ValueError):
            validate_observation(ExecutionObservation(
                workload_status=WorkloadStatus.UNKNOWN,
                workload_evidence_kind=EvidenceKind.NONE,
                workload_evidence=None,
                process_status=ProcessStatus.TEARDOWN_STALLED,
                exit_code=None,
                process_evidence="still alive",
            ))

    def test_framework_authoritative_requires_adapter(self):
        with self.assertRaises(ValueError):
            validate_observation(ExecutionObservation(
                workload_status=WorkloadStatus.PASSED,
                workload_evidence_kind=EvidenceKind.FRAMEWORK_AUTHORITATIVE,
                workload_evidence="237 passed in 18.41s",
                process_status=ProcessStatus.TEARDOWN_STALLED,
                exit_code=None,
                process_evidence="parent alive after terminal summary",
                cleanup_status=CleanupStatus.SUCCEEDED,
                cleanup_evidence="owned group terminated",
            ))

    def test_explicit_protocol_requires_verified_per_execution_token(self):
        with self.assertRaises(ValueError):
            validate_observation(ExecutionObservation(
                workload_status=WorkloadStatus.PASSED,
                workload_evidence_kind=EvidenceKind.EXPLICIT_PROTOCOL,
                workload_evidence="terminal marker observed",
                process_status=ProcessStatus.EXITED_CLEAN,
                exit_code=0,
                process_evidence="exit 0",
            ))

    def test_legacy_exit_code_is_explicit_compatibility_inference(self):
        obs = legacy_observation(0, "host exit")
        self.assertTrue(obs.legacy_inferred)
        self.assertEqual(obs.workload_status, WorkloadStatus.PASSED)
        self.assertEqual(obs.process_status, ProcessStatus.EXITED_CLEAN)


class CompletionSeparationTests(unittest.TestCase):
    def make_store(self, root: Path, *, clean_exit: bool = False):
        store = create_store(root)
        store.configure_task(
            store.path.parent.name,
            "run tests",
            ["tests pass"],
            profile="feature",
            requires_validation=True,
            requires_clean_process_exit=clean_exit,
        )
        capture_baseline(root, store)
        store.set_criterion(0, "pass", "authoritative test outcome recorded")
        store.mark_reviewed()
        return store

    def record(self, root: Path, store, observation: ExecutionObservation):
        plan = store.create_validation_plan(0, ["pytest", "-q"], cwd=root)
        return store.record_host_validation(
            plan["plan_id"],
            0,
            ["pytest", "-q"],
            observation.exit_code,
            cwd=root,
            evidence="host execution observation",
            observation=observation,
        )

    def test_passed_workload_teardown_stall_cleanup_success_can_pass_with_warning(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            store = self.make_store(root)
            self.record(root, store, validate_observation(ExecutionObservation(
                workload_status=WorkloadStatus.PASSED,
                workload_evidence_kind=EvidenceKind.MACHINE_AUTHORITATIVE,
                workload_evidence="junit xml says all tests passed",
                process_status=ProcessStatus.TEARDOWN_STALLED,
                exit_code=None,
                process_evidence="parent alive beyond teardown grace",
                cleanup_status=CleanupStatus.SUCCEEDED,
                cleanup_evidence="task-owned process group terminated",
            )))
            decision = assess(root, store)
            self.assertEqual(decision.status, CompletionStatus.PASS)
            self.assertIn("PROCESS_TEARDOWN_DEGRADED", decision.details["warnings"])

    def test_clean_exit_objective_is_not_satisfied_by_teardown_stall(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            store = self.make_store(root, clean_exit=True)
            self.record(root, store, validate_observation(ExecutionObservation(
                workload_status=WorkloadStatus.PASSED,
                workload_evidence_kind=EvidenceKind.MACHINE_AUTHORITATIVE,
                workload_evidence="structured report pass",
                process_status=ProcessStatus.TEARDOWN_STALLED,
                exit_code=None,
                process_evidence="did not exit in grace",
                cleanup_status=CleanupStatus.SUCCEEDED,
                cleanup_evidence="owned group terminated",
            )))
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)

    def test_unknown_workload_timeout_cannot_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            store = self.make_store(root)
            self.record(root, store, validate_observation(ExecutionObservation(
                workload_status=WorkloadStatus.UNKNOWN,
                workload_evidence_kind=EvidenceKind.WEAK_TEXTUAL,
                workload_evidence="[100%]",
                process_status=ProcessStatus.TIMED_OUT,
                exit_code=None,
                process_evidence="host timeout",
                cleanup_status=CleanupStatus.SUCCEEDED,
                cleanup_evidence="host reaped process",
            )))
            decision = assess(root, store)
            self.assertEqual(decision.status, CompletionStatus.CONTINUE)
            self.assertIn("WORKLOAD_RESULT_UNCERTAIN", decision.details["warnings"])

    def test_cleanup_orphan_blocks_completion(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            store = self.make_store(root)
            self.record(root, store, validate_observation(ExecutionObservation(
                workload_status=WorkloadStatus.PASSED,
                workload_evidence_kind=EvidenceKind.MACHINE_AUTHORITATIVE,
                workload_evidence="structured report pass",
                process_status=ProcessStatus.ORPHANED,
                exit_code=None,
                process_evidence="descendant remains",
                cleanup_status=CleanupStatus.ORPHANED,
                cleanup_evidence="owned descendant still observed",
            )))
            self.assertEqual(assess(root, store).status, CompletionStatus.BLOCKED)


if __name__ == "__main__":
    unittest.main()
