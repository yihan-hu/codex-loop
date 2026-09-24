from __future__ import annotations

from pathlib import Path
from typing import Any

from codex_loop_runtime.change_tracker import changes, sync_generation
from codex_loop_runtime.completion import CompletionStatus, assess
from codex_loop_runtime.instructions import discover
from codex_loop_runtime.release_lineage import workspace_binding_status
from codex_loop_runtime.shell import default_user_shell
from codex_loop_runtime.state import StateStore
from codex_loop_runtime.workspace import git_state, workspace_identity_status

MAX_REQUEST_CHARS = 12000
MAX_STEERS = 12
MAX_STEER_CHARS = 4096
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


CONTINUATION_CONTRACT = (
    "Keep the exact request plus later steers as the objective; do not shrink it to what fits this turn.",
    "Work from current repository, tool, process, and external state; re-observe anything that may have gone stale.",
    "Make concrete progress toward the real requested end state; status restatements and unexecuted plan updates are not progress.",
    "If task-owned work is confirmed live, observe the existing handle instead of restarting it; an observation timeout is not terminal evidence.",
    "Repair resolvable failures and continue; use blocked only for a genuine impasse with no remaining safe useful work.",
    "Treat completion as unproven: derive material requirements from the request, verify each against current authoritative evidence, then run the smallest relevant validation.",
)


def _task_board(plan: list[dict[str, str]]) -> dict[str, list[str]]:
    return {
        "doing": [item["step"] for item in plan if item["status"] == "in_progress"],
        "pending": [item["step"] for item in plan if item["status"] == "pending"],
        "done": [item["step"] for item in plan if item["status"] == "completed"],
    }


def _continuation_state(store: StateStore) -> dict[str, Any]:
    status = store.task_status()
    mode = {
        "active": "execute",
        "paused": "paused",
        "blocked": "blocked",
        "complete": "terminal",
        "cancelled": "terminal",
    }[status]
    result: dict[str, Any] = {
        "mode": mode,
        "resumable": status in {"active", "paused", "blocked"},
    }
    if status == "blocked":
        result["blocked_reason"] = store.get_meta("blocked_reason")
    return result


def _live_work_projection(store: StateStore) -> dict[str, Any] | None:
    rows = store.live_process_rows()
    if not rows:
        return None
    return {
        "mode": "verified_wait",
        "processes": [
            {"handle": row.get("handle"), "state": row.get("state"), "pid": row.get("pid"), "cwd": row.get("cwd")}
            for row in rows[:8]
        ],
        "rule": "observe these existing handles; do not restart solely because a prior observation timed out",
    }


def _validation_status(store: StateStore, generation: int, state: dict[str, Any]) -> str:
    if not bool(store.get_meta("requires_validation", False)):
        return "not_required"
    if int(state.get("passed_count", 0)):
        return "passed"
    latest = store.latest_validation()
    if latest is not None and int(latest.get("generation", -1)) != generation:
        return "stale"
    return "missing"


def collect_context(
    root: Path,
    cwd: Path,
    store: StateStore,
    *,
    reconcile: bool = False,
    deep_workspace: bool = False,
    include_instructions: bool = True,
) -> dict[str, Any]:
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
    instruction_result = discover(cwd) if include_instructions else None
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
        "request_steers": store.request_steers(),
        "external_actions": store.external_actions(),
        "processes": store.process_rows(),
        "active_isolation": store.active_isolation(),
        "isolation_history": store.isolation_history(limit=32),
        "warnings": store.isolation_warnings(limit=32),
        "workspace_binding": (
            workspace_binding_status(root, store.get_meta("workspace_binding"))
            if deep_workspace else workspace_identity_status(root, store.get_meta("workspace_binding"))
        ),
        "release_receipts": store.release_receipts(),
    }


def full_projection(facts: dict[str, Any]) -> dict[str, Any]:
    """Diagnostic/debug projection. This is intentionally richer than normal agent context."""
    store: StateStore = facts["store"]
    root: Path = facts["root"]
    cwd: Path = facts["cwd"]
    shell = facts["shell"]
    instructions = facts.get("instructions")
    instruction_payload = None
    if instructions is not None:
        instruction_payload = {
            "entries": [
                {"path": item.path, "sha256": item.sha256, "complete": item.complete, "provenance": item.provenance}
                for item in instructions.entries
            ],
            "complete": instructions.complete,
            "truncated_paths": list(instructions.truncated_paths),
        }
    return {
        "task_id": store.task_id,
        "task_status": store.task_status(),
        "profile": store.get_meta("profile", "regular"),
        "request_anchor": store.request_anchor(),
        "request_steers": [str(x.get("text", "")) for x in facts["request_steers"]],
        "plan": store.plan(),
        "generation": facts["generation"],
        "workspace": {
            "root": str(root),
            "cwd": str(cwd),
            "git": git_state(root),
            "binding": facts.get("workspace_binding"),
        },
        "instructions": instruction_payload,
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


def _request_projection(store: StateStore) -> tuple[dict[str, Any], bool, dict[str, int]]:
    anchor, anchor_omitted = _bounded(store.request_anchor(), MAX_REQUEST_CHARS)
    steers, steers_omitted = _steers(store.request_steers())
    truncated = bool(anchor_omitted or steers_omitted)
    return (
        {"anchor": anchor, "steers": steers, "truncated": truncated},
        truncated,
        {"request_chars": anchor_omitted, "steers": steers_omitted},
    )


def _base_working_projection(store: StateStore) -> dict[str, Any]:
    request, reload_required, truncated = _request_projection(store)
    result: dict[str, Any] = {
        "context_version": 6,
        "task": {
            "task_id": store.task_id,
            "profile": store.get_meta("profile", "regular"),
            "status": store.task_status(),
        },
        "request": request,
        "continuation": _continuation_state(store),
        "continuation_contract": list(CONTINUATION_CONTRACT),
        "authority_reload_required": reload_required,
        "resume_rule": (
            "resume this same lifecycle; a plain user continue is not a steer; reload complete authority if truncated; "
            "re-observe stale reality and existing live work before starting replacements"
        ),
        "truncated": truncated,
    }
    plan = store.plan()
    if plan:
        result["plan"] = plan
        result["task_board"] = _task_board(plan)
    return result


def working_projection(facts: dict[str, Any]) -> dict[str, Any]:
    store: StateStore = facts["store"]
    decision = facts["decision"]
    result = _base_working_projection(store)
    result["workspace"] = {"root": str(facts["root"]), "cwd": str(facts["cwd"])}
    instructions = facts.get("instructions")
    if instructions is not None:
        result["workspace"]["instructions"] = {
            "entries": [
                {
                    "path": item.path,
                    "sha256": item.sha256,
                    "complete": item.complete,
                    "provenance": item.provenance,
                    "contents": item.contents,
                }
                for item in instructions.entries
            ],
            "complete": instructions.complete,
            "truncated_paths": list(instructions.truncated_paths),
        }
    blockers = list(decision.reasons)[:MAX_REASONS]
    warnings = list(decision.details.get("warnings", [])) + list(facts.get("warnings", []))[-4:]
    result["machine"] = {
        "blockers_clear": decision.status == CompletionStatus.PASS,
        "blockers": blockers,
        "warnings": warnings,
    }
    live_work = _live_work_projection(store)
    if live_work is not None:
        result["live_work"] = live_work
    result["truncated"]["machine_blockers"] = max(0, len(decision.reasons) - MAX_REASONS)
    return result


def build_lifecycle_working(store: StateStore, *, workspace_status: dict[str, Any] | None = None) -> dict[str, Any]:
    result = _base_working_projection(store)
    workspace_status = workspace_status or {
        "bound": False,
        "available": False,
        "recovery_required": False,
        "reason": "lifecycle has no workspace binding",
    }
    blockers: list[str] = []
    warnings: list[str] = []
    if workspace_status.get("recovery_required"):
        blockers.append(str(workspace_status.get("reason") or "bound workspace requires recovery"))
    if store.active_isolation() is not None:
        blockers.append("delegated work is still active")
    if store.unresolved_external_count() or store.unresolved_external_failure_count():
        blockers.append("external action state is unresolved")
    live_processes = store.live_process_rows()
    if live_processes:
        blockers.append(f"{len(live_processes)} task-owned process(es) are still live")
        result["live_work"] = _live_work_projection(store)
    if store.orphaned_process_count() or store.unresolved_process_failure_count():
        blockers.append("task-owned process state requires reconciliation")
    validation = store.validation_state_for_generation(store.generation())
    validation_status = _validation_status(store, store.generation(), validation)
    if validation_status in {"missing", "stale"}:
        blockers.append(f"required validation is {validation_status}")
    warnings.extend(str(x) for x in validation.get("warning_codes", []) if str(x))
    result["workspace"] = workspace_status
    result["machine"] = {
        "blockers_clear": not blockers,
        "blockers": blockers[:MAX_REASONS],
        "warnings": warnings,
    }
    result["truncated"]["machine_blockers"] = max(0, len(blockers) - MAX_REASONS)
    return result


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
    semantic = isolation.get("semantic_work")
    result = {
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
    if semantic is not None:
        result["semantic_work"] = {
            "consumer": semantic.get("consumer"),
            "stage": semantic.get("stage"),
            "input_sha256": semantic.get("input_sha256"),
            "instruction_sha256": semantic.get("instruction_sha256"),
            "request_sha256": semantic.get("request_sha256"),
            "authority": "logical_isolation_only",
        }
        result["guardrails"] = [
            "read-only",
            "perform the semantic judgment inside this logical isolation",
            "do not use scripts, templates, loops, or prefilled verdicts to manufacture the semantic result",
            "return only the owning domain stage result",
        ]
        result["result_contract"] = {
            "fields": "defined by the owning domain stage",
            "semantic_result_semantics": "authority exists only after semantic-work-finish mints semantic_result_id",
        }
    return result


def build_isolation(root: Path, cwd: Path, store: StateStore, isolation_id: str, *, reconcile: bool = True) -> dict[str, Any]:
    facts = collect_context(root, cwd, store, reconcile=reconcile)
    isolation = store.isolation(isolation_id)
    if isolation is None:
        raise ValueError(f"unknown isolation: {isolation_id}")
    semantic = store.semantic_work_for_isolation(isolation_id)
    if semantic is not None:
        isolation["semantic_work"] = semantic
    return isolation_projection(facts, isolation)


def build_full(root: Path, cwd: Path, store: StateStore, *, reconcile: bool = True) -> dict[str, Any]:
    return full_projection(collect_context(root, cwd, store, reconcile=reconcile, deep_workspace=True, include_instructions=True))


def build_working(root: Path, cwd: Path, store: StateStore, *, reconcile: bool = False) -> dict[str, Any]:
    return working_projection(collect_context(root, cwd, store, reconcile=reconcile, deep_workspace=True, include_instructions=True))
