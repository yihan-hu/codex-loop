from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class WorkloadStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EvidenceKind(str, Enum):
    MACHINE_AUTHORITATIVE = "machine_authoritative"
    FRAMEWORK_AUTHORITATIVE = "framework_authoritative"
    EXPLICIT_PROTOCOL = "explicit_protocol"
    WEAK_TEXTUAL = "weak_textual"
    NONE = "none"


class ProcessStatus(str, Enum):
    RUNNING = "RUNNING"
    EXITED_CLEAN = "EXITED_CLEAN"
    EXITED_NONZERO = "EXITED_NONZERO"
    TEARDOWN_STALLED = "TEARDOWN_STALLED"
    TIMED_OUT = "TIMED_OUT"
    TERMINATED = "TERMINATED"
    ORPHANED = "ORPHANED"
    UNKNOWN = "UNKNOWN"


class CleanupStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ORPHANED = "ORPHANED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


_AUTHORITATIVE_SUCCESS_KINDS = {
    EvidenceKind.MACHINE_AUTHORITATIVE,
    EvidenceKind.FRAMEWORK_AUTHORITATIVE,
    EvidenceKind.EXPLICIT_PROTOCOL,
}
_TERMINAL_WORKLOAD = {
    WorkloadStatus.PASSED,
    WorkloadStatus.FAILED,
    WorkloadStatus.CANCELLED,
}


@dataclass(frozen=True)
class ExecutionObservation:
    workload_status: WorkloadStatus
    workload_evidence_kind: EvidenceKind
    workload_evidence: str | None
    process_status: ProcessStatus
    exit_code: int | None
    process_evidence: str | None
    cleanup_status: CleanupStatus = CleanupStatus.NOT_REQUIRED
    cleanup_evidence: str | None = None
    workload_adapter: str | None = None
    protocol_token_verified: bool = False
    legacy_inferred: bool = False

    @property
    def workload_passed(self) -> bool:
        return self.workload_status is WorkloadStatus.PASSED

    @property
    def workload_failed(self) -> bool:
        return self.workload_status in {WorkloadStatus.FAILED, WorkloadStatus.CANCELLED}

    @property
    def workload_terminal(self) -> bool:
        return self.workload_status in _TERMINAL_WORKLOAD

    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.process_status is ProcessStatus.TEARDOWN_STALLED:
            warnings.append("PROCESS_TEARDOWN_DEGRADED")
        if self.cleanup_status is CleanupStatus.FAILED:
            warnings.append("PROCESS_CLEANUP_FAILED")
        if self.process_status is ProcessStatus.ORPHANED or self.cleanup_status is CleanupStatus.ORPHANED:
            warnings.append("PROCESS_ORPHAN_DETECTED")
        if self.process_status is ProcessStatus.UNKNOWN or self.cleanup_status is CleanupStatus.UNSUPPORTED:
            warnings.append("PROCESS_SUPERVISION_PARTIAL")
        if self.workload_status is WorkloadStatus.UNKNOWN:
            warnings.append("WORKLOAD_RESULT_UNCERTAIN")
        return warnings

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["workload_status"] = self.workload_status.value
        data["workload_evidence_kind"] = self.workload_evidence_kind.value
        data["process_status"] = self.process_status.value
        data["cleanup_status"] = self.cleanup_status.value
        data["warnings"] = self.warnings()
        return data


def _nonempty(value: str | None) -> bool:
    return bool(value and value.strip())


def validate_observation(observation: ExecutionObservation) -> ExecutionObservation:
    if observation.workload_status is WorkloadStatus.PASSED:
        if observation.workload_evidence_kind not in _AUTHORITATIVE_SUCCESS_KINDS:
            raise ValueError("workload PASSED requires authoritative completion evidence; progress-only text cannot establish success")
        if not _nonempty(observation.workload_evidence):
            raise ValueError("workload PASSED requires non-empty authoritative workload evidence")
    if observation.workload_evidence_kind is EvidenceKind.FRAMEWORK_AUTHORITATIVE:
        if not _nonempty(observation.workload_adapter):
            raise ValueError("framework_authoritative evidence requires a registered adapter/parser identity")
    if observation.workload_evidence_kind is EvidenceKind.EXPLICIT_PROTOCOL:
        if not observation.protocol_token_verified:
            raise ValueError("explicit_protocol evidence requires capture-layer verification of the per-execution token")
    if observation.workload_evidence_kind is EvidenceKind.NONE and _nonempty(observation.workload_evidence):
        raise ValueError("evidence kind none cannot carry workload evidence")
    if observation.process_status is ProcessStatus.TEARDOWN_STALLED and not observation.workload_terminal:
        raise ValueError("TEARDOWN_STALLED is valid only after an authoritative terminal workload result")
    if observation.process_status is ProcessStatus.EXITED_CLEAN:
        if observation.exit_code is not None and int(observation.exit_code) != 0:
            raise ValueError("EXITED_CLEAN cannot carry a non-zero exit code")
    if observation.process_status is ProcessStatus.EXITED_NONZERO:
        if observation.exit_code is None or int(observation.exit_code) == 0:
            raise ValueError("EXITED_NONZERO requires a non-zero exit code")
    if observation.cleanup_status in {CleanupStatus.FAILED, CleanupStatus.ORPHANED} and not _nonempty(observation.cleanup_evidence):
        raise ValueError(f"{observation.cleanup_status.value} requires cleanup evidence")
    if observation.workload_status is WorkloadStatus.UNKNOWN and observation.workload_evidence_kind in _AUTHORITATIVE_SUCCESS_KINDS:
        # Authoritative evidence may establish failure/cancellation too, but UNKNOWN should not pretend it was parsed.
        if _nonempty(observation.workload_evidence):
            raise ValueError("UNKNOWN workload cannot carry authoritative terminal evidence; classify the observed terminal result")
    return observation


def legacy_observation(exit_code: int, evidence: str) -> ExecutionObservation:
    code = int(exit_code)
    passed = code == 0
    return validate_observation(
        ExecutionObservation(
            workload_status=WorkloadStatus.PASSED if passed else WorkloadStatus.FAILED,
            workload_evidence_kind=EvidenceKind.MACHINE_AUTHORITATIVE,
            workload_evidence=f"legacy compatibility inference from host-observed process exit code {code}: {evidence.strip()}",
            process_status=ProcessStatus.EXITED_CLEAN if passed else ProcessStatus.EXITED_NONZERO,
            exit_code=code,
            process_evidence=evidence.strip(),
            cleanup_status=CleanupStatus.NOT_REQUIRED,
            cleanup_evidence=None,
            legacy_inferred=True,
        )
    )


def observation_from_strings(
    *,
    workload_status: str,
    workload_evidence_kind: str,
    workload_evidence: str | None,
    process_status: str,
    exit_code: int | None,
    process_evidence: str | None,
    cleanup_status: str = CleanupStatus.NOT_REQUIRED.value,
    cleanup_evidence: str | None = None,
    workload_adapter: str | None = None,
    protocol_token_verified: bool = False,
) -> ExecutionObservation:
    try:
        observation = ExecutionObservation(
            workload_status=WorkloadStatus(workload_status.upper()),
            workload_evidence_kind=EvidenceKind(workload_evidence_kind.lower()),
            workload_evidence=workload_evidence,
            process_status=ProcessStatus(process_status.upper()),
            exit_code=None if exit_code is None else int(exit_code),
            process_evidence=process_evidence,
            cleanup_status=CleanupStatus(cleanup_status.upper()),
            cleanup_evidence=cleanup_evidence,
            workload_adapter=workload_adapter,
            protocol_token_verified=bool(protocol_token_verified),
            legacy_inferred=False,
        )
    except ValueError as exc:
        raise ValueError(f"invalid execution observation enum value: {exc}") from exc
    return validate_observation(observation)


def execution_policy(
    *,
    workload_timeout_ms: int = 300_000,
    teardown_grace_ms: int = 2_000,
    process_group_cleanup: bool = True,
    terminal_evidence_policy: str = "authoritative_only",
) -> dict[str, Any]:
    if workload_timeout_ms <= 0:
        raise ValueError("workload_timeout_ms must be positive")
    if teardown_grace_ms < 0:
        raise ValueError("teardown_grace_ms must be non-negative")
    if terminal_evidence_policy != "authoritative_only":
        raise ValueError("only authoritative_only terminal evidence policy is supported")
    return {
        "mode": "one_shot",
        "workload_timeout_ms": int(workload_timeout_ms),
        "teardown_grace_ms": int(teardown_grace_ms),
        "process_group_cleanup": bool(process_group_cleanup),
        "terminal_evidence_policy": terminal_evidence_policy,
        "invariant": "workload completion and process termination are independent execution facts",
    }
