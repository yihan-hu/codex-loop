"""Same-host Git-worktree coordination.  No daemon, ChatGPT wakeups, or Drive sync.

An active host agent calls these operations through the pinned local Codex Loop
runtime.  The SQLite file is host-local; task authorization and connector access
remain independently enforced by the host before native Git/file operations.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .workspace import run_git
from .release_lineage import capture_workspace_binding
from .workspace_registry import codex_loop_home

RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
TASK_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
REF_RE = re.compile(r"^[a-f0-9]{40,64}$")


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, repo TEXT NOT NULL, git_common_dir TEXT NOT NULL,
  repo_key TEXT NOT NULL, target_branch TEXT NOT NULL, base_commit TEXT NOT NULL,
  goal_key TEXT NOT NULL, planned INTEGER NOT NULL, strategy TEXT NOT NULL,
  worktree_parent TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open',
  integrator_task TEXT, candidate_head TEXT, integration_start_head TEXT,
  integration_attempted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS active_runs ON runs(repo_key, target_branch, goal_key, state);
CREATE TABLE IF NOT EXISTS slots (
  run_id TEXT NOT NULL REFERENCES runs(id), number INTEGER NOT NULL,
  title TEXT NOT NULL, instructions TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'available', task_id TEXT,
  worktree TEXT, commit_sha TEXT,
  PRIMARY KEY(run_id, number), UNIQUE(run_id, task_id), UNIQUE(run_id, worktree)
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_task ON slots(task_id) WHERE task_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  sender TEXT NOT NULL, recipient TEXT, body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS receipts (
  message_id INTEGER NOT NULL, task_id TEXT NOT NULL,
  PRIMARY KEY(message_id, task_id)
);
"""


def _text(value: str, name: str, limit: int = 10000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


def _identifier(value: str, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {name}: {value!r}")
    return value


def _git(root: Path, *args: str) -> str:
    proc = run_git(root, list(args))
    if proc.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout.decode('utf-8', errors='replace').strip()


def _repo_identity(repo: str, branch: str) -> dict[str, str]:
    root = Path(repo).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository must be a directory")
    actual_root = Path(_git(root, 'rev-parse', '--show-toplevel')).resolve()
    if actual_root != root:
        raise ValueError("repository must be a Git worktree root")
    branch = _text(branch, 'target branch', 200)
    _git(root, 'check-ref-format', '--branch', branch)
    base = _git(root, 'rev-parse', '--verify', f'refs/heads/{branch}^{{commit}}')
    common = Path(_git(root, 'rev-parse', '--git-common-dir'))
    if not common.is_absolute():
        common = root / common
    common = common.resolve(strict=True)
    return {
        'repo': str(root), 'git_common_dir': str(common),
        'repo_key': hashlib.sha256(str(common).encode()).hexdigest(),
        'target_branch': branch, 'base_commit': base,
    }


def _verify_same_repo(path: Path, run: sqlite3.Row) -> None:
    common = Path(_git(path, 'rev-parse', '--git-common-dir'))
    if not common.is_absolute():
        common = path / common
    if str(common.resolve(strict=True)) != run['git_common_dir']:
        raise ValueError('worktree is not attached to this run Git repository')


def db_path() -> Path:
    # CODEX_LOOP_HOME is host-local state, not the Git working tree or OneDrive.
    home = codex_loop_home().expanduser()
    if home.is_symlink():
        raise RuntimeError('local collaboration state directory must not be a symlink')
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not home.is_dir():
        raise RuntimeError('local collaboration state directory must be a directory')
    home = home.resolve(strict=True)
    return home / 'local-collaboration.sqlite3'


@contextmanager
def _connection(*, write: bool = False) -> Iterator[sqlite3.Connection]:
    path = db_path()
    if path.is_symlink():
        raise RuntimeError('refusing symlinked collaboration database')
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('collaboration database must be a regular file')
        stat = path.stat()
        if hasattr(os, 'geteuid') and stat.st_uid != os.geteuid():
            raise PermissionError('collaboration database is not owned by this user')
        if stat.st_mode & 0o077:
            os.chmod(path, 0o600)
    else:
        os.close(fd)
    conn = sqlite3.connect(path, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=20000')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript(SCHEMA)
    if write:
        conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
        if write:
            conn.execute('COMMIT')
    except BaseException:
        if write and conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    _identifier(run_id, 'run id', RUN_RE)
    row = conn.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if row is None:
        raise KeyError(f'unknown local collaboration run: {run_id}')
    return row


def _slot(conn: sqlite3.Connection, run_id: str, task_id: str) -> sqlite3.Row:
    row = conn.execute('SELECT * FROM slots WHERE run_id=? AND task_id=?', (run_id, task_id)).fetchone()
    if row is None:
        raise KeyError(f'task {task_id!r} has not claimed a slot in run {run_id!r}')
    return row


def _task(task_id: str) -> str:
    return _identifier(task_id, 'Codex Loop task id', TASK_RE)


def _make_run(conn: sqlite3.Connection, identity: dict[str, str], *, goal: str, strategy: str,
              parent: Path, planned: bool, run_id: str | None = None) -> str:
    if strategy not in ('detached', 'branches'):
        raise ValueError('strategy must be detached or branches')
    run_id = _identifier(run_id, 'run id', RUN_RE) if run_id else (
        f'LWC-{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")}-{secrets.token_hex(4)}')
    if not parent.is_dir():
        raise ValueError(f'worktree parent does not exist: {parent}')
    conn.execute('INSERT INTO runs(id,repo,git_common_dir,repo_key,target_branch,base_commit,goal_key,planned,strategy,worktree_parent) '
                 'VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (run_id, identity['repo'], identity['git_common_dir'], identity['repo_key'],
                  identity['target_branch'], identity['base_commit'], _text(goal, 'goal key', 200),
                  int(planned), strategy, str(parent)))
    return run_id


def create_run(repo: str, target_branch: str, worktree_parent: str,
               tasks: list[dict[str, str]], *, strategy: str = 'detached',
               goal_key: str, run_id: str | None = None) -> dict[str, Any]:
    identity = _repo_identity(repo, target_branch)
    parent = Path(worktree_parent).expanduser().resolve(strict=True)
    if parent == Path(identity['repo']) or parent.is_relative_to(Path(identity['repo'])):
        raise ValueError('worktree parent must be outside the target-branch checkout')
    if not tasks or len(tasks) > 32:
        raise ValueError('planned run requires 1-32 tasks')
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {'title', 'instructions'}:
            raise ValueError('each task must have exactly title and instructions')
        _text(task['title'], 'task title', 200)
        _text(task['instructions'], 'task instructions', 60000)
    with _connection(write=True) as db:
        run = _make_run(db, identity, goal=goal_key, strategy=strategy,
                        parent=parent, planned=True, run_id=run_id)
        for i, task in enumerate(tasks, 1):
            db.execute('INSERT INTO slots(run_id,number,title,instructions) VALUES(?,?,?,?)',
                       (run, i, task['title'], task['instructions']))
    return {'run_id': run, 'slots': len(tasks), 'strategy': strategy,
            'target_branch': target_branch, 'base_commit': identity['base_commit'],
            'worktree_parent': str(parent), 'launch': 'use the identical run-id launch prompt in each fresh chat'}


def discover(repo: str, target_branch: str) -> list[dict[str, Any]]:
    identity = _repo_identity(repo, target_branch)
    with _connection() as db:
        rows = db.execute("SELECT id,goal_key,planned,state,strategy FROM runs WHERE repo_key=? AND target_branch=? AND state='open' ORDER BY rowid",
                          (identity['repo_key'], identity['target_branch'])).fetchall()
        return [dict(row) for row in rows]


def dynamic_join(repo: str, target_branch: str, worktree_parent: str, *, goal_key: str,
                 task_id: str, title: str, instructions: str, strategy: str = 'detached',
                 existing_worktree: str | None = None) -> dict[str, Any]:
    identity = _repo_identity(repo, target_branch)
    parent = Path(worktree_parent).expanduser().resolve(strict=True)
    if parent == Path(identity['repo']) or parent.is_relative_to(Path(identity['repo'])):
        raise ValueError('worktree parent must be outside the target-branch checkout')
    task_id = _task(task_id)
    with _connection(write=True) as db:
        # Recover the original run for the same durable task even after its cohort closed.
        run = db.execute('''SELECT r.* FROM runs r JOIN slots s ON s.run_id=r.id
                            WHERE r.repo_key=? AND r.target_branch=? AND r.goal_key=?
                              AND r.planned=0 AND s.task_id=? ORDER BY r.rowid DESC LIMIT 1''',
                         (identity['repo_key'], identity['target_branch'], _text(goal_key, 'goal key', 200), task_id)).fetchone()
        if run is None:
            run = db.execute("SELECT * FROM runs WHERE repo_key=? AND target_branch=? AND goal_key=? AND planned=0 AND state='open' ORDER BY rowid DESC LIMIT 1",
                             (identity['repo_key'], identity['target_branch'], goal_key)).fetchone()
        if run is None:
            run_id = _make_run(db, identity, goal=goal_key, strategy=strategy, parent=parent, planned=False)
            run = _run(db, run_id)
        else:
            if run['strategy'] != strategy or run['worktree_parent'] != str(parent):
                raise ValueError('existing collaboration uses a different strategy or worktree parent')
            run_id = run['id']
        existing = db.execute('SELECT * FROM slots WHERE run_id=? AND task_id=?', (run_id, task_id)).fetchone()
        if existing is not None:
            number = existing['number']
        else:
            number = int(db.execute('SELECT COALESCE(MAX(number),0)+1 FROM slots WHERE run_id=?', (run_id,)).fetchone()[0])
            db.execute("INSERT INTO slots(run_id,number,title,instructions,status,task_id) VALUES(?,?,?,?, 'claimed', ?)",
                       (run_id, number, _text(title, 'title', 200), _text(instructions, 'instructions', 60000), task_id))
    return claim(run_id, task_id, worktree_parent=worktree_parent, existing_worktree=existing_worktree)


def claim(run_id: str, task_id: str, *, worktree_parent: str,
          existing_worktree: str | None = None) -> dict[str, Any]:
    task_id = _task(task_id)
    # Atomic assignment, but Git setup runs outside SQLite's write transaction.
    with _connection(write=True) as db:
        run = _run(db, run_id)
        parent = Path(worktree_parent).expanduser().resolve(strict=True)
        if str(parent) != run['worktree_parent']:
            raise PermissionError('worktree parent differs from the registered host-authorized parent')
        slot = db.execute('SELECT * FROM slots WHERE run_id=? AND task_id=?', (run_id, task_id)).fetchone()
        if slot is None:
            if run['state'] != 'open' or not run['planned']:
                raise RuntimeError('run is not accepting planned slot claims')
            slot = db.execute("SELECT * FROM slots WHERE run_id=? AND status='available' ORDER BY number LIMIT 1", (run_id,)).fetchone()
            if slot is None:
                raise RuntimeError('no unclaimed slot remains in this run; do not duplicate work')
            db.execute("UPDATE slots SET task_id=?,status='claimed' WHERE run_id=? AND number=? AND status='available'",
                       (task_id, run_id, slot['number']))
        number = slot['number']
        title, instructions = slot['title'], slot['instructions']
        stored = slot['worktree']
        base = run['base_commit']
        strategy = run['strategy']
        repo = Path(run['repo'])
    path = (Path(existing_worktree).expanduser().resolve(strict=True)
            if existing_worktree else parent / f'{run_id}-slot-{number}')
    if stored and stored != str(path):
        raise RuntimeError('task already owns a different worktree; resume the original worktree')
    if existing_worktree:
        _verify_same_repo(path, run)
        if path != repo and path == parent:
            raise ValueError('existing worker worktree cannot equal the worktree parent')
    elif not path.exists():
        if strategy == 'detached':
            _git(repo, 'worktree', 'add', '--detach', str(path), base)
        else:
            branch = f'codex-loop/{run_id}/slot-{number}'
            _git(repo, 'worktree', 'add', '-b', branch, str(path), base)
    _verify_same_repo(path, run)
    if not stored and _git(path, 'rev-parse', '--verify', 'HEAD') != base and not existing_worktree:
        raise RuntimeError('new worker worktree base differs from recorded run base')
    with _connection(write=True) as db:
        current = _slot(db, run_id, task_id)
        if current['worktree'] and current['worktree'] != str(path):
            raise RuntimeError('slot was concurrently assigned another worktree')
        competing = db.execute('''SELECT s.task_id,r.id FROM slots s JOIN runs r ON r.id=s.run_id
                       WHERE s.worktree=? AND s.task_id!=? AND r.state IN ('open','integrating')''',
                       (str(path), task_id)).fetchone()
        if competing:
            raise RuntimeError(f'worktree is already owned by active task {competing["task_id"]}')
        db.execute('UPDATE slots SET worktree=? WHERE run_id=? AND number=?', (str(path), run_id, number))
    source = capture_workspace_binding(repo)
    origin = str(source.get('origin_hint') or '')
    provenance = None
    if origin.startswith('github.com/'):
        provenance = {
            'schema_version': 1, 'kind': 'codex_loop_source_provenance',
            'repository': origin[len('github.com/'):], 'origin_hint': origin,
            'branch': run['target_branch'], 'base_commit': base,
            'base_tree': _git(repo, 'rev-parse', f'{base}^{{tree}}'),
            'path_bound': False, 'verified': True,
            'verification_basis': 'local_collaboration_target_branch_at_run_creation',
        }
    return {'run_id': run_id, 'slot': number, 'task_id': task_id,
            'title': title, 'instructions': instructions,
            'worktree': str(path), 'strategy': strategy, 'base_commit': base,
            'target_branch': run['target_branch'], 'source_provenance': provenance,
            'registered': True,
            'communication': 'read pending messages at next/resume, before editing shared interfaces, and before completion'}


def post_message(run_id: str, task_id: str, body: str, *, recipient_task: str | None = None) -> dict[str, Any]:
    _task(task_id)
    if recipient_task is not None:
        _task(recipient_task)
    with _connection(write=True) as db:
        _run(db, run_id)
        _slot(db, run_id, task_id)
        if recipient_task:
            _slot(db, run_id, recipient_task)
        cur = db.execute('INSERT INTO messages(run_id,sender,recipient,body) VALUES(?,?,?,?)',
                         (run_id, task_id, recipient_task, _text(body, 'message', 30000)))
        return {'message_id': cur.lastrowid, 'delivery': 'queued; receiving Chat reads on its next active turn'}


def inbox(run_id: str, task_id: str, *, ack: list[int] | None = None) -> dict[str, Any]:
    _task(task_id)
    with _connection(write=bool(ack)) as db:
        _run(db, run_id)
        slot = _slot(db, run_id, task_id)
        if ack:
            for mid in ack:
                row = db.execute('SELECT id FROM messages WHERE id=? AND run_id=? AND sender!=? AND (recipient IS NULL OR recipient=?)',
                                 (mid, run_id, task_id, task_id)).fetchone()
                if row is None:
                    raise ValueError(f'message {mid} is not addressed to this task')
                db.execute('INSERT OR IGNORE INTO receipts(message_id,task_id) VALUES(?,?)', (mid, task_id))
        rows = db.execute('''SELECT m.id,m.sender,m.recipient,m.body,m.created_at FROM messages m
          LEFT JOIN receipts a ON a.message_id=m.id AND a.task_id=?
          WHERE m.run_id=? AND m.sender!=? AND (m.recipient IS NULL OR m.recipient=?)
            AND a.message_id IS NULL ORDER BY m.id''', (task_id, run_id, task_id, task_id)).fetchall()
        return {'run_id': run_id, 'slot': slot['number'], 'messages': [dict(row) for row in rows]}


def inbox_for_task(task_id: str) -> list[dict[str, Any]]:
    # Normal next/resume context fetch: read-only, no implicit acknowledgement.
    if not db_path().exists():
        return []
    with _connection() as db:
        runs = db.execute('SELECT run_id FROM slots WHERE task_id=?', (task_id,)).fetchall()
    return [inbox(row['run_id'], task_id) for row in runs]


def _elect(db: sqlite3.Connection, run_id: str, task_id: str) -> dict[str, Any]:
    run = _run(db, run_id)
    states = db.execute('SELECT status,COUNT(*) count FROM slots WHERE run_id=? GROUP BY status', (run_id,)).fetchall()
    counts = {r['status']: r['count'] for r in states}
    if run['state'] == 'open' and counts and set(counts) == {'done'}:
        db.execute("UPDATE runs SET state='integrating',integrator_task=? WHERE id=? AND state='open'", (task_id, run_id))
        return {'integrate_now': True, 'integration_owner': task_id, 'run_state': 'integrating', 'counts': counts}
    return {'integrate_now': run['state'] == 'integrating' and run['integrator_task'] == task_id,
            'integration_owner': run['integrator_task'], 'run_state': run['state'], 'counts': counts}


def finish(run_id: str, task_id: str, *, commit_sha: str) -> dict[str, Any]:
    task_id = _task(task_id)
    if not REF_RE.fullmatch(commit_sha):
        raise ValueError('commit SHA must be a full hexadecimal Git object id')
    with _connection() as db:
        run = _run(db, run_id)
        slot = _slot(db, run_id, task_id)
    if not slot['worktree']:
        raise RuntimeError('no registered worker worktree')
    worktree = Path(slot['worktree'])
    _verify_same_repo(worktree, run)
    observed = _git(worktree, 'rev-parse', '--verify', 'HEAD')
    if observed != commit_sha:
        raise ValueError(f'commit must equal current worktree HEAD: {observed}')
    if run_git(worktree, ['merge-base', '--is-ancestor', run['base_commit'], observed]).returncode:
        raise ValueError('worker HEAD does not descend from shared base')
    if _git(worktree, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('worktree contains uncommitted or untracked work; preserve or resolve before finishing')
    # Keep detached commits reachable after worker worktree is removed.
    ref = f'refs/codex-loop/collab/{run_id}/slot-{slot["number"]}'
    _git(worktree, 'update-ref', ref, observed)
    with _connection(write=True) as db:
        current = _slot(db, run_id, task_id)
        if current['status'] == 'done':
            if current['commit_sha'] != observed:
                raise RuntimeError('completed slot SHA changed; manual reconciliation required')
        elif current['status'] == 'claimed':
            if _run(db, run_id)['state'] != 'open':
                raise RuntimeError('run was closed before this task finished')
            db.execute("UPDATE slots SET status='done',commit_sha=? WHERE run_id=? AND task_id=?", (observed, run_id, task_id))
        else:
            raise RuntimeError(f'cannot finish slot in state {current["status"]}')
        result = _elect(db, run_id, task_id)
    return {'run_id': run_id, 'task_id': task_id, 'commit_sha': observed, **result}


def elect(run_id: str, task_id: str) -> dict[str, Any]:
    _task(task_id)
    with _connection(write=True) as db:
        if _slot(db, run_id, task_id)['status'] != 'done':
            raise RuntimeError('only completed workers can claim integration')
        return {'run_id': run_id, **_elect(db, run_id, task_id)}


def prepare_integration(run_id: str, task_id: str, *, integration_worktree: str) -> dict[str, Any]:
    task_id = _task(task_id)
    with _connection() as db:
        run = _run(db, run_id)
        if run['state'] != 'integrating' or run['integrator_task'] != task_id:
            raise PermissionError('only the elected integrator can merge this run')
        if run['integration_attempted']:
            raise RuntimeError('integration was already attempted; inspect and reconcile Git state before any retry')
        slots = db.execute('SELECT * FROM slots WHERE run_id=? ORDER BY number', (run_id,)).fetchall()
    root = Path(integration_worktree).expanduser().resolve(strict=True)
    _verify_same_repo(root, run)
    if _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') != run['target_branch']:
        raise ValueError('integration worktree must be the sole checkout of the target branch')
    if _git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('integration worktree is dirty; user work must be preserved')
    start = _git(root, 'rev-parse', '--verify', 'HEAD')
    if run_git(root, ['merge-base', '--is-ancestor', run['base_commit'], start]).returncode:
        raise ValueError('integration branch no longer descends from run base')
    batches: list[tuple[int, list[str]]] = []
    for slot in slots:
        if slot['status'] != 'done' or not slot['commit_sha']:
            raise RuntimeError('all slots must be finished and committed')
        commits = _git(root, 'rev-list', '--reverse', f'{run["base_commit"]}..{slot["commit_sha"]}').splitlines()
        for commit in commits:
            if len(_git(root, 'rev-list', '--parents', '-n', '1', commit).split()) != 2:
                raise RuntimeError('merge commit in worker history requires manual integration')
        batches.append((slot['number'], commits))
    # Persist the write intent BEFORE changing the Git index or branch.
    with _connection(write=True) as db:
        fresh = _run(db, run_id)
        if fresh['integration_attempted'] or fresh['state'] != 'integrating' or fresh['integrator_task'] != task_id:
            raise RuntimeError('integration intent changed concurrently')
        db.execute('UPDATE runs SET integration_attempted=1,integration_start_head=? WHERE id=?', (start, run_id))
    try:
        for number, commits in batches:
            if commits:
                _git(root, 'cherry-pick', '-x', *commits)
    except Exception as exc:
        return {'run_id': run_id, 'status': 'CONFLICT_OR_INTERRUPTED',
                'reason': str(exc), 'action': 'the elected agent must inspect Git cherry-pick state, resolve conflicts or abort safely, then validate; do not automatically replay'}
    head = _git(root, 'rev-parse', '--verify', 'HEAD')
    with _connection(write=True) as db:
        db.execute('UPDATE runs SET candidate_head=? WHERE id=? AND integrator_task=? AND state=?',
                   (head, run_id, task_id, 'integrating'))
    return {'run_id': run_id, 'status': 'READY_FOR_TEST', 'candidate_head': head,
            'action': 'run targeted tests; call collab-integration-complete with actual test evidence only after verification'}


def integration_resolved(run_id: str, task_id: str, *, integration_worktree: str, resolution_evidence: str) -> dict[str, Any]:
    """Human/model-led resolution of an interrupted cherry-pick; tests still required."""
    _text(resolution_evidence, 'resolution evidence', 5000)
    with _connection() as db:
        run = _run(db, run_id)
    if run['state'] != 'integrating' or run['integrator_task'] != _task(task_id) or not run['integration_attempted']:
        raise RuntimeError('no interrupted integration owned by this task')
    root = Path(integration_worktree).expanduser().resolve(strict=True)
    _verify_same_repo(root, run)
    if _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') != run['target_branch']:
        raise ValueError('target branch changed')
    if _git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('worktree is not clean after conflict resolution')
    if _git(root, 'rev-parse', '--verify', 'HEAD') == run['integration_start_head']:
        raise RuntimeError('no integration result was committed; inspect missing changes')
    head = _git(root, 'rev-parse', '--verify', 'HEAD')
    # Every original worker commit must appear in the merged target history.
    # -x trailers survive ordinary conflict resolution and prevent prematurely
    # marking a partially cherry-picked run as integrated.
    with _connection() as db:
        slots = db.execute('SELECT commit_sha FROM slots WHERE run_id=? ORDER BY number', (run_id,)).fetchall()
    expected = []
    for slot in slots:
        expected.extend(_git(root, 'rev-list', '--reverse', f'{run["base_commit"]}..{slot["commit_sha"]}').splitlines())
    merged_messages = _git(root, 'log', '--format=%B', f'{run["integration_start_head"]}..HEAD')
    missing = [sha for sha in expected if f'(cherry picked from commit {sha})' not in merged_messages]
    if missing:
        raise RuntimeError(f'worker commits not yet merged: {missing}; continue git cherry-pick -x before resolving')
    with _connection(write=True) as db:
        fresh = _run(db, run_id)
        if fresh['candidate_head'] or fresh['state'] != 'integrating' or fresh['integrator_task'] != task_id:
            raise RuntimeError('integration state already finalized or changed')
        db.execute('UPDATE runs SET candidate_head=? WHERE id=?', (head, run_id))
    return {'run_id': run_id, 'status': 'READY_FOR_TEST', 'candidate_head': head,
            'resolution_evidence': resolution_evidence, 'action': 'review merged diff and run tests before integration-complete'}


def integration_complete(run_id: str, task_id: str, *, integration_worktree: str, test_evidence: str) -> dict[str, Any]:
    task_id = _task(task_id)
    _text(test_evidence, 'test evidence', 5000)
    with _connection() as db:
        run = _run(db, run_id)
    if run['integrator_task'] != task_id or run['state'] != 'integrating' or not run['candidate_head']:
        raise RuntimeError('no completed automatic integration candidate owned by this task')
    root = Path(integration_worktree).expanduser().resolve(strict=True)
    _verify_same_repo(root, run)
    if _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') != run['target_branch']:
        raise ValueError('target branch checkout changed')
    if _git(root, 'rev-parse', '--verify', 'HEAD') != run['candidate_head']:
        raise RuntimeError('target HEAD changed since integration; reconcile before reporting success')
    if _git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('integration worktree is dirty or cherry-pick is incomplete')
    with _connection(write=True) as db:
        row = _run(db, run_id)
        if row['candidate_head'] != run['candidate_head'] or row['state'] != 'integrating':
            raise RuntimeError('integration state changed concurrently')
        db.execute("UPDATE runs SET state='integrated' WHERE id=?", (run_id,))
    return {'run_id': run_id, 'state': 'integrated', 'commit': run['candidate_head'],
            'test_evidence': test_evidence, 'pushed': False}


def status(run_id: str) -> dict[str, Any]:
    with _connection() as db:
        run = _run(db, run_id)
        rows = db.execute('SELECT number,title,status,task_id,worktree,commit_sha FROM slots WHERE run_id=? ORDER BY number', (run_id,)).fetchall()
    return {'run_id': run_id, 'state': run['state'], 'target_branch': run['target_branch'],
            'goal_key': run['goal_key'], 'integrator_task': run['integrator_task'],
            'candidate_head': run['candidate_head'], 'slots': [dict(row) for row in rows]}


def completion_obstacle(task_id: str) -> str | None:
    if not db_path().exists():
        return None
    with _connection() as db:
        rows = db.execute('''SELECT r.state,r.integrator_task,s.status FROM slots s JOIN runs r ON r.id=s.run_id
                                  WHERE s.task_id=?''', (task_id,)).fetchall()
    for row in rows:
        if row['status'] != 'done':
            return 'local collaboration work has not been committed and finished'
        if row['state'] == 'integrating' and row['integrator_task'] == task_id:
            return 'elected local integrator has not completed merged validation'
    return None