from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .change_tracker import changes, sync_generation
from .release_lineage import workspace_binding_status
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
    """Check only deterministic finish blockers.

    Semantic acceptance belongs to the model's final review. This function deliberately does not
    duplicate that review with criterion evidence, fresh-PASS counters, or an outer objective audit.
    """
    binding = store.get_meta("workspace_binding")
    if reconcile and binding is not None:
        sync_generation(root, store)

    task_status = str(store.get_meta("task_status", "uninitialized"))
    if task_status == "cancelled":
        return CompletionDecision(CompletionStatus.BLOCKED, ("task is cancelled",), {"task_status": task_status})
    if task_status != "active":
        return CompletionDecision(
            CompletionStatus.BLOCKED,
            (f"task is not active: {task_status}",),
            {"task_status": task_status},
        )

    blockers: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []
    generation = store.generation()

    if not store.request_anchor().strip():
        blockers.append("task request anchor is missing")

    plan = store.plan()
    unfinished = [item for item in plan if item["status"] != "completed"]
    if unfinished:
        reasons.append(f"plan has {len(unfinished)} unfinished step(s)")

    validation_state = store.validation_state_for_generation(generation)
    warnings.extend(str(code) for code in validation_state.get("warning_codes", []) if str(code))
    requires_validation = bool(store.get_meta("requires_validation", False))
    if requires_validation and int(validation_state.get("passed_count", 0)) < 1:
        reasons.append("no current validation pass is recorded")
    if int(validation_state.get("failed_count", 0)):
        warnings.append("current validation also contains failing checks; inspect relevance before finishing")
    if int(validation_state.get("cleanup_failed_count", 0)) or int(validation_state.get("orphaned_count", 0)):
        blockers.append("validation process cleanup/orphan state is unresolved")
    if bool(store.get_meta("requires_clean_process_exit", False)) and int(validation_state.get("teardown_stalled_count", 0)):
        reasons.append("the request requires clean process exit and validation teardown stalled")

    active_isolation = store.active_isolation()
    if active_isolation is not None:
        reasons.append(f"active isolated task {active_isolation.get('isolation_id')} has not finished")

    unresolved_external = store.unresolved_external_count()
    unresolved_external_failures = store.unresolved_external_failure_count()
    if unresolved_external:
        reasons.append(f"{unresolved_external} external action outcome(s) are unresolved")
    if unresolved_external_failures:
        reasons.append(f"{unresolved_external_failures} external action failure(s) are unresolved")
    if store.ambiguous_non_idempotent_identity_count():
        blockers.append("non-idempotent external action identity is ambiguous")

    running_processes = store.running_process_count()
    unresolved_process_failures = store.unresolved_process_failure_count()
    if running_processes:
        reasons.append(f"{running_processes} managed process(es) still need cleanup")
    if unresolved_process_failures:
        reasons.append(f"{unresolved_process_failures} managed process failure(s) are unresolved")

    if binding is not None:
        binding_status = workspace_binding_status(root, binding)
        if not binding_status.get("matches"):
            blockers.append("canonical workspace binding no longer matches the current Git worktree")
        change_state = changes(root, store)
        if change_state.get("unexpected_protected_changes"):
            blockers.append("protected pre-existing user changes were modified outside the runtime journal")
        profile = str(store.get_meta("profile", "regular"))
        changed_any = bool(
            change_state.get("added") or change_state.get("modified")
            or change_state.get("deleted") or change_state.get("renamed")
        )
        if profile in READ_ONLY_PROFILES and changed_any:
            blockers.append(f"read-only task profile {profile} observed workspace changes")
        if profile == "command_only" and changed_any:
            blockers.append("command_only profile observed workspace changes")
        if change_state.get("git", {}).get("probe_degraded"):
            warnings.append("Git observation is degraded")
    else:
        binding_status = {"bound": False, "matches": True, "reason": "lifecycle has no workspace binding"}
        change_state = {
            "root": None, "generation": generation, "tracking_active": False,
            "added": [], "modified": [], "deleted": [], "renamed": [],
            "protected_paths": [], "agent_owned_paths": [], "unexpected_protected_changes": [],
            "ignored_watch": {"watched_paths": [], "opaque_paths": []}, "git": {"is_git": False},
        }

    status = CompletionStatus.BLOCKED if blockers else (CompletionStatus.CONTINUE if reasons else CompletionStatus.PASS)
    return CompletionDecision(
        status,
        tuple(blockers + reasons),
        {
            "generation": generation,
            "plan": plan,
            "validation": validation_state,
            "changes": change_state,
            "workspace_binding": binding_status,
            "active_isolation": active_isolation,
            "unresolved_external": unresolved_external,
            "unresolved_external_failures": unresolved_external_failures,
            "running_processes": running_processes,
            "unresolved_process_failures": unresolved_process_failures,
            "warnings": warnings,
            "latest_release": store.latest_release_receipt(),
        },
    )
