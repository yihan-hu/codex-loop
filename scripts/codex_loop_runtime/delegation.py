from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .change_tracker import sync_generation
from .checkpoint import create as create_checkpoint
from codex_loop_context_projection import build_isolation, build_working
from .state import StateStore, scrub_persisted_text

CAPABILITY_KEYS = (
    "fresh_model_context",
    "independent_model_instance",
    "physical_context_isolation",
    "behavioral_context_isolation",
    "bounded_context_projection",
    "parallel_execution",
    "background_execution",
    "independent_tool_sandbox",
)

LOGICAL_CAPABILITIES = {
    "fresh_model_context": False,
    "independent_model_instance": False,
    "physical_context_isolation": False,
    "behavioral_context_isolation": True,
    "bounded_context_projection": True,
    "parallel_execution": False,
    "background_execution": False,
    "independent_tool_sandbox": False,
}

DEFAULT_NATIVE_REQUEST = {
    "fresh_model_context": True,
    "independent_model_instance": True,
    "physical_context_isolation": True,
    "behavioral_context_isolation": True,
    "bounded_context_projection": True,
    "parallel_execution": False,
    "background_execution": False,
    "independent_tool_sandbox": False,
}

DEFAULT_LOGICAL_REQUEST = dict(LOGICAL_CAPABILITIES)

ROLES = {
    "reviewer",
    "researcher",
    "tester",
    "debugger",
    "security-reviewer",
    "architecture-reviewer",
}

MAX_RESULT_BYTES = 64 * 1024
MAX_FINDINGS = 24
MAX_EVIDENCE_PER_FINDING = 16
MAX_FILES = 64
MAX_LIMITATIONS = 24
MAX_PROJECT_FILES = 64
MAX_FACTS = 48
MAX_CRITERIA_REFS = 32


def _clean_text(value: Any, *, limit: int, required: bool = False) -> str:
    clean = (scrub_persisted_text(None if value is None else str(value), limit=limit) or "").strip()
    if required and not clean:
        raise ValueError("required delegation text must not be empty")
    return clean


def _clean_text_list(values: list[Any] | tuple[Any, ...] | None, *, item_limit: int, max_items: int) -> list[str]:
    result: list[str] = []
    for item in list(values or [])[:max_items]:
        clean = _clean_text(item, limit=item_limit)
        if clean:
            result.append(clean)
    return result


def _capability_map(values: dict[str, Any] | None, *, default: dict[str, bool]) -> dict[str, bool]:
    result = dict(default)
    for key, value in (values or {}).items():
        if key not in CAPABILITY_KEYS:
            raise ValueError(f"unknown delegation capability: {key}")
        result[key] = bool(value)
    return {key: bool(result.get(key, False)) for key in CAPABILITY_KEYS}


def requested_capabilities(executor: str, overrides: dict[str, Any] | None = None) -> dict[str, bool]:
    if executor == "native_subagent":
        return _capability_map(overrides, default=DEFAULT_NATIVE_REQUEST)
    if executor == "logical_isolation":
        return _capability_map(overrides, default=DEFAULT_LOGICAL_REQUEST)
    raise ValueError(f"unsupported requested delegation executor: {executor}")


def executor_capabilities(executor: str, reported: dict[str, Any] | None = None) -> dict[str, bool]:
    if executor == "logical_isolation":
        # Logical isolation capabilities are an implementation fact, not caller-controlled metadata.
        for key, value in (reported or {}).items():
            if key not in CAPABILITY_KEYS:
                raise ValueError(f"unknown delegation capability: {key}")
            if bool(value) != LOGICAL_CAPABILITIES[key]:
                raise ValueError(f"logical isolation capability report conflicts with runtime truth: {key}")
        return dict(LOGICAL_CAPABILITIES)
    if executor == "native_subagent":
        if reported is None:
            raise ValueError("native_subagent actual executor requires an explicit host capability report")
        return _capability_map(reported, default={key: False for key in CAPABILITY_KEYS})
    raise ValueError(f"unsupported actual delegation executor: {executor}")


def calculate_missing_capabilities(requested: dict[str, bool], actual: dict[str, bool]) -> list[str]:
    return [key for key in CAPABILITY_KEYS if bool(requested.get(key)) and not bool(actual.get(key))]


def _warning(code: str, message: str, **details: Any) -> dict[str, Any]:
    item = {"code": code, "severity": "warning", "message": _clean_text(message, limit=4096, required=True)}
    item.update(details)
    return item


def build_degradation_warnings(
    *,
    requested_executor: str,
    actual_executor: str,
    requested: dict[str, bool],
    actual: dict[str, bool],
    missing: list[str],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    core_isolation_caps = {"fresh_model_context", "independent_model_instance", "physical_context_isolation", "behavioral_context_isolation", "bounded_context_projection", "independent_tool_sandbox"}
    native_degraded = requested_executor == "native_subagent" and (
        actual_executor != "native_subagent" or bool(core_isolation_caps.intersection(missing))
    )
    if native_degraded:
        message = (
            "Native subagent execution was unavailable; delegation continued using logical isolation."
            if actual_executor != "native_subagent"
            else "The native delegated executor does not provide all requested isolation capabilities; execution continues with the host-reported capability set."
        )
        warnings.append(_warning(
            "DEGRADED_SUBAGENT_ISOLATION",
            message,
            requested_executor=requested_executor,
            actual_executor=actual_executor,
            missing_capabilities=list(missing),
        ))
    if requested.get("parallel_execution") and not actual.get("parallel_execution"):
        warnings.append(_warning(
            "SERIALIZED_DELEGATION",
            "Parallel delegated execution was unavailable; delegations must be serialized by the host orchestrator.",
            requested_executor=requested_executor,
            actual_executor=actual_executor,
            missing_capabilities=["parallel_execution"],
        ))
    if requested.get("background_execution") and not actual.get("background_execution"):
        warnings.append(_warning(
            "INLINE_DELEGATION",
            "Background delegated execution was unavailable; delegated work must run inline.",
            requested_executor=requested_executor,
            actual_executor=actual_executor,
            missing_capabilities=["background_execution"],
        ))
    return warnings


def _context_spec(
    *,
    project_files: list[str] | None,
    facts: list[str] | None,
    criteria_refs: list[str] | None,
) -> dict[str, Any]:
    spec = {
        "projected_context": {
            "files": _clean_text_list(project_files, item_limit=2048, max_items=MAX_PROJECT_FILES),
            "facts": _clean_text_list(facts, item_limit=4096, max_items=MAX_FACTS),
            "criteria_refs": _clean_text_list(criteria_refs, item_limit=256, max_items=MAX_CRITERIA_REFS),
        },
        "excluded_parent_context": [
            "main_agent_hypotheses",
            "main_preferred_solution",
            "main_root_cause_guess",
            "main_recommended_patch",
            "main_next_action",
            "unrequested_prior_conclusions",
            "private_chain_of_reasoning",
        ],
        "context_policy": {
            "enforcement": "behavioral",
            "physical_context_isolation": False,
            "prior_reasoning": "untrusted_unless_projected",
        },
    }
    if len(json.dumps(spec, ensure_ascii=True, sort_keys=True).encode("utf-8")) > 256 * 1024:
        raise ValueError("isolation context projection exceeds 256 KiB")
    return spec

def create_isolation(
    root: Path,
    cwd: Path,
    store: StateStore,
    *,
    role: str,
    objective: str,
    requested_executor: str = "native_subagent",
    actual_executor: str = "logical_isolation",
    project_files: list[str] | None = None,
    facts: list[str] | None = None,
    criteria_refs: list[str] | None = None,
    requested_capability_overrides: dict[str, Any] | None = None,
    actual_capability_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store.ensure_active()
    if role not in ROLES:
        raise ValueError(f"invalid isolation role: {role}")
    if store.active_isolation() is not None:
        raise RuntimeError("an isolated task is already active; nested isolation is not supported; finish/abort it and serialize the next delegation")
    sync_generation(root, store)
    parent_generation = store.generation()
    clean_objective = _clean_text(objective, limit=8192, required=True)
    requested = requested_capabilities(requested_executor, requested_capability_overrides)
    actual = executor_capabilities(actual_executor, actual_capability_report)
    missing = calculate_missing_capabilities(requested, actual)
    context_spec = _context_spec(project_files=project_files, facts=facts, criteria_refs=criteria_refs)

    create_checkpoint(
        root,
        cwd,
        store,
        key_findings=["delegation entry checkpoint; current workspace reality remains authoritative"],
        next_action=f"complete isolated {role} task and return structured evidence",
    )
    checkpoint = store.latest_checkpoint()
    checkpoint_id = None if checkpoint is None else int(checkpoint["id"])
    isolation_id = "iso_" + uuid.uuid4().hex[:20]
    item = store.create_isolation(
        isolation_id=isolation_id,
        role=role,
        objective=clean_objective,
        parent_generation=parent_generation,
        requested_executor=requested_executor,
        actual_executor=actual_executor,
        requested_capabilities=requested,
        actual_capabilities=actual,
        missing_capabilities=missing,
        mutation_policy="read_only",
        context_spec=context_spec,
        checkpoint_id=checkpoint_id,
    )
    for warning in build_degradation_warnings(
        requested_executor=requested_executor,
        actual_executor=actual_executor,
        requested=requested,
        actual=actual,
        missing=missing,
    ):
        store.record_isolation_event(isolation_id, "warning", warning)
    return build_isolation(root, cwd, store, isolation_id, reconcile=False)


def active_isolation(store: StateStore) -> dict[str, Any] | None:
    return store.active_isolation()


def isolation_status(root: Path, cwd: Path, store: StateStore) -> dict[str, Any]:
    sync_generation(root, store)
    active = store.active_isolation()
    if active is None:
        return {"mode": "main", "active_isolation": None, "warnings": store.isolation_warnings(limit=16)}
    current_generation = store.generation()
    return {
        "mode": "isolated",
        "isolation_id": active["isolation_id"],
        "role": active["role"],
        "status": active["status"],
        "parent_generation": int(active["parent_generation"]),
        "current_generation": current_generation,
        "workspace_changed": current_generation != int(active["parent_generation"]),
        "warnings": store.isolation_warnings(active["isolation_id"], limit=16),
    }


def validate_isolation_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("isolated result must be a JSON object")
    allowed = {"summary", "findings", "recommended_action", "files_inspected", "limitations"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("isolated result contains unsupported field(s): " + ", ".join(unknown))
    summary = _clean_text(value.get("summary"), limit=8192, required=True)
    findings_raw = value.get("findings", [])
    if not isinstance(findings_raw, list):
        raise ValueError("isolated result findings must be a list")
    findings: list[dict[str, Any]] = []
    for raw in findings_raw[:MAX_FINDINGS]:
        if not isinstance(raw, dict):
            raise ValueError("each isolated finding must be an object")
        claim = _clean_text(raw.get("claim"), limit=4096, required=True)
        evidence_raw = raw.get("evidence", [])
        if not isinstance(evidence_raw, list):
            raise ValueError("finding evidence must be a list")
        evidence = _clean_text_list(evidence_raw, item_limit=2048, max_items=MAX_EVIDENCE_PER_FINDING)
        if not evidence:
            raise ValueError("each isolated finding requires at least one evidence reference")
        confidence = _clean_text(raw.get("confidence", "unknown"), limit=32) or "unknown"
        if confidence not in {"low", "medium", "high", "unknown"}:
            raise ValueError("finding confidence must be one of low/medium/high/unknown")
        findings.append({"claim": claim, "evidence": evidence, "confidence": confidence})
    if len(findings_raw) > MAX_FINDINGS:
        raise ValueError(f"isolated result has too many findings; maximum is {MAX_FINDINGS}")
    files_raw = value.get("files_inspected", [])
    limitations_raw = value.get("limitations", [])
    if not isinstance(files_raw, list) or not isinstance(limitations_raw, list):
        raise ValueError("files_inspected and limitations must be lists")
    if len(files_raw) > MAX_FILES or len(limitations_raw) > MAX_LIMITATIONS:
        raise ValueError("isolated result list exceeds bounded persistence limits")
    result = {
        "summary": summary,
        "findings": findings,
        "recommended_action": _clean_text(value.get("recommended_action"), limit=4096),
        "files_inspected": _clean_text_list(files_raw, item_limit=2048, max_items=MAX_FILES),
        "limitations": _clean_text_list(limitations_raw, item_limit=4096, max_items=MAX_LIMITATIONS),
    }
    encoded = json.dumps(result, ensure_ascii=True, sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError("isolated result exceeds 64 KiB after scrubbing")
    return result


def finish_isolation(root: Path, cwd: Path, store: StateStore, isolation_id: str, result: Any) -> dict[str, Any]:
    store.ensure_active()
    active = store.active_isolation()
    if active is None:
        raise RuntimeError("no active isolated task")
    if str(active["isolation_id"]) != str(isolation_id):
        raise ValueError(f"wrong isolation_id: active isolation is {active['isolation_id']}")
    clean_result = validate_isolation_result(result)
    sync_generation(root, store)
    exit_generation = store.generation()
    workspace_changed = exit_generation != int(active["parent_generation"])
    item = store.finish_isolation(
        str(isolation_id),
        result=clean_result,
        exit_generation=exit_generation,
        workspace_changed=workspace_changed,
    )
    if workspace_changed:
        store.record_isolation_event(str(isolation_id), "warning", _warning(
            "WORKSPACE_CHANGED_DURING_ISOLATION",
            "Workspace state changed while the isolated task was active; current workspace reality overrides saved assumptions.",
            parent_generation=int(active["parent_generation"]),
            exit_generation=exit_generation,
        ))
    if clean_result.get("limitations"):
        store.record_isolation_event(str(isolation_id), "warning", _warning(
            "DELEGATION_RESULT_LIMITED",
            "The delegated result reported material limitations; Main must account for them when integrating the evidence.",
            limitation_count=len(clean_result["limitations"]),
        ))
    # Reconcile from current reality after closing the isolation. The checkpoint is remembered
    # working state only and is never restored over the workspace.
    main = build_working(root, cwd, store, reconcile=True)
    return {
        "isolation": item,
        "warnings": store.isolation_warnings(str(isolation_id), limit=32),
        "main": main,
        "rule": "delegated result is evidence, not truth; current workspace reality wins",
    }


def abort_isolation(root: Path, cwd: Path, store: StateStore, isolation_id: str, reason: str) -> dict[str, Any]:
    store.ensure_active()
    active = store.active_isolation()
    if active is None:
        raise RuntimeError("no active isolated task")
    if str(active["isolation_id"]) != str(isolation_id):
        raise ValueError(f"wrong isolation_id: active isolation is {active['isolation_id']}")
    sync_generation(root, store)
    exit_generation = store.generation()
    item = store.abort_isolation(str(isolation_id), reason=reason, exit_generation=exit_generation)
    store.record_isolation_event(str(isolation_id), "warning", _warning(
        "DELEGATION_ABORTED",
        "The isolated task was aborted; the parent task remains active.",
        reason=_clean_text(reason, limit=4096, required=True),
    ))
    main = build_working(root, cwd, store, reconcile=True)
    return {"isolation": item, "warnings": store.isolation_warnings(str(isolation_id), limit=32), "main": main}
