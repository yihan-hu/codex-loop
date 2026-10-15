"""Bind Local DAG Slots to the existing Codex Loop Logical Isolation lifecycle.

No separate isolation table: the per-Chat StateStore's existing isolations table
owns the projection, role, policy, status and semantic-result authority.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codex_loop_context_projection import build_isolation
from .delegation import abort_isolation, create_isolation, finish_isolation, resolve_semantic_result
from .state import open_store
from .workspace import workspace_fingerprint
from . import local_collaboration as collab


def _binding(record: dict[str, Any]) -> dict[str, Any] | None:
    return (record.get('context_spec') or {}).get('collaboration')


def _token(assignment: dict[str, Any]) -> dict[str, Any]:
    return {
        'run_id': assignment['run_id'],
        'slot': int(assignment['slot']),
        'lease_generation': int(assignment['lease_generation']),
        'task_key': assignment['task_key'],
    }


def _same_slot(a: dict[str, Any] | None, b: dict[str, Any]) -> bool:
    return bool(a and all(a.get(k) == b.get(k) for k in (
        'run_id', 'slot', 'lease_generation', 'task_key')))


def _root(assignment: dict[str, Any]) -> Path:
    return Path(assignment['repo']).expanduser().resolve(strict=True)


def _close_previous(store, active: dict[str, Any], new_token: dict[str, Any],
                    root: Path) -> None:
    old = _binding(active)
    if old is None:
        raise RuntimeError('another Logical Isolation is active; finish/abort it before claiming a new Slot')
    if old['run_id'] != new_token['run_id']:
        raise RuntimeError('Logical Isolation for a different Run is active')
    with collab._connection() as db:
        prior = db.execute('SELECT status,task_id,lease_generation,commit_sha FROM slots '
                           'WHERE run_id=? AND number=?',
                           (old['run_id'],old['slot'])).fetchone()
    if prior and (prior['status'] == 'done' or
                  prior['task_id'] != store.task_id or
                  prior['lease_generation'] != old['lease_generation']):
        if store.semantic_work_for_isolation(active['isolation_id']):
            raise RuntimeError('previous semantic isolation is unfinished; finish or abort it explicitly')
        if prior['status'] == 'done':
            _close_generic(store, active, root, prior['commit_sha'] or '')
        else:
            abort_isolation(root, root, store, active['isolation_id'],
                            'slot ownership was reclaimed before its isolation finished')
        return
    raise RuntimeError('previous Slot Logical Isolation is still active; finish that Slot first')


def _close_generic(store, active: dict[str, Any], root: Path, sha: str) -> None:
    bound = _binding(active)
    if not bound:
        raise RuntimeError('cannot auto-finish a non-Slot isolation')
    if store.semantic_work_for_isolation(active['isolation_id']):
        raise RuntimeError('semantic isolation requires semantic-work-finish and a real stage result')
    if active['mutation_policy'] == 'read_only':
        raise RuntimeError('read-only reviewer must complete through isolate-finish, not an automatic Git receipt')
    # This record closes the behavioral scope after Git acceptance. It is not
    # a model-made semantic judgment and cannot mint a semantic_result_id.
    finish_isolation(root, root, store, active['isolation_id'], {
        'summary': f'Slot {bound["slot"]} scope closed after accepted Git commit {sha}',
        'findings': [],
        'recommended_action': 'follow newly claimed Slot inputs or wait for Ready work',
        'files_inspected': [],
        'limitations': [],
    })



def preflight_claim(task_id: str, run_id: str | None = None) -> None:
    # Fail before reserving a Ready Slot if another, unrelated isolation is
    # active in this Chat. Claim must not leave an orphaned assignment behind.
    store = open_store(None, task_id)
    store.ensure_active()
    active = store.active_isolation()
    if active:
        bound = _binding(active)
        if bound is None or (run_id is not None and bound['run_id'] != run_id):
            raise RuntimeError('unrelated Logical Isolation is active; finish or abort it before claiming another Slot')


def enter_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
    """Start one existing Logical Isolation per new Slot, or return its original."""
    if assignment.get('status') in ('waiting','done') or 'lease_generation' not in assignment:
        return assignment
    store = open_store(None, assignment['task_id'])
    store.ensure_active()
    token = _token(assignment)
    root = _root(assignment)
    active = store.active_isolation()
    if active is not None and not _same_slot(_binding(active),token):
        _close_previous(store, active, token, root)
        active = store.active_isolation()
    if active is not None:
        assignment['logical_isolation'] = build_isolation(
            root, root, store, active['isolation_id'], reconcile=False)
        assignment['logical_isolation']['reused'] = True
        return assignment
    # A manually finished isolation for the SAME Slot must not be re-created
    # if a claim is retried before the caller registers its collab finish.
    history = store.isolation_history(limit=1)
    if history and _same_slot(_binding(history[0]),token) and history[0]['status'] == 'finished':
        assignment['logical_isolation'] = build_isolation(
            root, root, store, history[0]['isolation_id'], reconcile=False)
        assignment['logical_isolation']['reused'] = True
        return assignment
    spec = assignment.get('isolation_spec') or {}
    semantic = spec.get('semantic_work')
    role = spec.get('role', 'semantic-worker' if semantic else 'researcher')
    access = spec.get('mutation_policy', 'read_only' if semantic else 'workspace_write')
    # The stage's worker worktree may differ from the worker's durable
    # lifecycle binding. Semantic authority must detect changes in both.
    token['worktree'] = str(Path(assignment['worktree']).resolve(strict=True))
    # Ordinary writable work needs only the Slot/worktree identity; scanning
    # all file content is necessary only for strict read-only semantic work.
    if semantic:
        token['worktree_fingerprint'] = workspace_fingerprint(Path(token['worktree']))
    result = create_isolation(
        root, root, store, role=role, objective=assignment['title'],
        requested_executor='logical_isolation', actual_executor='logical_isolation',
        project_files=[assignment['worktree']],
        facts=[
            f'Current Run {token["run_id"]}; Slot {token["slot"]}; '
            f'lease generation {token["lease_generation"]}; task key {token["task_key"]}.',
            'Read the full current Slot instructions and verified dependency outputs '
            'from this claim and the current worktree; do not carry assumptions from other Slots.',
        ],
        semantic_work=semantic, mutation_policy=access,
        context_binding=token, checkpoint_at_entry=False,
    )
    assignment['logical_isolation'] = result
    return assignment


def before_finish(run_id: str, task_id: str, slot: int | None) -> None:
    # The Chat may legitimately retry a previously committed finish while a
    # newer Slot isolation is already active. Never treat that as a new result.
    store = open_store(None, task_id)
    with collab._connection() as db:
        prior = db.execute('''SELECT 1 FROM slots WHERE run_id=? AND number=?
            AND completed_by=? AND status='done' LIMIT 1''',
            (run_id,slot,task_id)).fetchone() if slot is not None else None
        row = db.execute('''SELECT * FROM slots WHERE run_id=? AND task_id=?
            AND status='claimed' LIMIT 1''',(run_id,task_id)).fetchone()
    if prior:
        return
    if row is None:
        # A worker may submit the original completed result after lease
        # recovery. Reuse its original Slot scope (active or already finished);
        # never open a new scope or skip semantic authority checks.
        if slot is None:
            raise RuntimeError('late finish requires the original --slot')
        with collab._connection() as db:
            reclaim=db.execute('''SELECT r.old_generation,s.task_key FROM reclaims r
                JOIN slots s ON s.run_id=r.run_id AND s.number=r.slot_number
                WHERE r.run_id=? AND r.slot_number=? AND r.old_task_id=?
                ORDER BY r.id DESC LIMIT 1''',(run_id,slot,task_id)).fetchone()
        if reclaim is None:
            raise RuntimeError('no original Slot assignment for the late finish')
        token={'run_id':run_id,'slot':slot,'lease_generation':reclaim['old_generation'],
               'task_key':reclaim['task_key'] or f'task-{slot}'}
        active=store.active_isolation()
        original=active if active and _same_slot(_binding(active),token) else next(
            (i for i in store.isolation_history(limit=128)
             if _same_slot(_binding(i),token)),None)
        if original is None or original['status'] not in ('active','finished'):
            raise RuntimeError('late finish has no original active or finished Slot Logical Isolation')
        semantic=store.semantic_work_for_isolation(original['isolation_id'])
        if semantic:
            if semantic['status']!='finished' or not semantic['semantic_result_id']:
                raise RuntimeError('semantic Slot must complete through semantic-work-finish before collab finish')
            resolve_semantic_result(
                Path(_run_repo(run_id)),store,semantic['semantic_result_id'],
                consumer=semantic['consumer'],stage=semantic['stage'],
                input_sha256=semantic['input_sha256'],
                instruction_sha256=semantic['instruction_sha256'])
        if original['mutation_policy']=='read_only' and original['status'] != 'finished':
            raise RuntimeError('read-only Slot requires isolate-finish before late collab finish')
        return
    if slot is not None and row['number'] != slot:
        raise RuntimeError('finish targets a different Slot from current ownership')
    spec = json.loads(row['isolation_spec'])
    matching = {
        'run_id':run_id,'slot':row['number'],
        'lease_generation':row['lease_generation'],
        'task_key':row['task_key'] or f'task-{row["number"]}',
    }
    active=store.active_isolation()
    if active is not None and _same_slot(_binding(active),matching):
        if store.semantic_work_for_isolation(active['isolation_id']):
            raise RuntimeError('semantic Slot must complete through semantic-work-finish before collab finish')
        if active['mutation_policy'] == 'read_only':
            raise RuntimeError('read-only Slot must complete through isolate-finish before collab finish')
        return
    if active is not None:
        raise RuntimeError('another Slot Logical Isolation is still active; finish it first')
    prior_iso = next((i for i in store.isolation_history(limit=128)
                      if _same_slot(_binding(i),matching)),None)
    if prior_iso is None or prior_iso['status']!='finished':
        raise RuntimeError('current Slot has no completed or active Logical Isolation; rerun collab claim')
    if 'semantic_work' in spec:
        sem=store.semantic_work_for_isolation(prior_iso['isolation_id'])
        if not sem or sem['status']!='finished' or not sem['semantic_result_id']:
            raise RuntimeError('semantic Slot lacks an accepted semantic-work-finish result')
        source=spec['semantic_work']
        resolve_semantic_result(Path(_run_repo(run_id)),store,sem['semantic_result_id'],
                                consumer=source['consumer'],stage=source['stage'],
                                input_sha256=source['input_sha256'],
                                instruction_sha256=source['instruction_sha256'])


def after_finish(run_id: str, task_id: str, result: dict[str, Any],
                 completed_slot: int | None) -> dict[str, Any]:
    """Finish old Slot scope, then enter any auto-claimed next Slot."""
    store = open_store(None, task_id)
    active = store.active_isolation()
    if active is not None:
        bound = _binding(active)
        if bound and bound['run_id'] == run_id and (
                completed_slot is None or completed_slot == bound['slot']):
            with collab._connection() as db:
                done = db.execute('SELECT status,commit_sha FROM slots WHERE run_id=? AND number=?',
                                  (run_id,bound['slot'])).fetchone()
            if result.get('status') == 'preserved':
                abort_isolation(Path(_run_repo(run_id)),Path(_run_repo(run_id)),store,
                                active['isolation_id'],
                                'late Git result preserved as an alternative; Slot owned elsewhere')
            elif done and done['status'] == 'done':
                if store.semantic_work_for_isolation(active['isolation_id']):
                    raise RuntimeError('semantic Slot finished without a semantic result')
                _close_generic(store, active, Path(_run_repo(run_id)), done['commit_sha'])
    if result.get('continue_now') and isinstance(result.get('next_task'), dict):
        result['next_task'] = enter_assignment(result['next_task'])
    return result


def _run_repo(run_id: str) -> str:
    with collab._connection() as db:
        return collab._run(db, run_id)['repo']
