#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codex_loop_kernel as kernel
from codex_loop_context_projection import build_lifecycle_working, build_working
from codex_loop_runtime.change_tracker import sync_generation
from codex_loop_runtime.command_identity import identify
from codex_loop_runtime.command_safety import assess as assess_command
from codex_loop_runtime.deployment_manifest import verify_installed_skill
from codex_loop_runtime.execution_supervision import (
    CleanupStatus,
    EvidenceKind,
    ProcessStatus,
    WorkloadStatus,
    execution_policy,
    observation_from_strings,
)
from codex_loop_runtime.interaction_routing import resolve_interaction_target
from codex_loop_runtime.instructions import discover
from codex_loop_runtime.routing_state import (
    DEPLOYMENT_TARGETS,
    HOST_SURFACES,
    INTERACTION_TARGETS as ROUTING_INTERACTION_TARGETS,
    ROUTE_ACTIONS,
    WORKSPACE_MODES,
    PERMISSION_PROBE_CAPABILITIES,
    permission_observation_status,
    permission_preflight_plan,
    record_permission_observation,
    route_check,
    route_init,
    route_show,
    route_transition,
)
from codex_loop_runtime.host_config import (
    PROGRESS_MODES,
    effective_progress_config,
    host_config_get,
    host_config_reset,
    host_config_set,
    host_config_show,
    host_config_unset,
    progress_policy,
    set_progress_config,
)
from codex_loop_runtime.persistence import (
    build_resume_plan,
    build_state_manifest,
    cleanup_decision,
    load_state_manifest,
    persistence_policy,
    resume_state_manifest,
    write_state_manifest,
)
from codex_loop_runtime.model_relay import (
    DEFAULT_GUARD_BYTES,
    DEFAULT_LINE_WIDTH,
    RelayError,
    failure_result,
    frame_file,
    receive_file,
)
from codex_loop_runtime.protocol import emit_error, emit_ok
from codex_loop_runtime.web_publish import (
    begin_web_publish_continuation,
    build_web_publish_archive,
    build_web_publish_bundle,
    publish_continuation_state,
    web_local_sync_plan,
    web_publish_plan,
)
from codex_loop_runtime.publication_router import publication_enter
from codex_loop_runtime.release_lineage import capture_workspace_binding, workspace_binding_status
from codex_loop_runtime.source_acquisition import (
    FALLBACK_METHODS,
    source_acquisition_plan,
    verify_restored_git_workspace,
)
from codex_loop_runtime.repository_continuity import repository_enter
from codex_loop_runtime.workspace_cache import (
    build_workspace_cache,
    drive_cache_cleanup_plan,
    register_drive_cache_folder,
    registered_drive_cache_folders,
    restore_workspace_cache,
    unregister_drive_cache_folder,
    validate_workspace_cache,
    workspace_cache_cleanup_plan,
)
from codex_loop_runtime.state import active_task_id, open_store, set_active_task
from codex_loop_runtime.workspace import git_state, repo_root, run_git
from codex_loop_runtime.workspace_registry import (
    grant_workspace,
    list_workspaces,
    register_workspace,
    registry_path,
    remove_workspace,
    resolve_workspace,
    session_grants,
)


HOST_ADAPTER_COMMANDS = (
    ('orient', 'bind/orient the existing lifecycle to workspace authority and pre-existing work'),
    ('instructions', 'load scoped repository instructions for the existing lifecycle'),
    ('authority', 'return the complete retained user request and ordered steers'),
    ('next', 'resume the same lifecycle from retained authority, plan, and current reality'),
    ('host-config', 'show or update the unified private Host Profile'),
    ('progress-config', 'compatibility facade for private progress-visibility preferences'),
    ('progress-policy', 'resolve progress behavior for lightweight or substantive work'),
    ('route-init', 'initialize deterministic conversation-scoped routing state'),
    ('route-show', 'show deterministic conversation-scoped routing state'),
    ('route-transition', 'change workspace, interaction, or deployment routing with evidence gates'),
    ('route-check', 'fail closed before repository, browser, deployment, or publish host actions'),
    ('permission-preflight-plan', 'plan only permission probes not covered by fresh scoped current-session observations'),
    ('permission-observation-record', 'record a scoped expiring host capability observation'),
    ('permission-observation-status', 'check freshness of a scoped current-session host capability observation'),
    ('source-acquisition-verify', 'verify an exact Git-native Web workspace restore before lifecycle rebind'),
    ('repository-enter', 'reuse HOT Git state, restore verified WARM state, or require COLD acquisition'),
    ('web-publish-continuation-begin', 'freeze a publish-only continuation onto fresh validation and forbid redundant revalidation'),
    ('web-publish-bundle', 'build and bind a verified exact-identity Web Git bundle'),
    ('web-publish-archive', 'compatibility alias for exact-identity Web Git bundle creation'),
    ('publish-enter', 'stable route-aware publication ABI; the only model-facing publication entrypoint'),
    ('web-publish-plan', 'low-level Web publication planner used by publish-enter'),
    ('web-local-sync-plan', 'plan the fixed Web -> local Drive staging + RDC download path'),
    ('interaction-route', 'resolve Cloud Browser vs local browser target without granting access'),
    ('persistence-export', 'export private cross-conversation recovery state'),
    ('persistence-validate', 'validate a recovery manifest'),
    ('persistence-resume-plan', 'plan deterministic recovery observations'),
    ('persistence-resume', 'restore the same lifecycle id and reconcile current reality'),
    ('persistence-cleanup-plan', 'plan recovery-manifest cleanup'),
    ('workspace-cache-create', 'create an immutable 3-day Git/worktree Workspace Capsule for private Drive staging'),
    ('workspace-cache-validate', 'validate a Workspace Capsule and its exact Git/worktree identity'),
    ('workspace-cache-restore', 'restore a Workspace Capsule into a fresh Git workspace and emit a consumption receipt'),
    ('workspace-cache-cleanup-plan', 'plan bounded consumed/expired Drive Workspace Capsule cleanup'),
    ('drive-cache-register', 'remember a Codex Loop cache folder path in host-local non-uploaded config'),
    ('drive-cache-unregister', 'remove a cache folder path from host-local config'),
    ('drive-cache-list', 'list host-local registered Codex Loop Drive cache folders'),
    ('drive-cache-cleanup-plan', 'return exact owned >=3-day registered cache objects ready for automatic cleanup'),
    ('workspace-register', 'register a private host workspace alias'),
    ('workspace-registry-list', 'list private host workspace aliases'),
    ('workspace-resolve', 'resolve a registered workspace under current grants'),
    ('workspace-grant', 'record current-conversation workspace authorization'),
    ('workspace-grants', 'show current-conversation workspace grants'),
    ('workspace-remove', 'remove a private host workspace alias'),
    ('workspace-sync-offer', 'prepare an exact-revision workspace sync offer'),
    ('deployment-provenance-verify', 'verify installed Skill bundle provenance'),
    ('relay-frame', 'frame a guarded model-relay payload'),
    ('relay-receive', 'receive and verify a guarded model-relay payload'),
)


def _print_top_level_help() -> int:
    print(kernel.build_parser().format_help().rstrip())
    print('\nHost-adapter commands:')
    width = max(len(name) for name, _ in HOST_ADAPTER_COMMANDS)
    for name, description in HOST_ADAPTER_COMMANDS:
        print(f'  {name:<{width}}  {description}')
    return 0


def _cwd(raw: str | None) -> Path:
    return Path(raw or os.getcwd()).resolve()


def _scope_from_argv(argv: list[str]) -> tuple[Path, Path, object]:
    explicit_cwd = _cwd(argv[argv.index('--cwd') + 1]) if '--cwd' in argv else None
    task_id = argv[argv.index('--task-id') + 1] if '--task-id' in argv else None
    if not task_id and explicit_cwd is not None:
        task_id = active_task_id(repo_root(explicit_cwd))
    if not task_id:
        raise RuntimeError('no active codex-loop lifecycle; pass --task-id')
    store = open_store(None, task_id)
    binding = store.get_meta('workspace_binding')
    if explicit_cwd is not None:
        cwd = explicit_cwd
    elif binding and binding.get('canonical_root'):
        cwd = Path(store.get_meta('workspace_cwd', binding['canonical_root'])).resolve()
    else:
        cwd = _cwd(None)
    root = repo_root(cwd)
    return cwd, root, store


def _command_after_double_dash(argv: list[str]) -> list[str]:
    if '--' not in argv:
        raise ValueError('a command is required after --')
    command = argv[argv.index('--') + 1:]
    if not command:
        raise ValueError('a command is required after --')
    return command


def _instruction_payload(cwd: Path, fallbacks: list[str], max_bytes: int) -> dict[str, object]:
    result = discover(cwd, fallback_filenames=tuple(fallbacks), max_bytes=max_bytes)
    return {
        'entries': [item.__dict__ for item in result.entries],
        'complete': result.complete,
        'truncated_paths': list(result.truncated_paths),
        'max_bytes': result.max_bytes,
        'bytes_read': result.bytes_read,
    }


def _verify_rebind(root: Path, expected: dict[str, object]) -> dict[str, object]:
    root = root.resolve()
    current = capture_workspace_binding(root)
    if not current.get('is_git'):
        raise RuntimeError('verified lifecycle rebind currently requires a Git workspace')
    expected_commit = str(expected.get('source_commit') or expected.get('base_commit') or '').strip()
    expected_tree = str(expected.get('source_tree') or expected.get('base_tree') or '').strip()
    expected_origin = str(expected.get('origin_hint') or '').strip()
    expected_repository = str(expected.get('repository') or '').strip().removesuffix('.git')
    if not any((expected_commit, expected_tree, expected_origin, expected_repository)):
        raise RuntimeError('verified lifecycle rebind requires a retained commit/tree or repository identity')
    current_origin = str(current.get('origin_hint') or '').strip()
    if not expected_commit and not expected_tree:
        if expected_origin and current_origin != expected_origin:
            raise RuntimeError('recovered workspace origin does not match the prior lifecycle binding')
        if expected_repository and not expected_origin:
            expected_repository_origin = f'github.com/{expected_repository}'
            if current_origin != expected_repository_origin:
                raise RuntimeError('recovered workspace repository does not match the retained lifecycle repository')
    if expected_commit:
        exists = run_git(root, ['cat-file', '-e', f'{expected_commit}^{{commit}}'])
        if exists.returncode != 0:
            raise RuntimeError('recovered workspace does not contain the lifecycle base commit')
        if expected_tree:
            tree = run_git(root, ['rev-parse', f'{expected_commit}^{{tree}}'])
            observed_tree = tree.stdout.decode('utf-8', errors='replace').strip() if tree.returncode == 0 else ''
            if observed_tree != expected_tree:
                raise RuntimeError('recovered workspace base tree does not match the lifecycle source')
        head = str(current.get('base_commit') or '').strip()
        if head:
            ancestor = run_git(root, ['merge-base', '--is-ancestor', expected_commit, head])
            if ancestor.returncode != 0:
                raise RuntimeError('recovered workspace history does not descend from the lifecycle base commit')
    return current


def _cmd_orient(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py orient')
    p.add_argument('--task-id', required=True)
    p.add_argument('--cwd')
    p.add_argument('--fallback', action='append', default=[])
    p.add_argument('--max-bytes', type=int, default=32 * 1024)
    p.add_argument('--rebind-verified', action='store_true')
    args = p.parse_args(argv[1:])
    store = open_store(None, args.task_id)
    store.ensure_active()
    cwd = _cwd(args.cwd)
    root = repo_root(cwd)
    instruction_state = _instruction_payload(cwd, args.fallback, args.max_bytes)
    git = git_state(root)
    is_git = bool(git.get('is_git'))
    probe_degraded = bool(git.get('probe_degraded', False))
    old_binding = store.get_meta('workspace_binding')
    expected_resume = store.get_meta('resume_expected_workspace')
    current_binding = capture_workspace_binding(root)
    binding_ok = True
    rebound = False

    if old_binding:
        status = workspace_binding_status(root, old_binding)
        if not status.get('matches'):
            binding_ok = False
            if args.rebind_verified:
                current_binding = _verify_rebind(root, old_binding)
                binding_ok = True
                rebound = True
    elif expected_resume:
        binding_ok = False
        if args.rebind_verified:
            current_binding = _verify_rebind(root, expected_resume)
            binding_ok = True
            rebound = True

    if binding_ok:
        if old_binding is None or rebound:
            store.set_meta('workspace_binding', current_binding)
        store.set_meta('workspace_cwd', str(cwd))
        store.set_meta('orientation_git', git)
        store.set_meta('protected_paths', list(git.get('protected_paths', [])))
        store.set_meta('instruction_complete', bool(instruction_state['complete']))
        set_active_task(root, store.task_id)
        if rebound:
            store.bump_generation()
            store.set_meta('baseline_enabled', False)
            store.set_meta('workspace_fingerprint', None)
            store.set_meta('baseline_git', None)
            store.set_meta('resume_expected_workspace', None)

    safe_to_mutate = bool(binding_ok and instruction_state['complete'] and not (is_git and probe_degraded))
    emit_ok({
        'task_id': store.task_id,
        'request_anchor': store.request_anchor(),
        'root': str(root),
        'cwd': str(cwd),
        'workspace_binding': current_binding if binding_ok else {'matches': False, 'prior': old_binding, 'candidate': current_binding},
        'rebound': rebound,
        'instructions': instruction_state,
        'preexisting_work': {
            'is_git': is_git,
            'head': git.get('head'),
            'branch': git.get('branch'),
            'status': list(git.get('status', [])),
            'protected_paths': list(git.get('protected_paths', [])),
            'probe_degraded': probe_degraded,
            'safe_to_mutate': safe_to_mutate,
        },
        'safe_to_mutate': safe_to_mutate,
        'rule': 'continue this lifecycle; user authority, complete scoped instructions, and pre-existing work constrain execution',
    })
    return 0


def _cmd_instructions(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py instructions')
    p.add_argument('--task-id', required=True)
    p.add_argument('--cwd')
    p.add_argument('--fallback', action='append', default=[])
    p.add_argument('--max-bytes', type=int, default=32 * 1024)
    args = p.parse_args(argv[1:])
    store = open_store(None, args.task_id)
    store.ensure_active()
    cwd = _cwd(args.cwd)
    binding = store.get_meta('workspace_binding')
    if binding:
        status = workspace_binding_status(repo_root(cwd), binding)
        if not status.get('matches'):
            raise RuntimeError('instruction scope is outside the lifecycle bound workspace; recover/rebind first')
    emit_ok(_instruction_payload(cwd, args.fallback, args.max_bytes))
    return 0


def _cmd_authority(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py authority')
    p.add_argument('--task-id', required=True)
    args = p.parse_args(argv[1:])
    store = open_store(None, args.task_id)
    emit_ok({
        'task_id': store.task_id,
        'request_anchor': store.request_anchor(),
        'steers': [str(item.get('text', '')) for item in store.request_steers()],
        'complete': True,
    })
    return 0


def _cmd_next(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py next')
    p.add_argument('--task-id', required=True)
    p.add_argument('--cwd')
    args = p.parse_args(argv[1:])
    store = open_store(None, args.task_id)
    store.ensure_active()
    binding = store.get_meta('workspace_binding')
    if not binding:
        working = build_lifecycle_working(store)
    else:
        canonical = Path(str(binding.get('canonical_root') or ''))
        if not canonical.exists():
            working = build_lifecycle_working(store, workspace_status={
                'bound': True, 'available': False, 'recovery_required': True,
                'canonical_root': str(canonical),
                'reason': 'the lifecycle bound workspace is no longer present',
            })
        else:
            cwd = _cwd(args.cwd) if args.cwd else Path(store.get_meta('workspace_cwd', str(canonical))).resolve()
            root = repo_root(cwd)
            status = workspace_binding_status(root, binding)
            if not status.get('matches'):
                working = build_lifecycle_working(store, workspace_status={
                    'bound': True, 'available': True, 'recovery_required': True,
                    'canonical_root': str(canonical), 'details': status,
                    'reason': 'the current workspace no longer matches the lifecycle binding',
                })
            else:
                working = build_working(root, cwd, store)
                working['workspace_status'] = {'bound': True, 'available': True, 'recovery_required': False, 'canonical_root': str(canonical)}
    working['progress'] = progress_policy('substantive')
    emit_ok(working)
    return 0



def _parse_host_config_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _cmd_host_config(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py host-config')
    sub = p.add_subparsers(dest='action')
    sub.add_parser('show')
    get_p = sub.add_parser('get'); get_p.add_argument('path')
    set_p = sub.add_parser('set'); set_p.add_argument('path'); set_p.add_argument('value')
    unset_p = sub.add_parser('unset'); unset_p.add_argument('path')
    reset_p = sub.add_parser('reset'); reset_p.add_argument('section')
    args = p.parse_args(argv[1:])
    action = args.action or 'show'
    if action == 'show':
        emit_ok(host_config_show())
    elif action == 'get':
        emit_ok({'path': args.path, 'value': host_config_get(args.path)})
    elif action == 'set':
        emit_ok(host_config_set(args.path, _parse_host_config_value(args.value)))
    elif action == 'unset':
        emit_ok(host_config_unset(args.path))
    elif action == 'reset':
        emit_ok(host_config_reset(args.section))
    else:
        raise ValueError(f'unsupported host-config action: {action}')
    return 0

def _cmd_progress_config(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py progress-config')
    p.add_argument('--mode', choices=sorted(PROGRESS_MODES))
    p.add_argument('--interval-seconds', type=int)
    p.add_argument('--tool-call-interval', type=int)
    p.add_argument('--upfront-plan', action=argparse.BooleanOptionalAction, default=None)
    p.add_argument('--material-event-updates', action=argparse.BooleanOptionalAction, default=None)
    p.add_argument('--reset', action='store_true')
    args = p.parse_args(argv[1:])
    requested_write = args.reset or any(
        value is not None
        for value in (
            args.mode,
            args.interval_seconds,
            args.tool_call_interval,
            args.upfront_plan,
            args.material_event_updates,
        )
    )
    if requested_write:
        emit_ok(set_progress_config(
            mode=args.mode,
            interval_seconds=args.interval_seconds,
            tool_call_interval=args.tool_call_interval,
            upfront_plan=args.upfront_plan,
            material_event_updates=args.material_event_updates,
            reset=args.reset,
        ))
    else:
        emit_ok(effective_progress_config())
    return 0


def _cmd_progress_policy(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py progress-policy')
    p.add_argument('--work-shape', required=True, choices=['lightweight', 'substantive'])
    args = p.parse_args(argv[1:])
    emit_ok(progress_policy(args.work_shape))
    return 0


def _cmd_validate(argv: list[str]) -> int:
    cwd, root, store = _scope_from_argv(argv)
    store.ensure_active()
    command = _command_after_double_dash(argv)
    sync_generation(root, store)
    continuation = publish_continuation_state(store)
    if continuation.get('active') and continuation.get('revalidation_forbidden'):
        raise RuntimeError(
            'redundant validation is forbidden during a fresh publish-only continuation; '
            'reuse the current validation evidence and run web-publish-plan'
        )
    safety = assess_command(command)
    if safety.classification.value == 'safe_known':
        return _delegate(argv)
    emit_ok({
        'executed': False,
        'requires_host_visible_execution': True,
        'safety': safety,
        'identity': identify(command, cwd),
        'cwd': str(cwd),
        'execution_policy': execution_policy(),
        'next': 'run the exact validation through the host tool, then record the observed result with validation-record',
    })
    return 0


def _cmd_validation_record(argv: list[str]) -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--use-active-task', action='store_true')
    p.add_argument('--command-json', required=True)
    p.add_argument('--exit-code', type=int)
    p.add_argument('--evidence')
    p.add_argument('--workload-status', choices=[x.value for x in WorkloadStatus])
    p.add_argument('--workload-evidence-kind', choices=[x.value for x in EvidenceKind])
    p.add_argument('--workload-evidence')
    p.add_argument('--workload-adapter')
    p.add_argument('--process-status', choices=[x.value for x in ProcessStatus])
    p.add_argument('--process-evidence')
    p.add_argument('--cleanup-status', choices=[x.value for x in CleanupStatus])
    p.add_argument('--cleanup-evidence')
    p.add_argument('--protocol-token-verified', action='store_true')
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
    rich_requested = any(value is not None for value in (
        args.workload_status, args.workload_evidence_kind, args.workload_evidence, args.workload_adapter,
        args.process_status, args.process_evidence, args.cleanup_status, args.cleanup_evidence,
    )) or args.protocol_token_verified
    observation = None
    if rich_requested:
        if args.workload_status is None or args.workload_evidence_kind is None or args.process_status is None:
            raise ValueError('rich execution recording requires workload status/evidence kind and process status')
        observation = observation_from_strings(
            workload_status=args.workload_status,
            workload_evidence_kind=args.workload_evidence_kind,
            workload_evidence=args.workload_evidence,
            workload_adapter=args.workload_adapter,
            process_status=args.process_status,
            exit_code=args.exit_code,
            process_evidence=args.process_evidence,
            cleanup_status=args.cleanup_status or CleanupStatus.NOT_REQUIRED.value,
            cleanup_evidence=args.cleanup_evidence,
            protocol_token_verified=args.protocol_token_verified,
        )
        evidence = args.evidence or args.workload_evidence or args.process_evidence or args.cleanup_evidence
    else:
        if args.exit_code is None:
            raise ValueError('validation recording requires --exit-code, or rich workload/process fields')
        evidence = args.evidence
    if not (evidence and str(evidence).strip()):
        raise ValueError('validation-record requires concise observable evidence')
    validation_id = store.record_observed_validation(
        command, args.exit_code, cwd=cwd, evidence=str(evidence), observation=observation
    )
    record = store.latest_validation() or {}
    emit_ok({
        'validation_id': validation_id,
        'cwd': str(cwd),
        'observed_exit_code': record.get('observed_exit_code'),
        'workload_status': record.get('workload_status'),
        'process_status': record.get('process_status'),
        'cleanup_status': record.get('cleanup_status'),
        'warnings': json.loads(record.get('warnings_json') or '[]'),
    })
    return 0


def _path_from(raw: str, cwd: Path) -> Path:
    root = cwd.resolve()
    path = Path(raw)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"relay path resolves outside --cwd root: {resolved}") from exc
    return resolved


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

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_FULL_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _cmd_workspace_sync_offer(argv: list[str]) -> int:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--repository', required=True)
    p.add_argument('--commit', required=True)
    args = p.parse_args(argv[1:])
    repository = args.repository.strip()
    commit = args.commit.strip().lower()
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError('--repository must be an exact GitHub OWNER/REPO name')
    if not _FULL_COMMIT_RE.fullmatch(commit):
        raise ValueError('--commit must be a full 40-hex Git commit SHA')
    repo_name = repository.split('/', 1)[1]
    emit_ok({
        'repository': repository,
        'commit': commit,
        'workflow_path': '.github/workflows/workspace-download.yml',
        'artifact_name': f'{repo_name}-source',
        'sync_method': 'github_actions_artifact',
        'offer_text': f'Local push {commit[:12]} is verified. Sync this commit into the current ChatGPT workspace?',
        'next_action': 'offer only; do not download until the user explicitly accepts workspace synchronization',
    })
    return 0

def _cmd_deployment_provenance_verify(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py deployment-provenance-verify')
    p.add_argument('--skill-root', required=True)
    args = p.parse_args(argv[1:])
    emit_ok(verify_installed_skill(Path(args.skill_root).resolve()))
    return 0



def _cmd_route_init(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py route-init')
    p.add_argument('--session-id')
    p.add_argument('--host-surface', choices=sorted(HOST_SURFACES), default='unknown')
    args = p.parse_args(argv[1:])
    emit_ok(route_init(session_id=args.session_id, host_surface=args.host_surface))
    return 0


def _cmd_route_show(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py route-show')
    p.add_argument('--session-id')
    args = p.parse_args(argv[1:])
    emit_ok(route_show(session_id=args.session_id))
    return 0


def _cmd_route_transition(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py route-transition')
    p.add_argument('--session-id')
    p.add_argument('--workspace-mode', choices=sorted(WORKSPACE_MODES))
    p.add_argument('--interaction-target', choices=sorted(ROUTING_INTERACTION_TARGETS))
    p.add_argument('--deployment-target', choices=sorted(DEPLOYMENT_TARGETS | {'none'}))
    p.add_argument('--selection-evidence')
    p.add_argument('--current-user-selection-observed', action='store_true')
    args = p.parse_args(argv[1:])
    if args.workspace_mode is None and args.interaction_target is None and args.deployment_target is None:
        raise ValueError('route-transition requires at least one routing field')
    emit_ok(route_transition(
        session_id=args.session_id,
        workspace_mode=args.workspace_mode,
        interaction_target=args.interaction_target,
        deployment_target=args.deployment_target,
        selection_evidence=args.selection_evidence,
        current_user_selection_observed=args.current_user_selection_observed,
    ))
    return 0


def _cmd_route_check(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py route-check')
    p.add_argument('--session-id')
    p.add_argument('--action', required=True, choices=sorted(ROUTE_ACTIONS))
    p.add_argument('--workspace-granted', action='store_true')
    p.add_argument('--current-user-local-source-mutation-authorized', action='store_true')
    p.add_argument('--current-user-local-computer-authorized', action='store_true')
    p.add_argument('--current-user-local-install-authorized', action='store_true')
    args = p.parse_args(argv[1:])
    emit_ok(route_check(
        action=args.action,
        session_id=args.session_id,
        workspace_granted=args.workspace_granted,
        local_source_mutation_authorized=args.current_user_local_source_mutation_authorized,
        local_computer_authorized=args.current_user_local_computer_authorized,
        local_install_authorized=args.current_user_local_install_authorized,
    ))
    return 0


def _cmd_source_acquisition_plan(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py source-acquisition-plan')
    p.add_argument('--exact-commit-bundle-available', action='store_true')
    p.add_argument('--receipt-bound-bundle-available', action='store_true')
    p.add_argument('--same-authority-artifact-discovery-exhausted', action='store_true')
    p.add_argument('--fallback-method', choices=sorted(FALLBACK_METHODS))
    p.add_argument('--current-user-fallback-authorization-observed', action='store_true')
    p.add_argument('--authorization-evidence')
    args = p.parse_args(argv[1:])
    emit_ok(source_acquisition_plan(
        exact_commit_bundle_available=args.exact_commit_bundle_available,
        receipt_bound_bundle_available=args.receipt_bound_bundle_available,
        same_authority_artifact_discovery_exhausted=args.same_authority_artifact_discovery_exhausted,
        fallback_method=args.fallback_method,
        current_user_fallback_authorization_observed=args.current_user_fallback_authorization_observed,
        authorization_evidence=args.authorization_evidence,
    ))
    return 0


def _capability_scope_map(values: list[str] | None) -> dict[str,str]:
    out={}
    for raw in values or []:
        if '=' not in raw: raise ValueError('capability scope must use CAPABILITY=SCOPE')
        cap,scope=raw.split('=',1); cap=cap.strip(); scope=scope.strip()
        if cap not in PERMISSION_PROBE_CAPABILITIES: raise ValueError(f'unknown permission capability scope: {cap}')
        if not scope: raise ValueError(f'permission capability scope is empty: {cap}')
        out[cap]=scope
    return out


def _cmd_source_acquisition_verify(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py source-acquisition-verify')
    p.add_argument('--cwd', required=True)
    p.add_argument('--repository', required=True)
    p.add_argument('--expected-commit', required=True)
    p.add_argument('--expected-tree', required=True)
    p.add_argument('--branch')
    p.add_argument('--method', default='github_git_bundle', choices=sorted({"github_git_bundle", "receipt_bound_git_bundle"} | FALLBACK_METHODS))
    args = p.parse_args(argv[1:])
    emit_ok(verify_restored_git_workspace(
        Path(args.cwd).resolve(),
        repository=args.repository,
        expected_commit=args.expected_commit,
        expected_tree=args.expected_tree,
        branch=args.branch,
        method=args.method,
    ))
    return 0


def _read_optional_bounded_json(path_text: str | None, *, label: str) -> dict | None:
    if path_text is None:
        return None
    path = Path(path_text).resolve()
    payload = path.read_bytes()
    if len(payload) > 128 * 1024:
        raise ValueError(f'{label} exceeds 128 KiB')
    try:
        value = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'{label} must be valid UTF-8 JSON') from exc
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a JSON object')
    return value


def _cmd_repository_enter(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py repository-enter')
    p.add_argument('--session-id', required=True)
    p.add_argument('--cwd', required=True)
    p.add_argument('--repository', required=True)
    p.add_argument('--branch', required=True)
    p.add_argument('--remote-head')
    p.add_argument('--remote-tree')
    p.add_argument('--source-provenance-json')
    p.add_argument('--published-source-json')
    p.add_argument('--workspace-cache-json')
    a = p.parse_args(argv[1:])
    gate = route_check(action='repository_observe', session_id=a.session_id)
    if not gate.get('allowed'):
        emit_ok({
            'status': 'BLOCKED',
            'code': 'REPOSITORY_ROUTE_REQUIREMENTS_UNMET',
            'requirements': list(gate.get('requirements') or []),
            'next_action': 'satisfy only the routing requirements and rerun repository-enter',
        })
        return 0
    emit_ok(repository_enter(
        Path(a.cwd).resolve(strict=False),
        repository=a.repository,
        branch=a.branch,
        remote_head=a.remote_head,
        remote_tree=a.remote_tree,
        source_provenance=_read_optional_bounded_json(a.source_provenance_json, label='source provenance'),
        published_source=_read_optional_bounded_json(a.published_source_json, label='published source receipt'),
        workspace_cache=_read_optional_bounded_json(a.workspace_cache_json, label='workspace cache metadata'),
    ))
    return 0


def _cmd_permission_preflight_plan(argv: list[str]) -> int:
    p=argparse.ArgumentParser(prog='codex_loop.py permission-preflight-plan')
    p.add_argument('--session-id'); p.add_argument('--capability',action='append',required=True,choices=sorted(PERMISSION_PROBE_CAPABILITIES))
    p.add_argument('--observation-scope',action='append',default=[]); p.add_argument('--reuse-fresh-observations',action='store_true')
    args=p.parse_args(argv[1:]); emit_ok(permission_preflight_plan(capabilities=args.capability,session_id=args.session_id,
        observation_scopes=_capability_scope_map(args.observation_scope),reuse_fresh_observations=args.reuse_fresh_observations)); return 0


def _cmd_permission_observation_record(argv: list[str]) -> int:
    p=argparse.ArgumentParser(prog='codex_loop.py permission-observation-record'); p.add_argument('--session-id',required=True)
    p.add_argument('--capability',required=True,choices=sorted(PERMISSION_PROBE_CAPABILITIES)); p.add_argument('--scope',required=True); p.add_argument('--evidence',required=True); p.add_argument('--ttl-seconds',type=int,default=14400)
    a=p.parse_args(argv[1:]); emit_ok(record_permission_observation(session_id=a.session_id,capability=a.capability,scope=a.scope,evidence=a.evidence,ttl_seconds=a.ttl_seconds)); return 0


def _cmd_permission_observation_status(argv: list[str]) -> int:
    p=argparse.ArgumentParser(prog='codex_loop.py permission-observation-status'); p.add_argument('--session-id',required=True); p.add_argument('--capability',required=True,choices=sorted(PERMISSION_PROBE_CAPABILITIES)); p.add_argument('--scope',required=True)
    a=p.parse_args(argv[1:]); emit_ok(permission_observation_status(session_id=a.session_id,capability=a.capability,scope=a.scope)); return 0


def _cmd_web_publish_continuation_begin(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py web-publish-continuation-begin')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--repository', required=True)
    p.add_argument('--branch', required=True)
    a = p.parse_args(argv[1:])
    _cwd_path, root, store = _scope_from_argv(argv)
    emit_ok(begin_web_publish_continuation(root, store, repository=a.repository, branch=a.branch))
    return 0


def _cmd_web_publish_bundle(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py web-publish-bundle')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--output', required=True)
    p.add_argument('--prerequisite-commit')
    args = p.parse_args(argv[1:])
    _cwd_path, root, store = _scope_from_argv(argv)
    emit_ok(build_web_publish_bundle(root, store, output=Path(args.output), prerequisite_commit=args.prerequisite_commit))
    return 0


def _cmd_web_publish_archive(argv: list[str]) -> int:
    p=argparse.ArgumentParser(prog='codex_loop.py web-publish-archive'); p.add_argument('--cwd'); p.add_argument('--task-id'); p.add_argument('--output',required=True); p.add_argument('--top-level'); p.add_argument('--prerequisite-commit')
    a=p.parse_args(argv[1:]); cwd,root,store=_scope_from_argv(argv); emit_ok(build_web_publish_archive(root,store,output=Path(a.output),top_level=a.top_level,prerequisite_commit=a.prerequisite_commit)); return 0


def _cmd_publish_enter(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py publish-enter')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--session-id', required=True)
    p.add_argument('--repository', required=True)
    p.add_argument('--branch', required=True)
    p.add_argument('--remote-head', required=True)
    p.add_argument('--remote-tree', required=True)
    p.add_argument('--capability-scope', action='append', default=[])
    p.add_argument('--controller-abi', type=int, required=True)
    p.add_argument('--standard-web', action='store_true')
    p.add_argument('--workspace-granted', action='store_true')
    p.add_argument('--release-id')
    p.add_argument('--remote', default='origin')
    p.add_argument('--release-publish', dest='source_only', action='store_false')
    p.set_defaults(source_only=True)
    a = p.parse_args(argv[1:])
    _cwd_path, root, store = _scope_from_argv(argv)
    emit_ok(publication_enter(
        root,
        store,
        session_id=a.session_id,
        repository=a.repository,
        branch=a.branch,
        remote_head=a.remote_head,
        remote_tree=a.remote_tree,
        capability_scopes=_capability_scope_map(a.capability_scope),
        controller_abi=a.controller_abi,
        standard_web=a.standard_web,
        workspace_granted=a.workspace_granted,
        source_only=a.source_only,
        release_id=a.release_id,
        remote=a.remote,
    ))
    return 0


def _cmd_web_local_sync_plan(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py web-local-sync-plan')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--session-id', required=True)
    p.add_argument('--destination-path', required=True)
    p.add_argument('--workspace-granted', action='store_true')
    p.add_argument('--local-computer-authorized', action='store_true')
    a = p.parse_args(argv[1:])
    _cwd_path, root, store = _scope_from_argv(argv)
    emit_ok(web_local_sync_plan(
        root,
        store,
        session_id=a.session_id,
        destination_path=a.destination_path,
        workspace_granted=a.workspace_granted,
        local_computer_authorized=a.local_computer_authorized,
    ))
    return 0

def _cmd_web_publish_plan(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py web-publish-plan')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--session-id', required=True)
    p.add_argument('--repository', required=True)
    p.add_argument('--branch', required=True)
    p.add_argument('--remote-head', required=True)
    p.add_argument('--remote-tree', required=True)
    p.add_argument('--capability-scope', action='append', default=[])
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        '--verified-tree-fast-path',
        dest='verified_tree_fast_path',
        action='store_true',
        help='compatibility alias; FAST_PUBLISH is already the default',
    )
    mode.add_argument(
        '--standard-web',
        dest='verified_tree_fast_path',
        action='store_false',
        help='explicitly select FULL_VERIFIED_PUBLISH instead of the default FAST_PUBLISH path',
    )
    p.set_defaults(verified_tree_fast_path=True)
    a = p.parse_args(argv[1:])
    cwd, root, store = _scope_from_argv(argv)
    emit_ok(web_publish_plan(
        root,
        store,
        session_id=a.session_id,
        repository=a.repository,
        branch=a.branch,
        remote_head=a.remote_head,
        remote_tree=a.remote_tree,
        capability_scopes=_capability_scope_map(a.capability_scope),
        verified_tree_fast_path=a.verified_tree_fast_path,
    ))
    return 0

def _cmd_interaction_route(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py interaction-route')
    p.add_argument('--requires-web-interaction', action='store_true')
    p.add_argument('--explicit-target', choices=['cloud_browser', 'local_chrome'])
    p.add_argument('--task-requires-local-session', action='store_true')
    p.add_argument('--available-target', action='append', default=[])
    p.add_argument('--current-user-local-computer-authorized', action='store_true')
    args = p.parse_args(argv[1:])
    emit_ok(resolve_interaction_target(
        requires_web_interaction=args.requires_web_interaction,
        explicit_target=args.explicit_target,
        task_requires_local_session=args.task_requires_local_session,
        available_targets=args.available_target,
        local_computer_authorized=args.current_user_local_computer_authorized,
    ))
    return 0


def _cmd_persistence_export(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py persistence-export')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--backend', default='off', choices=['off', 'google_drive'])
    p.add_argument('--repository')
    p.add_argument('--source-commit')
    p.add_argument('--source-tree')
    p.add_argument('--ttl-days', type=int)
    args = p.parse_args(argv[1:])
    if args.backend == 'off':
        emit_ok(persistence_policy('off'))
        return 0
    cwd, root, store = _scope_from_argv(argv)
    manifest = build_state_manifest(
        root, cwd, store, backend=args.backend, repository=args.repository,
        source_commit=args.source_commit, source_tree=args.source_tree, ttl_days=args.ttl_days,
    )
    path = write_state_manifest(store, manifest)
    emit_ok({
        'backend': args.backend,
        'mode': 'state_only',
        'manifest_path': str(path),
        'expires_at': manifest['expires_at'],
        'next': 'host may upload this private temporary file through the connected Google Drive connector; credentials remain host-owned',
    })
    return 0


def _cmd_persistence_validate(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py persistence-validate')
    p.add_argument('--manifest', required=True)
    args = p.parse_args(argv[1:])
    manifest = load_state_manifest(Path(args.manifest).resolve())
    emit_ok({
        'valid': True,
        'schema_version': manifest['schema_version'],
        'task_status': manifest.get('task', {}).get('status'),
        'repository': manifest.get('workspace', {}).get('repository'),
        'expires_at': manifest['expires_at'],
        'resume': manifest.get('resume', {}),
        'rule': 'treat this as recovery evidence; reconcile current workspace/tool/external state before resuming',
    })
    return 0


def _cmd_persistence_resume_plan(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py persistence-resume-plan')
    p.add_argument('--manifest', required=True)
    args = p.parse_args(argv[1:])
    manifest = load_state_manifest(Path(args.manifest).resolve())
    emit_ok(build_resume_plan(manifest))
    return 0


def _cmd_persistence_resume(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py persistence-resume')
    p.add_argument('--cwd')
    p.add_argument('--manifest', required=True)
    p.add_argument('--observations-json', required=True)
    args = p.parse_args(argv[1:])
    cwd = _cwd(args.cwd)
    root = repo_root(cwd)
    manifest = load_state_manifest(Path(args.manifest).resolve())
    observation_path = Path(args.observations_json).resolve()
    payload = observation_path.read_bytes()
    if len(payload) > 256 * 1024:
        raise ValueError('resume observations exceed 256 KiB')
    try:
        observations = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('resume observations must be valid UTF-8 JSON') from exc
    emit_ok(resume_state_manifest(root, manifest, observations))
    return 0


def _cmd_persistence_cleanup_plan(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py persistence-cleanup-plan')
    p.add_argument('--manifest', required=True)
    p.add_argument('--ownership-proven', action='store_true')
    p.add_argument('--bounded-runtime-scope-proven', action='store_true')
    p.add_argument('--recoverable-delete-supported', action='store_true')
    p.add_argument('--permanent-delete-supported', action='store_true')
    args = p.parse_args(argv[1:])
    manifest = load_state_manifest(Path(args.manifest).resolve())
    emit_ok(cleanup_decision(
        manifest,
        ownership_proven=args.ownership_proven,
        bounded_scope_proven=args.bounded_runtime_scope_proven,
        recoverable_delete_supported=args.recoverable_delete_supported,
        permanent_delete_supported=args.permanent_delete_supported,
    ))
    return 0


def _cmd_workspace_cache_create(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-cache-create')
    p.add_argument('--cwd')
    p.add_argument('--output', required=True)
    p.add_argument('--repository')
    args = p.parse_args(argv[1:])
    cwd = _cwd(args.cwd)
    root = repo_root(cwd)
    emit_ok(build_workspace_cache(root, output=Path(args.output), repository=args.repository))
    return 0


def _cmd_workspace_cache_validate(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-cache-validate')
    p.add_argument('--capsule', required=True)
    p.add_argument('--expected-sha256')
    args = p.parse_args(argv[1:])
    data = validate_workspace_cache(Path(args.capsule), expected_sha256=args.expected_sha256)
    data.pop('manifest', None)
    emit_ok(data)
    return 0


def _cmd_workspace_cache_restore(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-cache-restore')
    p.add_argument('--capsule', required=True)
    p.add_argument('--destination', required=True)
    p.add_argument('--expected-sha256')
    p.add_argument('--consumption-receipt-output')
    args = p.parse_args(argv[1:])
    emit_ok(restore_workspace_cache(
        Path(args.capsule),
        destination=Path(args.destination),
        expected_sha256=args.expected_sha256,
        consumption_receipt_output=None if args.consumption_receipt_output is None else Path(args.consumption_receipt_output),
    ))
    return 0


def _cmd_workspace_cache_cleanup_plan(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-cache-cleanup-plan')
    p.add_argument('--objects-json', required=True)
    p.add_argument('--preserve-cache-id', action='append', default=[])
    args = p.parse_args(argv[1:])
    payload = Path(args.objects_json).resolve().read_bytes()
    if len(payload) > 512 * 1024:
        raise ValueError('workspace cache cleanup object list exceeds 512 KiB')
    try:
        objects = json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('workspace cache cleanup object list must be valid UTF-8 JSON') from exc
    if isinstance(objects, dict) and set(objects) == {'objects'}:
        objects = objects['objects']
    emit_ok(workspace_cache_cleanup_plan(objects, preserve_cache_ids=set(args.preserve_cache_id)))
    return 0


def _load_bounded_json_file(path_text: str, max_bytes: int, label: str):
    payload = Path(path_text).resolve().read_bytes()
    if len(payload) > max_bytes:
        raise ValueError(f"{label} exceeds {max_bytes} bytes")
    return json.loads(payload.decode("utf-8"))


def _cmd_drive_cache_register(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="codex_loop.py drive-cache-register")
    p.add_argument("--folder-path", required=True)
    a = p.parse_args(argv[1:])
    emit_ok(register_drive_cache_folder(a.folder_path))
    return 0


def _cmd_drive_cache_unregister(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="codex_loop.py drive-cache-unregister")
    p.add_argument("--folder-path", required=True)
    a = p.parse_args(argv[1:])
    emit_ok(unregister_drive_cache_folder(a.folder_path))
    return 0


def _cmd_drive_cache_list(argv: list[str]) -> int:
    argparse.ArgumentParser(prog="codex_loop.py drive-cache-list").parse_args(argv[1:])
    emit_ok(registered_drive_cache_folders())
    return 0


def _cmd_drive_cache_cleanup_plan(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="codex_loop.py drive-cache-cleanup-plan")
    p.add_argument("--objects-json", required=True)
    a = p.parse_args(argv[1:])
    objects = _load_bounded_json_file(a.objects_json, 1024 * 1024, "Drive cache cleanup object list")
    if isinstance(objects, dict) and set(objects) == {"objects"}:
        objects = objects["objects"]
    emit_ok(drive_cache_cleanup_plan(objects))
    return 0


def _cmd_workspace_register(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-register')
    p.add_argument('--name', required=True)
    p.add_argument('--path', required=True)
    p.add_argument('--kind', required=True, choices=['repository', 'development_root'])
    p.add_argument('--update', action='store_true')
    args = p.parse_args(argv[1:])
    emit_ok(register_workspace(args.name, args.path, args.kind, update=args.update))
    return 0


def _cmd_workspace_registry_list(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-registry-list')
    p.parse_args(argv[1:])
    emit_ok({
        'registry_path': str(registry_path()),
        'workspaces': list_workspaces(),
        'authorization_persisted': False,
    })
    return 0


def _cmd_workspace_resolve(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-resolve')
    p.add_argument('name')
    p.add_argument('--session-id')
    p.add_argument('--host-authorized-root', action='append', default=[])
    p.add_argument('--require-access', action='store_true')
    args = p.parse_args(argv[1:])
    state = resolve_workspace(
        args.name,
        session_id=args.session_id,
        host_authorized_roots=args.host_authorized_root,
    )
    if args.require_access and not state['accessible']:
        reasons = ', '.join(state.get('reasons') or ['workspace access denied'])
        raise PermissionError(f'workspace access denied for {state["name"]}: {reasons}')
    emit_ok(state)
    return 0


def _cmd_workspace_grant(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-grant')
    p.add_argument('name')
    p.add_argument('--session-id')
    p.add_argument('--authorization-evidence', required=True)
    p.add_argument('--current-user-authorization-observed', action='store_true')
    args = p.parse_args(argv[1:])
    emit_ok(grant_workspace(
        args.name,
        args.authorization_evidence,
        session_id=args.session_id,
        current_user_authorization_observed=args.current_user_authorization_observed,
    ))
    return 0


def _cmd_workspace_grants(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-grants')
    p.add_argument('--session-id')
    args = p.parse_args(argv[1:])
    emit_ok(session_grants(session_id=args.session_id))
    return 0


def _cmd_workspace_remove(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py workspace-remove')
    p.add_argument('name')
    args = p.parse_args(argv[1:])
    emit_ok(remove_workspace(args.name))
    return 0


def _delegate(argv: list[str]) -> int:
    args = list(argv)
    command = args[0] if args else ''
    task_scoped = command not in {'bootstrap', 'command-check', 'source-verify', '_serve'}
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
        if argv[0] in {'-h', '--help'}:
            return _print_top_level_help()
        if argv[0] == 'orient':
            return _cmd_orient(argv)
        if argv[0] == 'instructions':
            return _cmd_instructions(argv)
        if argv[0] == 'authority':
            return _cmd_authority(argv)
        if argv[0] == 'next':
            return _cmd_next(argv)
        if argv[0] == 'host-config':
            return _cmd_host_config(argv)
        if argv[0] == 'progress-config':
            return _cmd_progress_config(argv)
        if argv[0] == 'progress-policy':
            return _cmd_progress_policy(argv)
        if argv[0] == 'route-init':
            return _cmd_route_init(argv)
        if argv[0] == 'route-show':
            return _cmd_route_show(argv)
        if argv[0] == 'route-transition':
            return _cmd_route_transition(argv)
        if argv[0] == 'route-check':
            return _cmd_route_check(argv)
        if argv[0] == 'permission-preflight-plan':
            return _cmd_permission_preflight_plan(argv)
        if argv[0] == 'permission-observation-record':
            return _cmd_permission_observation_record(argv)
        if argv[0] == 'permission-observation-status':
            return _cmd_permission_observation_status(argv)
        if argv[0] == 'web-publish-continuation-begin':
            return _cmd_web_publish_continuation_begin(argv)
        if argv[0] == 'web-publish-bundle':
            return _cmd_web_publish_bundle(argv)
        if argv[0] == 'web-publish-archive':
            return _cmd_web_publish_archive(argv)
        if argv[0] == 'publish-enter':
            return _cmd_publish_enter(argv)
        if argv[0] == 'web-publish-plan':
            return _cmd_web_publish_plan(argv)
        if argv[0] == 'web-local-sync-plan':
            return _cmd_web_local_sync_plan(argv)
        if argv[0] == 'source-acquisition-plan':
            return _cmd_source_acquisition_plan(argv)
        if argv[0] == 'source-acquisition-verify':
            return _cmd_source_acquisition_verify(argv)
        if argv[0] == 'repository-enter':
            return _cmd_repository_enter(argv)
        if argv[0] == 'interaction-route':
            return _cmd_interaction_route(argv)
        if argv[0] == 'validate':
            return _cmd_validate(argv)
        if argv[0] == 'validation-record':
            return _cmd_validation_record(argv)
        if argv[0] == 'persistence-export':
            return _cmd_persistence_export(argv)
        if argv[0] == 'persistence-validate':
            return _cmd_persistence_validate(argv)
        if argv[0] == 'persistence-resume-plan':
            return _cmd_persistence_resume_plan(argv)
        if argv[0] == 'persistence-resume':
            return _cmd_persistence_resume(argv)
        if argv[0] == 'persistence-cleanup-plan':
            return _cmd_persistence_cleanup_plan(argv)
        if argv[0] == 'workspace-cache-create':
            return _cmd_workspace_cache_create(argv)
        if argv[0] == 'workspace-cache-validate':
            return _cmd_workspace_cache_validate(argv)
        if argv[0] == 'workspace-cache-restore':
            return _cmd_workspace_cache_restore(argv)
        if argv[0] == 'workspace-cache-cleanup-plan':
            return _cmd_workspace_cache_cleanup_plan(argv)
        if argv[0] == 'drive-cache-register':
            return _cmd_drive_cache_register(argv)
        if argv[0] == 'drive-cache-unregister':
            return _cmd_drive_cache_unregister(argv)
        if argv[0] == 'drive-cache-list':
            return _cmd_drive_cache_list(argv)
        if argv[0] == 'drive-cache-cleanup-plan':
            return _cmd_drive_cache_cleanup_plan(argv)
        if argv[0] == 'workspace-register':
            return _cmd_workspace_register(argv)
        if argv[0] == 'workspace-registry-list':
            return _cmd_workspace_registry_list(argv)
        if argv[0] == 'workspace-resolve':
            return _cmd_workspace_resolve(argv)
        if argv[0] == 'workspace-grant':
            return _cmd_workspace_grant(argv)
        if argv[0] == 'workspace-grants':
            return _cmd_workspace_grants(argv)
        if argv[0] == 'workspace-remove':
            return _cmd_workspace_remove(argv)
        if argv[0] == 'workspace-sync-offer':
            return _cmd_workspace_sync_offer(argv)
        if argv[0] == 'deployment-provenance-verify':
            return _cmd_deployment_provenance_verify(argv)
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
