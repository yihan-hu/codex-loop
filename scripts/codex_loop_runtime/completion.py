from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .change_tracker import changes, sync_generation
from .state import READ_ONLY_PROFILES, StateStore


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
    if generation > 0 and reviewed_generation != generation:
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
        },
    )
