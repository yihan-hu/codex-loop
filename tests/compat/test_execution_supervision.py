import tempfile, unittest
from pathlib import Path
from scripts.codex_loop_runtime.execution_supervision import CleanupStatus, EvidenceKind, ExecutionObservation, ProcessStatus, WorkloadStatus

class ExecutionSupervisionTests(unittest.TestCase):
    def test_pass_with_teardown_stall_is_representable(self):
        obs=ExecutionObservation(WorkloadStatus.PASSED,ProcessStatus.TEARDOWN_STALLED,CleanupStatus.SUCCEEDED,EvidenceKind.FRAMEWORK_AUTHORITATIVE,'237 passed in 18.41s','process remained alive beyond grace','owned process group terminated',None).validate()
        self.assertEqual(obs.workload_status,WorkloadStatus.PASSED)
    def test_progress_only_cannot_pass(self):
        with self.assertRaises(ValueError):
            ExecutionObservation(WorkloadStatus.PASSED,ProcessStatus.UNKNOWN,CleanupStatus.UNKNOWN,EvidenceKind.WEAK_TEXTUAL,'100%').validate()
    def test_teardown_stall_requires_terminal_workload(self):
        with self.assertRaises(ValueError):
            ExecutionObservation(WorkloadStatus.UNKNOWN,ProcessStatus.TEARDOWN_STALLED,CleanupStatus.UNKNOWN).validate()

class ValidationRecordIntegrationTests(unittest.TestCase):
    def test_rich_host_validation_can_pass_without_exit_code(self):
        from scripts.codex_loop_runtime.state import create_store
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); store=create_store(root); tid=store.path.parent.name; store.configure_task(tid,'validate',['pass']); plan=store.create_validation_plan(0,['pytest'],cwd=root)
            vid=store.record_host_validation(plan['plan_id'],0,['pytest'],None,cwd=root,evidence='tests terminal summary observed',workload_status='passed',process_status='teardown_stalled',cleanup_status='succeeded',evidence_kind='framework_authoritative',workload_evidence='237 passed in 18.41s',process_evidence='alive after grace',cleanup_evidence='group terminated')
            row=store.latest_validation(); self.assertEqual(row['id'],vid); self.assertEqual(row['workload_status'],'passed'); self.assertEqual(row['process_status'],'teardown_stalled'); self.assertIsNone(row['exit_code']); self.assertTrue(row['passed'])
