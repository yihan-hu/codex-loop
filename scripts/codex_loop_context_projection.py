from __future__ import annotations

from pathlib import Path
from typing import Any

from codex_loop_runtime.change_tracker import changes, sync_generation
from codex_loop_runtime.completion import CompletionDecision, assess
from codex_loop_runtime.instructions import discover
from codex_loop_runtime.release_lineage import workspace_binding_status
from codex_loop_runtime.shell import default_user_shell
from codex_loop_runtime.state import StateStore
from codex_loop_runtime.workspace import git_state

MAX_REQUEST_CHARS = 12000
MAX_STEERS = 12
MAX_STEER_CHARS = 4096
MAX_PATHS = 32
MAX_REASONS = 10


def _bounded(value: Any, limit: int) -> tuple[str, int]:
    text = str(value or "")
    return (text, 0) if len(text) <= limit else (text[:limit], len(text) - limit)


def _steers(items: list[dict[str, Any]]) -> tuple[list[str], int]:
    result: list[str] = []
    omitted = max(0, len(items) - MAX_STEERS)
    for item in items[:MAX_STEERS]:
        text, clipped = _bounded(item.get("text", ""), MAX_STEER_CHARS)
        result.append(text)
        omitted += int(clipped > 0)
    return result, omitted


def _changed_paths(change_state: dict[str, Any]) -> tuple[list[str], int]:
    paths: list[str] = []
    for key in ("added", "modified", "deleted"):
        paths.extend(str(x) for x in change_state.get(key, []))
    for pair in change_state.get("renamed", []):
        paths.extend([str(pair.get("from", "")), str(pair.get("to", ""))])
    ordered = sorted({x for x in paths if x})
    return ordered[:MAX_PATHS], max(0, len(ordered) - MAX_PATHS)


def _validation_status(store: StateStore, generation: int, state: dict[str, Any]) -> str:
    if not bool(store.get_meta("requires_validation", False)):
        return "not_required"
    if int(state.get("passed_count", 0)):
        return "passed"
    latest = store.latest_validation()
    if latest is not None and int(latest.get("generation", -1)) != generation:
        return "stale"
    return "missing"


def collect_context(root: Path, cwd: Path, store: StateStore, *, reconcile: bool = True) -> dict[str, Any]:
    root = root.resolve()
    cwd = cwd.resolve()
    if reconcile:
        sync_generation(root, store)
    decision = assess(root, store, reconcile=False)
    generation = store.generation()
    change_state = decision.details.get("changes")
    if not isinstance(change_state, dict):
        change_state = changes(root, store)
    validation = decision.details.get("validation")
    if not isinstance(validation, dict):
        validation = store.validation_state_for_generation(generation)
    instruction_result = discover(cwd)
    return {
        "root": root,
        "cwd": cwd,
        "store": store,
        "generation": generation,
        "decision": decision,
        "changes": change_state,
        "validation": validation,
        "instructions": instruction_result,
        "shell": default_user_shell(),
        "criteria": store.criteria(),
        "request_steers": store.request_steers(),
        "external_actions": store.external_actions(),
        "processes": store.process_rows(),
        "active_isolation": store.active_isolation(),
        "isolation_history": store.isolation_history(limit=32),
        "warnings": store.isolation_warnings(limit=32),
        "workspace_binding": workspace_binding_status(root, store.get_meta("workspace_binding")),
        "release_receipts": store.release_receipts(),
    }


def full_projection(facts: dict[str, Any]) -> dict[str, Any]:
    store: StateStore = facts["store"]
    root: Path = facts["root"]
    cwd: Path = facts["cwd"]
    shell = facts["shell"]
    return {
        "task_id": store.task_id,
        "task_status": store.get_meta("task_status", "uninitialized"),
        "profile": store.get_meta("profile", "regular"),
        "request_anchor": store.request_anchor(),
        "request_steers": [str(x.get("text", "")) for x in facts["request_steers"]],
        "objective": store.get_meta("objective", ""),
        "acceptance": [str(x.get("text", "")) for x in facts["criteria"]],
        "plan": store.plan(),
        "generation": facts["generation"],
        "workspace": {
            "root": str(root),
            "cwd": str(cwd),
            "git": git_state(root),
            "binding": facts.get("workspace_binding"),
        },
        "instructions": {
            "entries": [
                {"path": item.path, "sha256": item.sha256, "complete": item.complete, "provenance": item.provenance}
                for item in facts["instructions"].entries
            ],
            "complete": facts["instructions"].complete,
            "truncated_paths": list(facts["instructions"].truncated_paths),
        },
        "changes": facts["changes"],
        "validation": facts["validation"],
        "processes": facts["processes"],
        "external_actions": facts["external_actions"],
        "release_receipts": facts.get("release_receipts", []),
        "completion": {
            "status": facts["decision"].status.value,
            "reasons": list(facts["decision"].reasons),
            "warnings": list(facts["decision"].details.get("warnings", [])),
        },
        "shell": {"type": shell.shell_type.value, "path": str(shell.shell_path)},
    }


def _next_actions(facts: dict[str, Any], validation_status: str) -> list[dict[str, str]]:
    store: StateStore = facts["store"]
    decision: CompletionDecision = facts["decision"]
    actions: list[dict[str, str]] = []

    def add(kind: str, action: str, reason: str) -> None:
        if not any(x["action"] == action for x in actions):
            actions.append({"kind": kind, "action": action, "reason": reason})

    if facts.get("active_isolation") is not None:
        add("required", "finish or abort the active isolated task", "delegated work is still active")
        return actions
    if facts["changes"].get("unexpected_protected_changes"):
        add("blocker", "reconcile protected user work", "pre-existing user changes were modified unexpectedly")
    if store.unresolved_external_count() or store.unresolved_external_failure_count():
        add("required", "reconcile unresolved external actions before further side effects", "external action state must be reconciled before continuation can safely dispatch another side effect")
    if store.running_process_count() or store.unresolved_process_failure_count():
        add("required", "clean up or reconcile managed processes", "task-owned process state is unresolved")
    plan = store.plan()
    current = next((x for x in plan if x["status"] == "in_progress"), None)
    pending = next((x for x in plan if x["status"] == "pending"), None)
    if current:
        add("work", current["step"], "current Codex-style plan step")
    elif pending:
        add("work", pending["step"], "next Codex-style plan step")
    if validation_status in {"missing", "stale"}:
        add("verify", "run the smallest relevant validation", f"validation is {validation_status}")
    if decision.status.value == "PASS":
        return [{
            "kind": "finish",
            "action": "perform one final semantic acceptance review, then finish if the user's objective is satisfied",
            "reason": "deterministic blockers are clear",
        }]
    if not actions:
        add("inspect", "continue the objective from current repository state", "the task is not yet ready to finish")
    return actions[:6]


def working_projection(facts: dict[str, Any]) -> dict[str, Any]:
    store: StateStore = facts["store"]
    decision: CompletionDecision = facts["decision"]
    anchor, anchor_omitted = _bounded(store.request_anchor(), MAX_REQUEST_CHARS)
    steers, steers_omitted = _steers(facts["request_steers"])
    changed, changed_omitted = _changed_paths(facts["changes"])
    validation_status = _validation_status(store, facts["generation"], facts["validation"])
    authority_reload_required = bool(anchor_omitted or steers_omitted)
    return {
        "context_version": 4,
        "task": {
            "task_id": store.task_id,
            "objective": store.get_meta("objective", ""),
            "profile": store.get_meta("profile", "regular"),
            "status": store.get_meta("task_status", "uninitialized"),
        },
        "request": {
            "anchor": anchor,
            "steers": steers,
            "truncated": bool(anchor_omitted or steers_omitted),
        },
        "acceptance": [str(x.get("text", "")) for x in facts["criteria"]],
        "plan": store.plan(),
        "state": {
            "completion": decision.status.value,
            "validation": validation_status,
            "changed_paths": changed,
            "completion_reasons": list(decision.reasons)[:MAX_REASONS],
            "warnings": list(decision.details.get("warnings", [])) + list(facts.get("warnings", []))[-4:],
        },
        "next_actions": _next_actions(facts, validation_status),
        "authority_reload_required": authority_reload_required,
        "resume_rule": "resume this same lifecycle: reload complete authority if truncated, inspect current repository/tool state, and do not redo completed work unless evidence is stale",
        "truncated": {
            "request_chars": anchor_omitted,
            "steers": steers_omitted,
            "changed_paths": changed_omitted,
            "completion_reasons": max(0, len(decision.reasons) - MAX_REASONS),
        },
    }


def build_lifecycle_working(store: StateStore, *, workspace_status: dict[str, Any] | None = None) -> dict[str, Any]:
    anchor, anchor_omitted = _bounded(store.request_anchor(), MAX_REQUEST_CHARS)
    steers, steers_omitted = _steers(store.request_steers())
    plan = store.plan()
    validation = store.validation_state_for_generation(store.generation())
    validation_status = _validation_status(store, store.generation(), validation)
    reasons: list[str] = []
    actions: list[dict[str, str]] = []
    workspace_status = workspace_status or {"bound": False, "available": False, "reason": "lifecycle has no workspace binding"}
    recovery_required = bool(workspace_status.get("recovery_required"))
    active_isolation = store.active_isolation()
    unresolved_external = store.unresolved_external_count() + store.unresolved_external_failure_count()
    unresolved_process = store.running_process_count() + store.unresolved_process_failure_count()
    validation_required = validation_status in {"missing", "stale"}
    unfinished_plan = [x for x in plan if x["status"] != "completed"]

    if recovery_required:
        reasons.append(str(workspace_status.get("reason") or "bound workspace requires recovery"))
        actions.append({
            "kind": "blocker",
            "action": "recover and verify the bound workspace, then rebind this same lifecycle",
            "reason": reasons[-1],
        })
    if active_isolation is not None:
        reasons.append("delegated work is still active")
        if not actions:
            actions.append({"kind": "required", "action": "finish or abort the active isolated task", "reason": reasons[-1]})
    if unresolved_external:
        reasons.append("external action state is unresolved")
        if not actions:
            actions.append({"kind": "required", "action": "reconcile unresolved external actions before further side effects", "reason": reasons[-1]})
    if unresolved_process:
        reasons.append("task-owned process state is unresolved")
        if not actions:
            actions.append({"kind": "required", "action": "clean up or reconcile managed processes", "reason": reasons[-1]})
    if unfinished_plan:
        reasons.append(f"plan has {len(unfinished_plan)} unfinished step(s)")
    if validation_required:
        reasons.append(f"validation is {validation_status}")

    current = next((x for x in plan if x["status"] == "in_progress"), None)
    pending = next((x for x in plan if x["status"] == "pending"), None)
    if not actions and current:
        actions.append({"kind": "work", "action": current["step"], "reason": "current Codex-style plan step"})
    elif not actions and pending:
        actions.append({"kind": "work", "action": pending["step"], "reason": "next Codex-style plan step"})
    if validation_required and not actions:
        actions.append({"kind": "verify", "action": "run the smallest relevant validation", "reason": f"validation is {validation_status}"})
    if not actions:
        actions.append({
            "kind": "finish",
            "action": "perform one final semantic acceptance review, then finish if the user's objective is satisfied",
            "reason": "no modeled deterministic blocker is active",
        })
    authority_reload_required = bool(anchor_omitted or steers_omitted)
    return {
        "context_version": 4,
        "task": {
            "task_id": store.task_id,
            "objective": store.get_meta("objective", ""),
            "profile": store.get_meta("profile", "regular"),
            "status": store.get_meta("task_status", "uninitialized"),
        },
        "request": {"anchor": anchor, "steers": steers, "truncated": authority_reload_required},
        "acceptance": [str(x.get("text", "")) for x in store.criteria()],
        "plan": plan,
        "workspace": workspace_status,
        "state": {
            "completion": "BLOCKED" if recovery_required else ("CONTINUE" if reasons else "PASS"),
            "validation": validation_status,
            "changed_paths": [],
            "completion_reasons": reasons,
            "warnings": list(validation.get("warning_codes", [])),
        },
        "next_actions": actions[:6],
        "authority_reload_required": authority_reload_required,
        "resume_rule": "resume this same lifecycle: reload complete authority if truncated, recover current external reality, and do not re-bootstrap or redo completed work",
        "truncated": {
            "request_chars": anchor_omitted,
            "steers": steers_omitted,
            "changed_paths": 0,
            "completion_reasons": 0,
        },
    }


def _delegation_record_view(item: dict[str, Any] | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "isolation_id": item.get("isolation_id"),
        "role": item.get("role"),
        "status": item.get("status"),
        "requested_executor": item.get("requested_executor"),
        "actual_executor": item.get("actual_executor"),
        "missing_capabilities": list(item.get("missing_capabilities") or []),
        "mutation_policy": item.get("mutation_policy"),
    }


def isolation_projection(facts: dict[str, Any], isolation: dict[str, Any]) -> dict[str, Any]:
    role = str(isolation.get("role", "reviewer"))
    context_spec = isolation.get("context_spec") or {}
    projected = context_spec.get("projected_context") or {}
    actual = isolation.get("actual_capabilities") or {}
    return {
        "context_version": 2,
        "isolation_id": isolation.get("isolation_id"),
        "status": isolation.get("status"),
        "role": role,
        "objective": isolation.get("objective"),
        "executor": {
            "kind": isolation.get("actual_executor"),
            "physical_context_isolation": bool(actual.get("physical_context_isolation", False)),
            "behavioral_context_isolation": bool(actual.get("behavioral_context_isolation", False)),
        },
        "projected_context": {
            "files": list(projected.get("files", []))[:64],
            "facts": list(projected.get("facts", []))[:48],
            "criteria_refs": list(projected.get("criteria_refs", []))[:32],
        },
        "guardrails": ["read-only", "re-observe evidence independently", "return actionable findings only"],
        "result_contract": {
            "fields": ["summary", "findings", "recommended_action", "files_inspected", "limitations"],
            "delegated_result_semantics": "evidence_not_truth",
        },
    }


def build_isolation(root: Path, cwd: Path, store: StateStore, isolation_id: str, *, reconcile: bool = True) -> dict[str, Any]:
    facts = collect_context(root, cwd, store, reconcile=reconcile)
    isolation = store.isolation(isolation_id)
    if isolation is None:
        raise ValueError(f"unknown isolation: {isolation_id}")
    return isolation_projection(facts, isolation)


def build_full(root: Path, cwd: Path, store: StateStore, *, reconcile: bool = True) -> dict[str, Any]:
    return full_projection(collect_context(root, cwd, store, reconcile=reconcile))


def build_working(root: Path, cwd: Path, store: StateStore, *, reconcile: bool = True) -> dict[str, Any]:
    return working_projection(collect_context(root, cwd, store, reconcile=reconcile))
