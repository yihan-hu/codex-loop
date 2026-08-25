#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from codex_loop_runtime.change_tracker import capture_baseline, changes, sync_generation
from codex_loop_runtime.checkpoint import create as create_checkpoint, restore as restore_checkpoint
from codex_loop_runtime.command_identity import identify
from codex_loop_runtime.command_safety import assess as assess_command
from codex_loop_runtime.completion import CompletionStatus, assess as assess_completion
from codex_loop_runtime.instructions import discover
from codex_loop_runtime.process_manager import managed_session_capability, run_one_shot
from codex_loop_runtime.protocol import emit_error, emit_ok
from codex_loop_runtime.service import request as service_request, serve as service_serve, start as service_start
from codex_loop_runtime.shell_snapshot import capture_plan as shell_snapshot_plan
from codex_loop_runtime.state import (
    active_task_id, create_store, open_store, root_state_dir, set_active_task,
    state_dir_for, validate_task_id, scrub_persisted_text,
)
from codex_loop_runtime.upstream_verify import verify as verify_upstream
from codex_loop_runtime.validation import validate
from codex_loop_runtime.workspace import hash_file, hash_workspace_path, repo_root
from codex_loop_runtime.world_state import build as build_world_state
from codex_loop_runtime.write_transaction import MAX_LOCAL_WRITE_BYTES, guarded_write


def _cwd(raw: str | None) -> Path:
    return Path(raw or os.getcwd()).resolve()


def _root(args: argparse.Namespace) -> tuple[Path, Path]:
    cwd = _cwd(getattr(args, "cwd", None))
    return cwd, repo_root(cwd)


def _store(args: argparse.Namespace, *, create: bool = False):
    cwd, root = _root(args)
    if create:
        store = create_store(root, task_id=getattr(args, "task_id", None))
    else:
        task_id = getattr(args, "task_id", None)
        if not task_id:
            if getattr(args, "use_active_task", False):
                task_id = active_task_id(root)
            else:
                raise RuntimeError("explicit --task-id is required for task-scoped runtime commands; --use-active-task is human CLI convenience only")
        store = open_store(root, task_id)
    return cwd, root, store


def _command(raw: list[str]) -> list[str]:
    values = list(raw)
    if values and values[0] == "--":
        values = values[1:]
    if not values:
        raise ValueError("a command is required after --")
    return values


def cmd_bootstrap(args: argparse.Namespace) -> None:
    cwd, root = _root(args)
    if args.task_id:
        task_id = validate_task_id(args.task_id)
        existing = root_state_dir(root) / "tasks" / task_id
        if existing.exists() or existing.is_symlink():
            raise RuntimeError(f"task_id already exists and cannot be reset by bootstrap: {task_id}")
    store = create_store(root, task_id=args.task_id)
    task_id = store.path.parent.name
    try:
        store.configure_task(
            task_id, args.objective, args.criterion or [], profile=args.profile,
            requires_validation=not args.no_validation,
            git_mutation_reason=args.git_mutation_reason,
            git_mutation_scope={"head": args.allow_git_head, "branch": args.allow_git_branch, "index": args.allow_git_index},
            no_validation_reason=args.no_validation_reason,
        )
        count = capture_baseline(root, store)
        set_active_task(root, task_id)
    except Exception:
        shutil.rmtree(store.path.parent, ignore_errors=True)
        raise
    emit_ok({
        "task_id": task_id,
        "root": root,
        "state": store.path,
        "baseline_files": count,
        "world_state": build_world_state(root, cwd, store, reconcile=False),
    })


def cmd_snapshot(args: argparse.Namespace) -> None:
    cwd, root, store = _store(args)
    emit_ok(build_world_state(root, cwd, store))


def cmd_instructions(args: argparse.Namespace) -> None:
    cwd, _root_path, _store_obj = _store(args)
    emit_ok([x.__dict__ for x in discover(cwd, fallback_filenames=tuple(args.fallback or []))])


def cmd_command_check(args: argparse.Namespace) -> None:
    cwd = _cwd(getattr(args, "cwd", None))
    argv = _command(args.command)
    emit_ok({"safety": assess_command(argv), "identity": identify(argv, cwd), "cwd": str(cwd)})


def cmd_exec(args: argparse.Namespace) -> None:
    cwd, _root_path, store = _store(args)
    store.ensure_active()
    argv = _command(args.command)
    safety = assess_command(argv)
    if safety.classification.value != "safe_known":
        emit_ok({
            "executed": False,
            "requires_host_visible_execution": True,
            "safety": safety,
            "identity": identify(argv, cwd),
            "reason": "local runtime only executes narrow deterministic primitives; run this exact command through a host-visible tool path",
        })
        return
    result = run_one_shot(
        argv, cwd, timeout=args.timeout,
        transcript_dir=store.path.parent / "exec-transcripts",
    )
    emit_ok({"executed": True, "safety": safety, "identity": identify(argv, cwd), "result": result})


def cmd_validate(args: argparse.Namespace) -> None:
    cwd_path, root, store = _store(args)
    store.ensure_active()
    argv = _command(args.command)
    safety = assess_command(argv)
    if safety.classification.value != "safe_known":
        sync_generation(root, store)
        plan = store.create_validation_plan(store.generation(), argv, cwd=cwd_path)
        emit_ok({
            "executed": False,
            "requires_host_visible_execution": True,
            "safety": safety,
            "identity": identify(argv, cwd_path),
            "cwd": str(cwd_path),
            "generation": store.generation(),
            "plan_id": plan["plan_id"],
            "next": "run the exact validation through the host tool, then use validation-record with this one-time plan-id, the same generation/cwd/command, exit code, and concise observable evidence",
        })
        return
    result = validate(root, cwd_path, store, argv, timeout=args.timeout)
    emit_ok({"executed": True, "result": result, "validation": store.latest_validation()})


def cmd_validation_record(args: argparse.Namespace) -> None:
    cwd_path, root, store = _store(args)
    store.ensure_active()
    sync_generation(root, store)
    parsed = json.loads(args.command_json)
    if not (isinstance(parsed, list) and parsed and all(isinstance(x, str) for x in parsed)):
        raise ValueError("--command-json must be a non-empty JSON array of strings")
    current_generation = store.generation()
    if int(args.generation) != current_generation:
        raise RuntimeError(
            f"host validation is stale: observed generation {int(args.generation)} but current generation is {current_generation}; rerun validation"
        )
    validation_id = store.record_host_validation(
        args.plan_id, current_generation, parsed, int(args.exit_code), cwd=cwd_path, evidence=args.evidence,
    )
    emit_ok({"validation_id": validation_id, "generation": current_generation, "cwd": str(cwd_path), "exit_code": int(args.exit_code)})


def cmd_validation_resolve(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    store.ensure_active()
    store.resolve_validation(args.validation_id, "baseline_unrelated", args.evidence)
    emit_ok({"validation_id": args.validation_id, "disposition": "baseline_unrelated"})


def _read_local_content_file(root: Path, store, raw: str) -> bytes:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    base = root.resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise PermissionError("--content-file must be inside the workspace; use stdin for external or runtime-private payloads") from exc
    cur = base
    for part in candidate.relative_to(base).parts:
        cur = cur / part
        try:
            st = cur.lstat()
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"content file path does not exist: {cur}") from exc
        if stat.S_ISLNK(st.st_mode):
            raise RuntimeError(f"content file path must not contain symlinks: {cur}")
    st = candidate.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise RuntimeError("content file must be a regular non-symlink file")
    if st.st_size > 16 * 1024 * 1024:
        raise ValueError("local guarded write content exceeds 16 MiB; use a host-visible file operation")
    return candidate.read_bytes()


def cmd_write(args: argparse.Namespace) -> None:
    _cwd_path, root, store = _store(args)
    # Cancellation is a lifecycle gate: reject before reading any payload file.
    store.ensure_active()
    if args.content_file:
        content = _read_local_content_file(root, store, args.content_file)
    else:
        content = sys.stdin.buffer.read(MAX_LOCAL_WRITE_BYTES + 1)
        if len(content) > MAX_LOCAL_WRITE_BYTES:
            raise ValueError("local guarded write payload exceeds 16 MiB; use a host-visible file operation")
    result = guarded_write(
        root, store, Path(args.path), content,
        expected_sha256=args.expected_sha256,
        allow_protected=args.allow_protected,
        protected_override_reason=args.protected_override_reason,
    )
    emit_ok(result)


def cmd_hash(args: argparse.Namespace) -> None:
    _cwd_path, root, _store_obj = _store(args)
    path, digest = hash_workspace_path(root, Path(args.path))
    emit_ok({"path": path, "sha256": digest})


def cmd_changes(args: argparse.Namespace) -> None:
    _cwd_path, root, store = _store(args)
    sync_generation(root, store)
    result = changes(root, store)
    if args.review:
        store.ensure_active()
        store.mark_reviewed()
        result["reviewed_generation"] = store.generation()
    emit_ok(result)


def cmd_criterion(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    store.ensure_active()
    store.set_criterion(args.index, args.status, args.evidence)
    emit_ok(store.criteria())


def cmd_steer(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    store.ensure_active()
    emit_ok({"steer_id": store.record_steer(args.text), "plan_revision": store.get_meta("plan_revision", 0)})


def cmd_steer_ack(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    store.ensure_active()
    store.ack_steer(args.steer_id, args.evidence)
    emit_ok({"steer_id": args.steer_id, "state": "acked"})


def cmd_external(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    details = json.loads(args.details_json) if args.details_json else None
    requested_action_id = args.action_id
    action_id = store.record_external(
        args.kind, args.state, args.identity, details,
        action_class=args.action_class, action_id=requested_action_id,
    )
    persisted = store.external_action(action_id)
    emit_ok({
        "action_id": action_id,
        "state": persisted["state"],
        "requested_state": args.state,
        "deduplicated": requested_action_id is None and args.action_class == "external_non_idempotent" and persisted["state"] != args.state,
    })


def cmd_external_resolve_failure(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    store.resolve_external_failure(args.action_id, args.evidence)
    emit_ok({"action_id": args.action_id, "failure_resolved": True})


def cmd_git_authorize(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    store.authorize_git_mutation(
        args.reason, head=args.head, branch=args.branch, index=args.index
    )
    emit_ok({
        "allow_git_mutation": True,
        "scope": store.get_meta("git_mutation_scope"),
        "reason": store.get_meta("git_mutation_reason"),
    })


def cmd_service_start(args: argparse.Namespace) -> None:
    _cwd_path, root, store = _store(args)
    store.ensure_active()
    capability = managed_session_capability()
    if not capability["supported"]:
        emit_ok({"started": False, "requires_host_visible_execution": True, "capability": capability})
        return
    emit_ok(service_start(root, store.task_id, Path(__file__).resolve()))


def _service_call(args: argparse.Namespace, payload: dict) -> None:
    _cwd_path, root, store = _store(args)
    response = service_request(root, store.task_id, payload, timeout=args.timeout if hasattr(args, "timeout") else 3.0)
    if not response.get("ok"):
        raise RuntimeError(response.get("error", {}).get("message", "runtime service error"))
    emit_ok(response["data"])


def cmd_spawn(args: argparse.Namespace) -> None:
    cwd, root, store = _store(args)
    store.ensure_active()
    capability = managed_session_capability()
    if not capability["supported"]:
        emit_ok({"spawned": False, "requires_host_visible_execution": True, "capability": capability})
        return
    argv = _command(args.command)
    safety = assess_command(argv)
    if safety.classification.value != "safe_known":
        emit_ok({"spawned": False, "requires_host_visible_execution": True, "safety": safety, "identity": identify(argv, cwd)})
        return
    service_start(root, store.task_id, Path(__file__).resolve())
    response = service_request(root, store.task_id, {"op": "spawn", "argv": argv, "cwd": str(cwd)})
    if not response.get("ok"):
        raise RuntimeError(response.get("error", {}).get("message", "spawn failed"))
    emit_ok(response["data"])


def cmd_poll(args: argparse.Namespace) -> None:
    _service_call(args, {"op": "poll", "handle": args.handle})


def cmd_stdin(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    store.ensure_active()
    _service_call(args, {"op": "stdin", "handle": args.handle, "data": args.data})


def cmd_interrupt(args: argparse.Namespace) -> None:
    _service_call(args, {"op": "interrupt", "handle": args.handle})


def cmd_terminate(args: argparse.Namespace) -> None:
    _service_call(args, {"op": "terminate", "handle": args.handle})


def cmd_service_stop(args: argparse.Namespace) -> None:
    _cwd_path, root, store = _store(args)
    response = service_request(root, store.task_id, {"op": "shutdown"}, timeout=5.0)
    if not response.get("ok"):
        raise RuntimeError(response.get("error", {}).get("message", "service shutdown failed"))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            service_request(root, store.task_id, {"op": "ping"}, timeout=0.2)
        except Exception:
            emit_ok({"stopped": True})
            return
        time.sleep(0.05)
    raise RuntimeError("runtime service acknowledged shutdown but endpoint remained reachable")


def cmd_process_resolve(args: argparse.Namespace) -> None:
    _cwd_path, _root_path, store = _store(args)
    store.resolve_orphaned_process(args.handle, args.evidence)
    emit_ok({"handle": args.handle, "state": "resolved"})


def cmd_checkpoint(args: argparse.Namespace) -> None:
    cwd, root, store = _store(args)
    store.ensure_active()
    emit_ok(create_checkpoint(root, cwd, store, key_findings=args.key_finding or [], next_action=args.next_action))


def cmd_checkpoint_restore(args: argparse.Namespace) -> None:
    cwd, root, store = _store(args)
    store.ensure_active()
    emit_ok(restore_checkpoint(root, cwd, store))


def cmd_completion(args: argparse.Namespace) -> None:
    _cwd_path, root, store = _store(args)
    emit_ok(assess_completion(root, store))


def cmd_freshness_waiver(args: argparse.Namespace) -> None:
    _cwd_path, root, store = _store(args)
    store.ensure_active()
    sync_generation(root, store)
    opaque = sorted(str(x) for x in changes(root, store).get("ignored_watch", {}).get("opaque_paths", []))
    waiver = store.set_freshness_waiver(opaque, args.reason)
    emit_ok(waiver)


def cmd_cancel(args: argparse.Namespace) -> None:
    _cwd_path, root, store = _store(args)
    store.ensure_active()
    store.cancel(args.reason)
    # Do not revert workspace. Best-effort service stop; unresolved ownership remains in state.
    try:
        response = service_request(root, store.task_id, {"op": "shutdown"}, timeout=3.0)
        if not response.get("ok"):
            store.mark_running_processes_orphaned("service shutdown failed during task cancellation")
    except Exception:
        store.mark_running_processes_orphaned("service unavailable during task cancellation")
    emit_ok({"task_id": store.task_id, "status": "cancelled", "workspace_reverted": False})


def cmd_cleanup(args: argparse.Namespace) -> None:
    _cwd_path, root, store = _store(args)
    task_status = str(store.get_meta("task_status", "uninitialized"))
    if task_status == "active":
        decision = assess_completion(root, store)
        if decision.status != CompletionStatus.PASS:
            raise RuntimeError(f"refusing cleanup before completion PASS: {', '.join(decision.reasons)}")
    elif task_status == "cancelled":
        if (
            store.unresolved_external_count()
            or store.unresolved_external_failure_count()
            or store.running_process_count()
            or store.unresolved_process_failure_count()
        ):
            raise RuntimeError("refusing cancelled-task cleanup while external/process outcomes remain unresolved")
    else:
        raise RuntimeError(f"refusing cleanup for task status {task_status}")
    # A live service must be confirmed stopped. An absent endpoint is fine only if no unresolved processes remain.
    try:
        response = service_request(root, store.task_id, {"op": "shutdown"}, timeout=5.0)
        if not response.get("ok"):
            raise RuntimeError(response.get("error", {}).get("message", "service shutdown failed"))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                service_request(root, store.task_id, {"op": "ping"}, timeout=0.2)
            except Exception:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("service endpoint remained reachable after shutdown")
    except RuntimeError as exc:
        if str(exc) != "runtime service is not running":
            raise
    if store.running_process_count():
        raise RuntimeError("refusing cleanup while managed process ownership is unresolved")
    task_id = store.task_id
    task_dir = state_dir_for(root, task_id, create=False)
    active = active_task_id(root)
    shutil.rmtree(task_dir)
    if active == task_id:
        active_path = root_state_dir(root) / "active_task.json"
        try:
            active_path.unlink()
        except FileNotFoundError:
            pass
    emit_ok({"cleaned": True, "task_id": task_id})


def cmd_shell_snapshot(args: argparse.Namespace) -> None:
    cwd, _root_path, store = _store(args)
    store.ensure_active()
    emit_ok(shell_snapshot_plan(cwd))


def cmd_source_verify(args: argparse.Namespace) -> None:
    emit_ok(verify_upstream())


def cmd_serve(args: argparse.Namespace) -> None:
    token = os.environ.get("CODEX_LOOP_SERVICE_TOKEN")
    if not token:
        raise RuntimeError("missing runtime service token")
    service_serve(_cwd(args.cwd), args.task_id, token)


def _add_scope(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cwd")
    parser.add_argument("--task-id")
    parser.add_argument("--use-active-task", action="store_true", help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex_loop.py")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p = sub.add_parser("bootstrap"); p.add_argument("--cwd"); p.add_argument("--task-id"); p.add_argument("--objective", required=True); p.add_argument("--criterion", action="append"); p.add_argument("--profile", default="regular"); p.add_argument("--no-validation", action="store_true"); p.add_argument("--no-validation-reason"); p.add_argument("--allow-git-head", action="store_true"); p.add_argument("--allow-git-branch", action="store_true"); p.add_argument("--allow-git-index", action="store_true"); p.add_argument("--git-mutation-reason"); p.set_defaults(func=cmd_bootstrap)
    for name, func in [("snapshot", cmd_snapshot), ("instructions", cmd_instructions), ("changes", cmd_changes), ("completion", cmd_completion), ("checkpoint-restore", cmd_checkpoint_restore), ("service-start", cmd_service_start), ("service-stop", cmd_service_stop), ("shell-snapshot", cmd_shell_snapshot), ("cleanup", cmd_cleanup)]:
        p = sub.add_parser(name); _add_scope(p); p.set_defaults(func=func)
        if name == "instructions": p.add_argument("--fallback", action="append")
        if name == "changes": p.add_argument("--review", action="store_true")
    p = sub.add_parser("command-check"); p.add_argument("--cwd"); p.add_argument("command", nargs=argparse.REMAINDER); p.set_defaults(func=cmd_command_check)
    for name, func in [("exec", cmd_exec), ("validate", cmd_validate), ("spawn", cmd_spawn)]:
        p = sub.add_parser(name); _add_scope(p); p.add_argument("--timeout", type=float); p.add_argument("command", nargs=argparse.REMAINDER); p.set_defaults(func=func)
    p = sub.add_parser("validation-record"); _add_scope(p); p.add_argument("--plan-id", required=True); p.add_argument("--command-json", required=True); p.add_argument("--generation", required=True, type=int); p.add_argument("--exit-code", required=True, type=int); p.add_argument("--evidence", required=True); p.set_defaults(func=cmd_validation_record)
    p = sub.add_parser("validation-resolve"); _add_scope(p); p.add_argument("--validation-id", type=int, required=True); p.add_argument("--evidence", required=True); p.set_defaults(func=cmd_validation_resolve)
    p = sub.add_parser("freshness-waiver"); _add_scope(p); p.add_argument("--reason", required=True); p.set_defaults(func=cmd_freshness_waiver)
    p = sub.add_parser("external-resolve-failure"); _add_scope(p); p.add_argument("--action-id", required=True); p.add_argument("--evidence", required=True); p.set_defaults(func=cmd_external_resolve_failure)
    p = sub.add_parser("write"); _add_scope(p); p.add_argument("--path", required=True); p.add_argument("--content-file"); p.add_argument("--expected-sha256"); p.add_argument("--allow-protected", action="store_true"); p.add_argument("--protected-override-reason"); p.set_defaults(func=cmd_write)
    p = sub.add_parser("hash"); _add_scope(p); p.add_argument("--path", required=True); p.set_defaults(func=cmd_hash)
    p = sub.add_parser("criterion"); _add_scope(p); p.add_argument("--index", type=int, required=True); p.add_argument("--status", choices=["pending","pass","fail","blocked"], required=True); p.add_argument("--evidence"); p.set_defaults(func=cmd_criterion)
    p = sub.add_parser("steer"); _add_scope(p); p.add_argument("--text", required=True); p.set_defaults(func=cmd_steer)
    p = sub.add_parser("steer-ack"); _add_scope(p); p.add_argument("--steer-id", required=True); p.add_argument("--evidence", required=True); p.set_defaults(func=cmd_steer_ack)
    p = sub.add_parser("external"); _add_scope(p); p.add_argument("--kind", required=True); p.add_argument("--state", required=True, choices=["planned","dispatched","terminal_success","terminal_failure","outcome_unknown","cancelled_before_dispatch"]); p.add_argument("--identity"); p.add_argument("--action-class", default="recheckable", choices=["read_only","recheckable","external_non_idempotent"]); p.add_argument("--action-id"); p.add_argument("--details-json"); p.set_defaults(func=cmd_external)
    p = sub.add_parser("git-authorize"); _add_scope(p); p.add_argument("--reason", required=True); p.add_argument("--head", action="store_true"); p.add_argument("--branch", action="store_true"); p.add_argument("--index", action="store_true"); p.set_defaults(func=cmd_git_authorize)
    for name, func in [("poll",cmd_poll),("stdin",cmd_stdin),("interrupt",cmd_interrupt),("terminate",cmd_terminate)]:
        p=sub.add_parser(name); _add_scope(p); p.add_argument("handle"); p.add_argument("--timeout",type=float,default=3.0)
        if name=="stdin": p.add_argument("data")
        p.set_defaults(func=func)
    p = sub.add_parser("process-resolve"); _add_scope(p); p.add_argument("--handle", required=True); p.add_argument("--evidence", required=True); p.set_defaults(func=cmd_process_resolve)
    p = sub.add_parser("checkpoint"); _add_scope(p); p.add_argument("--key-finding", action="append"); p.add_argument("--next-action"); p.set_defaults(func=cmd_checkpoint)
    p = sub.add_parser("cancel"); _add_scope(p); p.add_argument("--reason"); p.set_defaults(func=cmd_cancel)
    p = sub.add_parser("source-verify"); p.set_defaults(func=cmd_source_verify)
    p = sub.add_parser("_serve"); p.add_argument("--cwd", required=True); p.add_argument("--task-id", required=True); p.set_defaults(func=cmd_serve)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        args.func(args)
        return 0
    except Exception as exc:
        emit_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
