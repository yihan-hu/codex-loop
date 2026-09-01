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
from codex_loop_context_projection import build_working
from codex_loop_runtime.change_tracker import sync_generation
from codex_loop_runtime.completion import record_objective_audit
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
from codex_loop_runtime.lifecycle import DURABLE_SIGNAL_KEYS, assess_runtime_need
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
from codex_loop_runtime.state import active_task_id, open_store
from codex_loop_runtime.workspace import repo_root
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
    ('lifecycle-assess', 'decide direct vs durable execution and expose effective progress policy'),
    ('next', 'project the bounded working set for the active durable task'),
    ('host-config', 'show or update the unified private Host Profile'),
    ('progress-config', 'compatibility facade for private progress-visibility preferences'),
    ('progress-policy', 'resolve effective progress behavior for direct or durable work'),
    ('interaction-route', 'resolve Cloud Browser vs local browser target without granting access'),
    ('persistence-export', 'export private cross-conversation recovery state'),
    ('persistence-validate', 'validate a recovery manifest'),
    ('persistence-resume-plan', 'plan deterministic recovery observations'),
    ('persistence-resume', 'reconcile current reality and create a fresh resumed task'),
    ('persistence-cleanup-plan', 'plan recovery-manifest cleanup'),
    ('objective-audit', 'record requirement-by-requirement completion evidence'),
    ('workspace-register', 'register a private host workspace alias'),
    ('workspace-registry-list', 'list private host workspace aliases'),
    ('workspace-resolve', 'resolve a registered workspace under current grants'),
    ('workspace-grant', 'record current-conversation workspace authorization'),
    ('workspace-grants', 'show current-conversation workspace grants'),
    ('workspace-remove', 'remove a private host workspace alias'),
    ('workspace-sync-offer', 'prepare an exact-revision workspace sync offer'),
    ('skill-deploy-handoff', 'plan native current-workspace Skill update reconciliation'),
    ('skill-deploy-resume', 'release a terminal Codex Loop self-update barrier on a later host turn'),
    ('skill-deploy-surface-record', 'record an actually observed native Skill update/install surface'),
    ('skill-deploy-complete', 'record observed activation of the intended Skill revision'),
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
    result = assess_runtime_need(signals)
    result["progress"] = progress_policy(str(result["mode"]))
    emit_ok(result)
    return 0


def _cmd_next(argv: list[str]) -> int:
    cwd, root, store = _scope_from_argv(argv)
    working = build_working(root, cwd, store)
    lifecycle = working.get("lifecycle") or {}
    working["progress"] = progress_policy(str(lifecycle.get("mode", "durable")))
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
    p.add_argument('--lifecycle-mode', required=True, choices=['direct', 'durable'])
    args = p.parse_args(argv[1:])
    emit_ok(progress_policy(args.lifecycle_mode))
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
        'execution_policy': execution_policy(),
        'next': 'run the exact validation through the host tool, observe workload and process outcomes independently, then record authoritative workload/process/cleanup evidence with validation-record; legacy exit-code-only recording remains a compatibility path',
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
    generation = store.generation()
    if args.generation is not None and args.generation != generation:
        raise RuntimeError(f'host validation is stale: observed generation {args.generation} but current generation is {generation}; rerun validation')
    inferred = args.plan_id is None
    plan_id = args.plan_id or _resolve_plan(store, generation, command, cwd)['plan_id']
    rich_requested = any(value is not None for value in (
        args.workload_status, args.workload_evidence_kind, args.workload_evidence, args.workload_adapter,
        args.process_status, args.process_evidence, args.cleanup_status, args.cleanup_evidence,
    )) or args.protocol_token_verified
    observation = None
    if rich_requested:
        if args.workload_status is None or args.workload_evidence_kind is None or args.process_status is None:
            raise ValueError('rich execution recording requires --workload-status, --workload-evidence-kind, and --process-status')
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
            raise ValueError('legacy validation recording requires --exit-code, or provide the rich workload/process execution fields')
        evidence = args.evidence
    if not (evidence and str(evidence).strip()):
        raise ValueError('validation-record requires concise observable evidence')
    validation_id = store.record_host_validation(
        plan_id, generation, command, args.exit_code, cwd=cwd, evidence=str(evidence), observation=observation
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
        'bookkeeping_inferred': inferred,
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


_SELF_UPDATE_BARRIER_KEY = 'skill_self_update_terminal_barrier'


def _skill_deploy_identity(skill_name: str, commit: str) -> str:
    return f'chatgpt-skill:{skill_name}@{commit}'


def _self_update_barrier(store) -> dict | None:
    value = store.get_meta(_SELF_UPDATE_BARRIER_KEY, None)
    return value if isinstance(value, dict) and value.get('active') is True else None


def _skill_deploy_action(store, identity: str) -> dict:
    matches = [
        action for action in store.external_actions()
        if action.get('kind') == 'chatgpt_skill_update'
        and action.get('identity') == identity
        and action.get('action_class') == 'external_non_idempotent'
    ]
    if not matches:
        raise ValueError('no planned Skill deployment handoff exists for this Skill/commit')
    if len(matches) != 1:
        raise RuntimeError('multiple Skill deployment actions exist for the same stable identity')
    return matches[0]


def _parse_skill_deploy_args(argv: list[str], *, include_surface: bool = False, include_evidence: bool = False):
    p = argparse.ArgumentParser(prog=f'codex_loop.py {argv[0]}')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--skill-name', required=True)
    p.add_argument('--repository', required=True)
    p.add_argument('--commit', required=True)
    if include_surface:
        p.add_argument('--surface-kind', required=True, choices=['skill_creator_install_ui', 'host_managed_update'])
    if include_evidence:
        p.add_argument('--evidence', required=True)
    args = p.parse_args(argv[1:])
    skill_name = args.skill_name.strip().lower()
    repository = args.repository.strip()
    commit = args.commit.strip().lower()
    if not skill_name or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', skill_name):
        raise ValueError('--skill-name must be a lowercase Skill name')
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError('--repository must be an exact GitHub OWNER/REPO name')
    if not _FULL_COMMIT_RE.fullmatch(commit):
        raise ValueError('--commit must be a full 40-hex Git commit SHA')
    if include_evidence and not args.evidence.strip():
        raise ValueError('--evidence must contain concise observable evidence')
    return args, skill_name, repository, commit


def _cmd_skill_deploy_handoff(argv: list[str]) -> int:
    args, skill_name, repository, commit = _parse_skill_deploy_args(argv)
    _cwd_path, _root, store = _scope_from_argv(argv)
    store.ensure_active()
    identity = _skill_deploy_identity(skill_name, commit)
    is_self_update = skill_name == 'codex-loop'
    planned_details = {
        'handoff_mode': 'terminal_self_update' if is_self_update else 'native_skill_update',
        'terminal_owner': 'skill-creator/host' if is_self_update else None,
        'reconcile_on_next_turn': bool(is_self_update),
        'same_turn_codex_loop_resume_allowed': False if is_self_update else None,
    }
    action_id = store.record_external(
        'chatgpt_skill_update',
        'planned',
        identity,
        details=planned_details,
        action_class='external_non_idempotent',
    )
    action = store.external_action(action_id)
    action_state = action['state']
    action_details = json.loads(action['details_json']) if action.get('details_json') else {}
    if action_state == 'terminal_success':
        native_update_state = 'NATIVE_UPDATE_CONFIRMED'
        native_surface_state = 'NATIVE_SURFACE_OBSERVED'
        ui_state = 'UI_SURFACED' if action_details.get('ui_surfaced') is True else 'UI_NOT_REQUIRED' if action_details.get('ui_surfaced') is False else 'UI_STATE_UNKNOWN'
        deployment_state = 'DEPLOYED'
    elif action_state in {'dispatched', 'outcome_unknown'}:
        native_update_state = 'NATIVE_UPDATE_DISPATCHED'
        native_surface_state = 'NATIVE_SURFACE_OBSERVED'
        ui_state = 'UI_SURFACED' if action_details.get('ui_surfaced') is True else 'UI_NOT_REQUIRED' if action_details.get('ui_surfaced') is False else 'UI_STATE_UNKNOWN'
        deployment_state = 'DEPLOY_PENDING'
    else:
        native_update_state = 'NATIVE_UPDATE_REQUIRED'
        native_surface_state = 'NATIVE_SURFACE_NOT_OBSERVED'
        ui_state = 'UI_NOT_OBSERVED'
        deployment_state = 'DEPLOY_PENDING'
    terminal_handoff_active = bool(is_self_update and action_state == 'planned')
    if terminal_handoff_active:
        store.set_meta(_SELF_UPDATE_BARRIER_KEY, {
            'active': True,
            'skill_name': skill_name,
            'repository': repository,
            'commit': commit,
            'identity': identity,
            'external_action_id': action_id,
            'terminal_owner': 'skill-creator/host',
        })
    emit_ok({
        'skill_name': skill_name,
        'repository': repository,
        'commit': commit,
        'source_state': 'SOURCE_PUSHED',
        'native_update_state': native_update_state,
        'native_surface_state': native_surface_state,
        'ui_state': ui_state,
        'deployment_state': deployment_state,
        'target': 'current_chatgpt_workspace_skill',
        'native_handoff_owner': 'skill-creator/host',
        'required_action': 'invoke_skill_creator_as_final_current_turn_action' if terminal_handoff_active else 'invoke_skill_creator_or_equivalent_native_skill_update_flow',
        'host_managed_alternative': 'supported_host_managed_skill_update',
        'handoff_mode': 'terminal_self_update' if terminal_handoff_active else 'native_skill_update',
        'terminal_owner': 'skill-creator/host' if terminal_handoff_active else None,
        'codex_loop_resume_allowed': False if terminal_handoff_active else True,
        'same_turn_codex_loop_followup_forbidden': terminal_handoff_active,
        'reconcile_on_next_turn': terminal_handoff_active,
        'next_turn_reconcile_command': 'skill-deploy-resume' if terminal_handoff_active else None,
        'handoff_is_ui_evidence': False,
        'handoff_is_deployment_evidence': False,
        'browser_automation_authorized': False,
        'completion_blocking_until_reconciled': True,
        'external_action_id': action_id,
        'external_action_state': action_state,
    })
    return 0


def _cmd_skill_deploy_resume(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py skill-deploy-resume')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--skill-name', required=True)
    p.add_argument('--repository', required=True)
    p.add_argument('--commit', required=True)
    p.add_argument('--later-host-turn-observed', action='store_true')
    p.add_argument('--evidence', required=True)
    args = p.parse_args(argv[1:])
    skill_name = args.skill_name.strip().lower()
    repository = args.repository.strip()
    commit = args.commit.strip().lower()
    if skill_name != 'codex-loop':
        raise ValueError('skill-deploy-resume is reserved for the terminal Codex Loop self-update handoff')
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError('--repository must be an exact GitHub OWNER/REPO name')
    if not _FULL_COMMIT_RE.fullmatch(commit):
        raise ValueError('--commit must be a full 40-hex Git commit SHA')
    evidence = args.evidence.strip()
    if not args.later_host_turn_observed:
        raise ValueError('terminal self-update reconciliation may resume only on a later host turn; pass --later-host-turn-observed after a new user/host turn is actually observed')
    if not evidence:
        raise ValueError('--evidence must contain concise observable evidence of the later host turn')
    _cwd_path, _root, store = _scope_from_argv(argv)
    store.ensure_active()
    identity = _skill_deploy_identity(skill_name, commit)
    barrier = _self_update_barrier(store)
    if barrier is None:
        raise ValueError('no active terminal Codex Loop self-update barrier exists')
    if barrier.get('identity') != identity or barrier.get('repository') != repository:
        raise ValueError('terminal self-update barrier does not match this Skill/repository/commit')
    action = _skill_deploy_action(store, identity)
    if action['state'] not in {'planned', 'dispatched', 'outcome_unknown'}:
        raise ValueError(f"Skill deployment action is already {action['state']}; terminal barrier cannot be resumed")
    store.set_meta(_SELF_UPDATE_BARRIER_KEY, None)
    emit_ok({
        'skill_name': skill_name,
        'repository': repository,
        'commit': commit,
        'handoff_mode': 'terminal_self_update',
        'terminal_barrier_state': 'RELEASED_ON_LATER_TURN',
        'later_host_turn_observed': True,
        'reconciliation_evidence': evidence,
        'deployment_state': 'DEPLOY_PENDING',
        'next_action': 'reconcile observed native surface and installed revision; do not infer either',
        'external_action_id': action['action_id'],
    })
    return 0


def _cmd_skill_deploy_surface_record(argv: list[str]) -> int:
    args, skill_name, repository, commit = _parse_skill_deploy_args(
        argv, include_surface=True, include_evidence=True
    )
    _cwd_path, _root, store = _scope_from_argv(argv)
    store.ensure_active()
    identity = _skill_deploy_identity(skill_name, commit)
    action = _skill_deploy_action(store, identity)
    if action['state'] not in {'planned', 'dispatched'}:
        raise ValueError(f"Skill deployment action is already {action['state']}; native surface cannot be newly recorded")
    action_id = store.record_external(
        'chatgpt_skill_update',
        'dispatched',
        identity,
        details={
            'surface_kind': args.surface_kind,
            'surface_evidence': args.evidence.strip(),
            'ui_surfaced': args.surface_kind == 'skill_creator_install_ui',
        },
        action_class='external_non_idempotent',
        action_id=action['action_id'],
    )
    emit_ok({
        'skill_name': skill_name,
        'repository': repository,
        'commit': commit,
        'source_state': 'SOURCE_PUSHED',
        'native_update_state': 'NATIVE_UPDATE_DISPATCHED',
        'native_surface_state': 'NATIVE_SURFACE_OBSERVED',
        'ui_state': 'UI_SURFACED' if args.surface_kind == 'skill_creator_install_ui' else 'UI_NOT_REQUIRED',
        'deployment_state': 'DEPLOY_PENDING',
        'surface_kind': args.surface_kind,
        'surface_is_deployment_evidence': False,
        'external_action_id': action_id,
    })
    return 0


def _cmd_skill_deploy_complete(argv: list[str]) -> int:
    args, skill_name, repository, commit = _parse_skill_deploy_args(argv, include_evidence=True)
    _cwd_path, _root, store = _scope_from_argv(argv)
    store.ensure_active()
    identity = _skill_deploy_identity(skill_name, commit)
    action = _skill_deploy_action(store, identity)
    if action['state'] not in {'dispatched', 'outcome_unknown'}:
        raise ValueError('Skill deployment can complete only after a native update/install surface was actually dispatched or observed')
    prior_details = json.loads(action['details_json']) if action.get('details_json') else {}
    action_id = store.record_external(
        'chatgpt_skill_update',
        'terminal_success',
        identity,
        details={
            'observed': args.evidence.strip(),
            'installed_commit': commit,
            'surface_kind': prior_details.get('surface_kind'),
            'ui_surfaced': prior_details.get('ui_surfaced'),
        },
        action_class='external_non_idempotent',
        action_id=action['action_id'],
    )
    emit_ok({
        'skill_name': skill_name,
        'repository': repository,
        'commit': commit,
        'source_state': 'SOURCE_PUSHED',
        'native_update_state': 'NATIVE_UPDATE_CONFIRMED',
        'native_surface_state': 'NATIVE_SURFACE_OBSERVED',
        'deployment_state': 'DEPLOYED',
        'deployment_evidence': args.evidence.strip(),
        'external_action_id': action_id,
    })
    return 0


def _cmd_interaction_route(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py interaction-route')
    p.add_argument('--requires-web-interaction', action='store_true')
    p.add_argument('--explicit-target', choices=['cloud_browser', 'local_chrome'])
    p.add_argument('--task-requires-local-session', action='store_true')
    p.add_argument('--available-target', action='append', default=[])
    p.add_argument('--local-computer-authorized', action='store_true')
    args = p.parse_args(argv[1:])
    emit_ok(resolve_interaction_target(
        requires_web_interaction=args.requires_web_interaction,
        explicit_target=args.explicit_target,
        task_requires_local_session=args.task_requires_local_session,
        available_targets=args.available_target,
        local_computer_authorized=args.local_computer_authorized,
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


def _cmd_objective_audit(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog='codex_loop.py objective-audit')
    p.add_argument('--cwd')
    p.add_argument('--task-id')
    p.add_argument('--audit-json')
    args = p.parse_args(argv[1:])
    _cwd_path, root, store = _scope_from_argv(argv)
    store.ensure_active()
    sync_generation(root, store)
    if args.audit_json is not None:
        raw_text = args.audit_json
    else:
        payload = sys.stdin.buffer.read(64 * 1024 + 1)
        if len(payload) > 64 * 1024:
            raise ValueError('objective audit JSON exceeds 64 KiB')
        try:
            raw_text = payload.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError('objective audit stdin must be valid UTF-8 JSON') from exc
    if not raw_text.strip():
        raise ValueError('objective audit requires JSON via --audit-json or stdin')
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError('objective audit must be valid JSON') from exc
    audit = record_objective_audit(store, raw)
    unresolved = [item for item in audit['requirements'] if item['status'] != 'proven']
    emit_ok({
        'status': 'PASS' if not unresolved else 'CONTINUE',
        'generation': audit['generation'],
        'plan_revision': audit['plan_revision'],
        'requirements_count': len(audit['requirements']),
        'unresolved_count': len(unresolved),
        'upstream_blob': audit['upstream_blob'],
    })
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
    args = p.parse_args(argv[1:])
    emit_ok(grant_workspace(
        args.name,
        args.authorization_evidence,
        session_id=args.session_id,
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


def _enforce_terminal_self_update_barrier(argv: list[str]) -> None:
    if not argv or argv[0] == 'skill-deploy-resume':
        return
    try:
        _cwd_path, _root, store = _scope_from_argv(argv)
    except Exception:
        return
    barrier = _self_update_barrier(store)
    if barrier is None:
        return
    raise RuntimeError(
        'terminal Codex Loop self-update handoff is active; do not run another Codex Loop command in the same turn. '
        'Let skill-creator/the host own the native install surface. On a later user/host turn, run skill-deploy-resume '
        'with --later-host-turn-observed before reconciliation.'
    )


def main() -> int:
    argv = sys.argv[1:]
    try:
        _enforce_terminal_self_update_barrier(argv)
        if not argv:
            return _delegate(argv)
        if argv[0] in {'-h', '--help'}:
            return _print_top_level_help()
        if argv[0] == 'lifecycle-assess':
            return _cmd_lifecycle_assess(argv)
        if argv[0] == 'next':
            return _cmd_next(argv)
        if argv[0] == 'host-config':
            return _cmd_host_config(argv)
        if argv[0] == 'progress-config':
            return _cmd_progress_config(argv)
        if argv[0] == 'progress-policy':
            return _cmd_progress_policy(argv)
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
        if argv[0] == 'objective-audit':
            return _cmd_objective_audit(argv)
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
        if argv[0] == 'skill-deploy-handoff':
            return _cmd_skill_deploy_handoff(argv)
        if argv[0] == 'skill-deploy-resume':
            return _cmd_skill_deploy_resume(argv)
        if argv[0] == 'skill-deploy-surface-record':
            return _cmd_skill_deploy_surface_record(argv)
        if argv[0] == 'skill-deploy-complete':
            return _cmd_skill_deploy_complete(argv)
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
