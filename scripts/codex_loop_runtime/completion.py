from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import Path
from typing import Any

from .change_tracker import changes, sync_generation
from .release_lineage import workspace_binding_status
from .state import READ_ONLY_PROFILES, StateStore, scrub_persisted_text


OBJECTIVE_AUDIT_STATUSES = {"proven", "contradicted", "incomplete", "weak", "missing"}
UPSTREAM_GOAL_CONTINUATION_BLOB = "62391c523cab01022a32c6bb685292ed1e8d3205"


def _objective_sha256(objective: str) -> str:
    return hashlib.sha256(str(objective).encode("utf-8")).hexdigest()


def record_objective_audit(store: StateStore, payload: Any) -> dict[str, Any]:
    """Record an upstream-style objective completion audit without domain-specific semantics."""
    store.ensure_active()
    requirements = payload.get("requirements") if isinstance(payload, dict) else payload
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("objective audit requires a non-empty requirements array")
    if len(requirements) > 256:
        raise ValueError("objective audit exceeds the 256 requirement limit")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(requirements):
        if not isinstance(item, dict):
            raise ValueError(f"objective audit requirement {index} must be an object")
        requirement = (scrub_persisted_text(str(item.get("requirement", "")), limit=4096) or "").strip()
        status = str(item.get("status", "")).strip().lower()
        evidence = (scrub_persisted_text(str(item.get("evidence", "")), limit=4096) or "").strip()
        source = (scrub_persisted_text(str(item.get("authoritative_source", "")), limit=2048) or "").strip()
        if not requirement:
            raise ValueError(f"objective audit requirement {index} is missing requirement text")
        if status not in OBJECTIVE_AUDIT_STATUSES:
            raise ValueError(
                f"objective audit requirement {index} has invalid status {status!r}; "
                f"expected one of {sorted(OBJECTIVE_AUDIT_STATUSES)}"
            )
        if status == "proven" and not evidence:
            raise ValueError(f"objective audit requirement {index} is proven without evidence")
        if status == "proven" and not source:
            raise ValueError(f"objective audit requirement {index} is proven without an authoritative source")
        normalized.append({
            "ordinal": index,
            "requirement": requirement,
            "status": status,
            "evidence": evidence,
            "authoritative_source": source,
        })

    objective = str(store.get_meta("objective", "") or "")
    audit = {
        "version": 1,
        "upstream_blob": UPSTREAM_GOAL_CONTINUATION_BLOB,
        "objective_sha256": _objective_sha256(objective),
        "generation": store.generation(),
        "plan_revision": int(store.get_meta("plan_revision", 0)),
        "requirements": normalized,
    }
    store.set_meta("objective_completion_audit", audit)
    return audit


def _objective_audit_state(store: StateStore, generation: int) -> dict[str, Any]:
    audit = store.get_meta("objective_completion_audit")
    reasons: list[str] = []
    unresolved: list[dict[str, Any]] = []
    if not isinstance(audit, dict):
        return {
            "required": True,
            "present": False,
            "fresh": False,
            "pass": False,
            "reasons": ["objective completion audit has not been recorded"],
            "requirements": [],
            "unresolved": [],
        }

    objective = str(store.get_meta("objective", "") or "")
    if str(audit.get("objective_sha256", "")) != _objective_sha256(objective):
        reasons.append("objective completion audit does not match the current objective")
    if int(audit.get("generation", -1)) != int(generation):
        reasons.append(f"objective completion audit is stale for generation {generation}")
    if int(audit.get("plan_revision", -1)) != int(store.get_meta("plan_revision", 0)):
        reasons.append("objective completion audit predates the current user steer/plan revision")

    requirements = audit.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        requirements = []
        reasons.append("objective completion audit has no requirements")
    else:
        for index, item in enumerate(requirements):
            if not isinstance(item, dict):
                unresolved.append({"ordinal": index, "status": "invalid", "requirement": "<invalid>"})
                continue
            requirement = str(item.get("requirement", "")).strip()
            status = str(item.get("status", "")).strip().lower()
            evidence = str(item.get("evidence", "")).strip()
            source = str(item.get("authoritative_source", "")).strip()
            if status != "proven" or not requirement or not evidence or not source:
                unresolved.append({
                    "ordinal": index,
                    "status": status or "missing",
                    "requirement": requirement or "<missing requirement>",
                })
        if unresolved:
            reasons.append("one or more objective requirements are not proven by authoritative evidence")

    fresh = not any("does not match" in x or "stale" in x or "predates" in x for x in reasons)
    passed = bool(requirements) and not reasons and not unresolved
    return {
        "required": True,
        "present": True,
        "fresh": fresh,
        "pass": passed,
        "reasons": reasons,
        "requirements": requirements,
        "unresolved": unresolved,
        "generation": audit.get("generation"),
        "plan_revision": audit.get("plan_revision"),
        "upstream_blob": audit.get("upstream_blob"),
    }


class CompletionStatus(str, Enum):
    PASS = "PASS"
    CONTINUE = "CONTINUE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CompletionDecision:
    status: CompletionStatus
    reasons: tuple[str, ...]
    details: dict[str, Any]


def assess(root: Path, store: StateStore, *, reconcile: bool = True) -> CompletionDecision:
    if reconcile:
        sync_generation(root, store)
    status = str(store.get_meta("task_status", "uninitialized"))
    if status == "cancelled":
        return CompletionDecision(CompletionStatus.BLOCKED, ("task is cancelled",), {"task_status": status})
    if status != "active":
        return CompletionDecision(CompletionStatus.BLOCKED, (f"task is not active: {status}",), {"task_status": status})

    reasons: list[str] = []
    blockers: list[str] = []
    generation = store.generation()
    active_isolation = store.active_isolation()
    if active_isolation is not None:
        reasons.append(
            f"active isolated task {active_isolation.get('isolation_id')} has not finished"
        )
    delegation_warnings = store.isolation_warnings(limit=32)
    criteria = store.criteria()
    if not criteria:
        blockers.append("task has no acceptance criterion")
    for item in criteria:
        state = str(item.get("status", "pending"))
        evidence = str(item.get("evidence") or "").strip()
        if state == "blocked":
            blockers.append(f"criterion {item['ordinal']} is blocked")
        elif state != "pass":
            reasons.append(f"criterion {item['ordinal']} is {state}")
        elif not evidence:
            reasons.append(f"criterion {item['ordinal']} passed without evidence")
        elif int(item.get("evidence_generation") if item.get("evidence_generation") is not None else -1) != generation:
            reasons.append(f"criterion {item['ordinal']} evidence is stale for generation {generation}")

    objective_audit_required = bool(store.get_meta("requires_objective_completion_audit", False))
    if objective_audit_required:
        objective_audit = _objective_audit_state(store, generation)
        if not objective_audit["pass"]:
            reasons.extend(str(x) for x in objective_audit["reasons"])
    else:
        objective_audit = {
            "required": False,
            "present": False,
            "fresh": True,
            "pass": True,
            "reasons": [],
            "requirements": [],
            "unresolved": [],
        }

    if store.pending_steers():
        reasons.append("one or more user steers are pending integration")
    stale_steers = store.stale_steers()
    if stale_steers:
        reasons.append("one or more acknowledged user steers have stale integration evidence")

    validation_state = store.validation_state_for_generation(generation)
    if bool(store.get_meta("requires_validation", True)):
        if validation_state["passed_count"] < 1:
            if validation_state.get("legacy_identity_count", 0):
                reasons.append("legacy validation record(s) lack cwd-aware identity and must be rerun")
            reasons.append("no current-generation passing validation is recorded")
        if validation_state["failed_count"]:
            reasons.append("current-generation validation has unresolved blocking failure(s)")
    elif not str(store.get_meta("no_validation_reason", "") or "").strip():
        blockers.append("validation is disabled without a recorded reason")

    unresolved_external = store.unresolved_external_count()
    if unresolved_external:
        reasons.append(f"{unresolved_external} external action outcome(s) are unresolved")
    unresolved_external_failures = store.unresolved_external_failure_count()
    if unresolved_external_failures:
        reasons.append(f"{unresolved_external_failures} external action failure(s) are not yet resolved with evidence")
    ambiguous_external_identities = store.ambiguous_non_idempotent_identity_count()
    if ambiguous_external_identities:
        blockers.append(
            f"{ambiguous_external_identities} legacy non-idempotent external identity collision(s) require external-state inspection before this task can be trusted"
        )
    running_processes = store.running_process_count()
    if running_processes:
        reasons.append(f"{running_processes} managed process record(s) are running, draining, or orphaned")
    unresolved_process_failures = store.unresolved_process_failure_count()
    if unresolved_process_failures:
        reasons.append(f"{unresolved_process_failures} managed process failure(s) are unresolved")

    binding = store.get_meta("workspace_binding")
    if binding is not None:
        binding_status = workspace_binding_status(root, binding)
        if not binding_status.get("matches"):
            blockers.append("canonical workspace binding no longer matches the task's bound Git working tree")
    else:
        binding_status = {"bound": False, "matches": False, "reason": "legacy task without canonical workspace binding"}

    change_state = changes(root, store)
    opaque_paths = sorted(str(x) for x in change_state.get("ignored_watch", {}).get("opaque_paths", []))
    freshness_waiver = store.freshness_waiver()
    if opaque_paths:
        waiver_ok = bool(
            freshness_waiver
            and int(freshness_waiver.get("generation", -1)) == generation
            and sorted(str(x) for x in freshness_waiver.get("opaque_paths", [])) == opaque_paths
            and str(freshness_waiver.get("reason") or "").strip()
        )
        if not waiver_ok:
            blockers.append("opaque ignored path(s) prevent a complete freshness guarantee; record an explicit current-generation freshness waiver or make them observable")
    if change_state["unexpected_protected_changes"]:
        blockers.append("protected pre-existing user changes were modified outside the runtime journal")
    profile = str(store.get_meta("profile", "regular"))
    changed_any = bool(change_state["added"] or change_state["modified"] or change_state["deleted"] or change_state["renamed"])
    if profile in READ_ONLY_PROFILES and changed_any:
        blockers.append(f"read-only task profile {profile} observed workspace changes")
    if profile == "command_only" and changed_any:
        blockers.append("command_only profile observed workspace changes")

    git = change_state["git"]
    if git.get("probe_degraded"):
        reasons.append("Git state observation is degraded; refresh Git probes before completion")
    scope = store.get_meta("git_mutation_scope", {}) or {}
    if not isinstance(scope, dict):
        scope = {}
    if git.get("head_changed") and not bool(scope.get("head")):
        blockers.append("Git HEAD changed without explicit HEAD authorization")
    if git.get("branch_changed") and not bool(scope.get("branch")):
        blockers.append("Git branch changed without explicit branch authorization")
    if git.get("index_changed_from_baseline") and not bool(scope.get("index")):
        blockers.append("Git index changed without explicit index authorization")
    if any(bool(scope.get(k)) for k in ("head", "branch", "index")) and not str(store.get_meta("git_mutation_reason", "") or "").strip():
        blockers.append("Git mutation authorization is missing its reason")

    reviewed_generation = int(store.get_meta("changes_reviewed_generation", -1))
    if changed_any and reviewed_generation != generation:
        reasons.append("final changes have not been reviewed at the current generation")

    if blockers:
        result = CompletionStatus.BLOCKED
    elif reasons:
        result = CompletionStatus.CONTINUE
    else:
        result = CompletionStatus.PASS
    return CompletionDecision(
        result,
        tuple(blockers + reasons),
        {
            "generation": generation,
            "criteria": criteria,
            "objective_audit": objective_audit,
            "validation": validation_state,
            "reviewed_generation": reviewed_generation,
            "unresolved_external": unresolved_external,
            "unresolved_external_failures": unresolved_external_failures,
            "ambiguous_external_identities": ambiguous_external_identities,
            "running_processes": running_processes,
            "unresolved_process_failures": unresolved_process_failures,
            "stale_steers": stale_steers,
            "no_validation_reason": store.get_meta("no_validation_reason"),
            "changes": change_state,
            "freshness_waiver": freshness_waiver,
            "active_isolation": active_isolation,
            "warnings": delegation_warnings,
            "workspace_binding": binding_status,
            "latest_release": store.latest_release_receipt(),
        },
    )
