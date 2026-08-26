#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codex_loop_kernel as kernel
from codex_loop_context_projection import build_working
from codex_loop_runtime.change_tracker import sync_generation
from codex_loop_runtime.command_identity import identify
from codex_loop_runtime.command_safety import assess as assess_command
from codex_loop_runtime.lifecycle import DURABLE_SIGNAL_KEYS, assess_runtime_need
from codex_loop_runtime.model_relay import (
    DEFAULT_GUARD_BYTES,
    DEFAULT_LINE_WIDTH,
    RelayError,
    failure_result,
    frame_file,
    receive_file,
)
from codex_loop_runtime.protocol import emit_error, emit_ok
from codex_loop_runtime.state import active_task_id, open_store
from codex_loop_runtime.workspace import repo_root


def _cwd(raw: str | None) -> Path:
    return Path(raw or os.getcwd()).resolve()


def _scope_from_argv(argv: list[str]) -> tuple[Path, Path, object]:
    cwd = _cwd(argv[argv.index('--cwd') + 1] if '--cwd' in argv else None)
    root = repo_root(cwd)
    task_id = argv[argv.index('--task-id') + 1] if '--task-id' in argv else active_task_id(root)
    if not task_id:
        raise RuntimeError('no active codex-loop task; run bootstrap or pass --task-id')
    return cwd, root, open_store(root, task_id)


def _command_after_double_dash(argv: list[str]) -> list[str]:
    if '--' not in argv:
        raise ValueError('a command is required after --')
    command = argv[argv.index('--') + 1:]
    if not command:
        raise ValueError('a command is required after --')
    return command


def _matching_plans(store, generation: int, command: list[str], cwd: Path):
    cwd_norm, rec = store._validation_record(command, cwd)
    encoded = json.dumps(rec, sort_keys=True)
    with store.connect() as db:
        rows = db.execute(
            'SELECT plan_id FROM validation_plans '
            'WHERE generation=? AND command_json=? AND cwd=? AND consumed=0 '
            'ORDER BY created_at,plan_id',
            (int(generation), encoded, cwd_norm),
        ).fetchall()
    return cwd_norm, rec, rows


def _resolve_plan(store, generation: int, command: list[str], cwd: Path) -> dict:
    cwd_norm, rec, rows = _matching_plans(store, generation, command, cwd)
    if not rows:
        raise ValueError('no unconsumed validation plan matches the current generation/cwd/command; run validate first')
    if len(rows) > 1:
        raise RuntimeError('multiple unconsumed validation plans match the current generation/cwd/command; use an explicit plan id for low-level recovery')
    return {'plan_id': str(rows[0]['plan_id']), 'generation': int(generation), 'cwd': cwd_norm, 'identity': rec['sha256']}


def _cmd_lifecycle_assess(argv: list[str]) -> int:
    p = argparse.ArgumentParser(add_help=False)
    for key in DURABLE_SIGNAL_KEYS:
        p.add_argument("--" + key.replace("_", "-"), action="store_true")
    args = p.parse_args(argv[1:])
    signals = {key: bool(getattr(args, key)) for key in DURABLE_SIGNAL_KEYS}
    emit_ok(assess_runtime_need(signals))
    return 0


def _cmd_next(argv: list[str]) -> int:
    cwd, root, store = _scope_from_argv(argv)
    emit_ok(build_working(root, cwd, store))
    return 0


def _cmd_validate(argv: list[str]) -> int:
    cwd, root, store = _scope_from_argv(argv)
    store.ensure_active()
    command = _command_after_double_dash(argv)
    safety = assess_command(command)
    if safety.classification.value == 'safe_known':
        return _delegate(argv)
    sync_generation(root, store)
    generation = store.generation()
    cwd_norm, rec, rows = _matching_plans(store, generation, command, cwd)
    if len(rows) > 1:
        raise RuntimeError('multiple unconsumed validation plans match this generation/cwd/command; use an explicit plan id for low-level recovery')
    if rows:
        plan_id = str(rows[0]['plan_id'])
        reused = True
    else:
        plan = store.create_validation_plan(generation, command, cwd=cwd)
        plan_id = plan['plan_id']
        reused = False
    payload = {
        'executed': False,
        'requires_host_visible_execution': True,
        'safety': safety,
        'identity': identify(command, cwd),
        'cwd': cwd_norm,
        'next': 'run the exact validation through the host tool, then record its exit code and concise observable evidence with validation-record using the same cwd and exact command; plan/generation bookkeeping is inferred when unambiguous',
    }
    if '--debug-bookkeeping' in argv:
        payload.update({'generation': generation, 'plan_id': plan_id, 'plan_reused': reused})
    emit_ok(payload)
    return 0


def _cmd_validation_record(argv: list[str]) -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--use-active-task', action='store_true')
    p.add_argument('--plan-id')
    p.add_argument('--command-json', required=True)
    p.add_argument('--generation', type=int)
    p.add_argument('--exit-code', type=int, required=True)
    p.add_argument('--evidence', required=True)
    args = p.parse_args(argv[1:])
    cwd = _cwd(args.cwd)
    root = repo_root(cwd)
    task_id = args.task_id or active_task_id(root)
    if not task_id:
        raise RuntimeError('no active codex-loop task; run bootstrap or pass --task-id')
    store = open_store(root, task_id)
    store.ensure_active()
    sync_generation(root, store)
    command = json.loads(args.command_json)
    if not (isinstance(command, list) and command and all(isinstance(x, str) for x in command)):
        raise ValueError('--command-json must be a non-empty JSON array of strings')
    generation = store.generation()
    if args.generation is not None and args.generation != generation:
        raise RuntimeError(f'host validation is stale: observed generation {args.generation} but current generation is {generation}; rerun validation')
    inferred = args.plan_id is None
    plan_id = args.plan_id or _resolve_plan(store, generation, command, cwd)['plan_id']
    validation_id = store.record_host_validation(plan_id, generation, command, args.exit_code, cwd=cwd, evidence=args.evidence)
    emit_ok({'validation_id': validation_id, 'cwd': str(cwd), 'exit_code': args.exit_code, 'bookkeeping_inferred': inferred})
    return 0



def _path_from(raw: str, cwd: Path) -> Path:
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (cwd / path).resolve()


def _cmd_relay_frame(argv: list[str]) -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--cwd')
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--transfer-id')
    p.add_argument('--guard-bytes', type=int, default=DEFAULT_GUARD_BYTES)
    p.add_argument('--line-width', type=int, default=DEFAULT_LINE_WIDTH)
    p.add_argument('--overwrite', action='store_true')
    args = p.parse_args(argv[1:])
    cwd = _cwd(args.cwd)
    emit_ok(frame_file(
        _path_from(args.input, cwd),
        _path_from(args.output, cwd),
        transfer_id=args.transfer_id,
        guard_bytes=args.guard_bytes,
        line_width=args.line_width,
        overwrite=args.overwrite,
    ))
    return 0


def _cmd_relay_receive(argv: list[str]) -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--cwd')
    p.add_argument('--envelope', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--expected-size', type=int)
    p.add_argument('--expected-sha256')
    p.add_argument('--overwrite', action='store_true')
    args = p.parse_args(argv[1:])
    cwd = _cwd(args.cwd)
    try:
        result = receive_file(
            _path_from(args.envelope, cwd),
            _path_from(args.output, cwd),
            overwrite=args.overwrite,
            expected_size=args.expected_size,
            expected_sha256=args.expected_sha256,
        )
    except RelayError as exc:
        emit_ok(failure_result(exc))
        return 2
    emit_ok(result)
    return 0

def _delegate(argv: list[str]) -> int:
    args = list(argv)
    command = args[0] if args else ''
    task_scoped = command not in {'bootstrap', 'lifecycle-assess', 'command-check', 'source-verify', '_serve'}
    if task_scoped and '--task-id' not in args and '--use-active-task' not in args:
        insert = args.index('--') if '--' in args else len(args)
        args.insert(insert, '--use-active-task')
    old = sys.argv
    try:
        sys.argv = [str(Path(kernel.__file__).resolve()), *args]
        return kernel.main()
    finally:
        sys.argv = old


def main() -> int:
    argv = sys.argv[1:]
    try:
        if not argv:
            return _delegate(argv)
        if argv[0] == 'lifecycle-assess':
            return _cmd_lifecycle_assess(argv)
        if argv[0] == 'next':
            return _cmd_next(argv)
        if argv[0] == 'validate':
            return _cmd_validate(argv)
        if argv[0] == 'validation-record':
            return _cmd_validation_record(argv)
        if argv[0] == 'relay-frame':
            return _cmd_relay_frame(argv)
        if argv[0] == 'relay-receive':
            return _cmd_relay_receive(argv)
        return _delegate(argv)
    except Exception as exc:
        emit_error(exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
