from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import StrEnum
from typing import Any


class WorkloadStatus(StrEnum):
    UNKNOWN = "unknown"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessStatus(StrEnum):
    RUNNING = "running"
    EXITED_CLEAN = "exited_clean"
    EXITED_NONZERO = "exited_nonzero"
    TEARDOWN_STALLED = "teardown_stalled"
    TIMED_OUT = "timed_out"
    TERMINATED = "terminated"
    ORPHANED = "orphaned"
    UNKNOWN = "unknown"


class CleanupStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ORPHANED = "orphaned"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class EvidenceKind(StrEnum):
    MACHINE_AUTHORITATIVE = "machine_authoritative"
    FRAMEWORK_AUTHORITATIVE = "framework_authoritative"
    EXPLICIT_PROTOCOL = "explicit_protocol"
    WEAK_TEXTUAL = "weak_textual"
    NONE = "none"


TERMINAL_WORKLOAD = {WorkloadStatus.PASSED, WorkloadStatus.FAILED, WorkloadStatus.CANCELLED}
AUTHORITATIVE_EVIDENCE = {
    EvidenceKind.MACHINE_AUTHORITATIVE,
    EvidenceKind.FRAMEWORK_AUTHORITATIVE,
    EvidenceKind.EXPLICIT_PROTOCOL,
}


@dataclass(frozen=True)
class ExecutionObservation:
    workload_status: WorkloadStatus
    process_status: ProcessStatus
    cleanup_status: CleanupStatus
    evidence_kind: EvidenceKind = EvidenceKind.NONE
    workload_evidence: str | None = None
    process_evidence: str | None = None
    cleanup_evidence: str | None = None
    exit_code: int | None = None

    def validate(self) -> "ExecutionObservation":
        if self.workload_status in {WorkloadStatus.PASSED, WorkloadStatus.FAILED}:
            if self.evidence_kind not in AUTHORITATIVE_EVIDENCE:
                raise ValueError("terminal pass/fail workload status requires authoritative completion evidence")
            if not (self.workload_evidence and self.workload_evidence.strip()):
                raise ValueError("terminal pass/fail workload status requires workload evidence")
        if self.process_status == ProcessStatus.TEARDOWN_STALLED and self.workload_status not in TERMINAL_WORKLOAD:
            raise ValueError("teardown_stalled requires an already-terminal workload result")
        if self.cleanup_status == CleanupStatus.ORPHANED and self.process_status not in {ProcessStatus.ORPHANED, ProcessStatus.TEARDOWN_STALLED}:
            raise ValueError("orphaned cleanup requires orphaned or teardown-stalled process state")
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        result = asdict(self)
        for key in ("workload_status", "process_status", "cleanup_status", "evidence_kind"):
            result[key] = str(result[key])
        return result


def legacy_observation(exit_code: int, evidence: str) -> ExecutionObservation:
    if int(exit_code) == 0:
        return ExecutionObservation(
            workload_status=WorkloadStatus.PASSED,
            process_status=ProcessStatus.EXITED_CLEAN,
            cleanup_status=CleanupStatus.NOT_REQUIRED,
            evidence_kind=EvidenceKind.MACHINE_AUTHORITATIVE,
            workload_evidence=evidence,
            process_evidence=f"observed exit code {exit_code}",
            exit_code=int(exit_code),
        )
    return ExecutionObservation(
        workload_status=WorkloadStatus.FAILED,
        process_status=ProcessStatus.EXITED_NONZERO,
        cleanup_status=CleanupStatus.NOT_REQUIRED,
        evidence_kind=EvidenceKind.MACHINE_AUTHORITATIVE,
        workload_evidence=evidence,
        process_evidence=f"observed exit code {exit_code}",
        exit_code=int(exit_code),
    )
