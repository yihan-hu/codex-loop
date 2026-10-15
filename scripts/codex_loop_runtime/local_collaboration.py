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
import time
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
LEASE_SECONDS = 600


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, repo TEXT NOT NULL, git_common_dir TEXT NOT NULL,
  repo_key TEXT NOT NULL, target_branch TEXT NOT NULL, base_commit TEXT NOT NULL,
  goal_key TEXT NOT NULL, planned INTEGER NOT NULL, strategy TEXT NOT NULL,
  worktree_parent TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open',
  integrator_task TEXT, candidate_head TEXT, integration_start_head TEXT,
  integration_attempted INTEGER NOT NULL DEFAULT 0,
  graph_revision INTEGER NOT NULL DEFAULT 1,
  integrator_generation INTEGER NOT NULL DEFAULT 0, integrator_last_seen REAL
);
CREATE INDEX IF NOT EXISTS active_runs ON runs(repo_key, target_branch, goal_key, state);
CREATE TABLE IF NOT EXISTS slots (
  run_id TEXT NOT NULL REFERENCES runs(id), number INTEGER NOT NULL,
  title TEXT NOT NULL, instructions TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'available', task_id TEXT,
  worktree TEXT, commit_sha TEXT,
  task_key TEXT, pool_id TEXT NOT NULL DEFAULT 'default',
  depends_on TEXT NOT NULL DEFAULT '[]', start_commit TEXT, completed_by TEXT,
  exclude_workers TEXT NOT NULL DEFAULT '[]', review_of TEXT NOT NULL DEFAULT '[]',
  lease_generation INTEGER NOT NULL DEFAULT 0, last_seen REAL,
  checkpoint_sha TEXT, checkpoint_note TEXT,
  PRIMARY KEY(run_id, number), UNIQUE(run_id, task_id), UNIQUE(run_id, worktree)
);
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_task ON slots(task_id) WHERE task_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS workers (
  run_id TEXT NOT NULL REFERENCES runs(id), task_id TEXT NOT NULL,
  worktree TEXT NOT NULL, last_commit TEXT, PRIMARY KEY(run_id, task_id), UNIQUE(run_id, worktree)
);
CREATE TABLE IF NOT EXISTS reclaims (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, slot_number INTEGER NOT NULL,
  old_task_id TEXT NOT NULL, old_worktree TEXT, old_generation INTEGER NOT NULL,
  checkpoint_sha TEXT, checkpoint_note TEXT, reason TEXT NOT NULL,
  reclaimed_at REAL NOT NULL, adopted_by TEXT
);
CREATE INDEX IF NOT EXISTS reclaimed_slots ON reclaims(run_id,slot_number,id);
CREATE TABLE IF NOT EXISTS worker_inputs (
  run_id TEXT NOT NULL, task_id TEXT NOT NULL, source_slot INTEGER NOT NULL,
  PRIMARY KEY(run_id, task_id, source_slot)
);
CREATE TABLE IF NOT EXISTS pool_dispatch (
  run_id TEXT NOT NULL, pool_id TEXT NOT NULL, last_claim INTEGER NOT NULL,
  PRIMARY KEY(run_id,pool_id)
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
  sender TEXT NOT NULL, recipient TEXT, body TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS delegations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id), sender TEXT NOT NULL,
  request_key TEXT NOT NULL, recipient TEXT, title TEXT NOT NULL,
  instructions TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'offered',
  result TEXT, commit_sha TEXT, reject_reason TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(run_id, sender, request_key)
);
CREATE INDEX IF NOT EXISTS pending_delegations ON delegations(run_id,status,recipient);
CREATE TABLE IF NOT EXISTS receipts (
  message_id INTEGER NOT NULL, task_id TEXT NOT NULL,
  PRIMARY KEY(message_id, task_id)
);
CREATE TABLE IF NOT EXISTS serial_tails (
  run_id TEXT PRIMARY KEY REFERENCES runs(id),
  instructions TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  owner_task TEXT, final_head TEXT, evidence TEXT
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
    # Previously created host-local runs retain their slots; add DAG fields in place.
    existing = {row['name'] for row in conn.execute('PRAGMA table_info(slots)')}
    for field, definition in {
        'task_key': 'TEXT', 'pool_id': "TEXT NOT NULL DEFAULT 'default'",
        'depends_on': "TEXT NOT NULL DEFAULT '[]'", 'start_commit': 'TEXT',
        'completed_by': 'TEXT',
        'exclude_workers': "TEXT NOT NULL DEFAULT '[]'",
        'review_of': "TEXT NOT NULL DEFAULT '[]'",
        'lease_generation': 'INTEGER NOT NULL DEFAULT 0',
        'last_seen': 'REAL', 'checkpoint_sha': 'TEXT', 'checkpoint_note': 'TEXT',
    }.items():
        if field not in existing:
            try:
                conn.execute(f'ALTER TABLE slots ADD COLUMN {field} {definition}')
            except sqlite3.OperationalError as exc:
                if 'duplicate column' not in str(exc).lower():
                    raise
    run_fields = {row['name'] for row in conn.execute('PRAGMA table_info(runs)')}
    for name, definition in {
        'graph_revision': 'INTEGER NOT NULL DEFAULT 1',
        'integrator_generation': 'INTEGER NOT NULL DEFAULT 0',
        'integrator_last_seen': 'REAL',
    }.items():
        if name not in run_fields:
            conn.execute(f'ALTER TABLE runs ADD COLUMN {name} {definition}')
    # Existing claimed tasks get one grace period on schema upgrade.
    conn.execute("UPDATE slots SET last_seen=? WHERE status='claimed' AND last_seen IS NULL",
                 (time.time(),))
    conn.execute("UPDATE runs SET integrator_last_seen=? WHERE state IN ('integrating','integrated') "
                 "AND integrator_task IS NOT NULL AND integrator_last_seen IS NULL",
                 (time.time(),))
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS unique_task_key ON slots(run_id,task_key) WHERE task_key IS NOT NULL')
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
    row = conn.execute("""SELECT * FROM slots WHERE run_id=? AND
                (task_id=? OR completed_by=?)
                ORDER BY (status='claimed') DESC, number DESC LIMIT 1""",
                (run_id, task_id, task_id)).fetchone()
    if row is None:
        raise KeyError(f'task {task_id!r} has not claimed a slot in run {run_id!r}')
    return row


def _task(task_id: str) -> str:
    return _identifier(task_id, 'Codex Loop task id', TASK_RE)


def _task_specs(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not tasks or len(tasks) > 10000:
        raise ValueError('planned run requires 1-10000 bounded tasks')
    result = []
    allowed = {'title', 'instructions', 'key', 'pool', 'depends_on',
               'exclude_workers', 'review_of'}
    for i, task in enumerate(tasks, 1):
        if not isinstance(task, dict) or not {'title', 'instructions'} <= set(task) or set(task) - allowed:
            raise ValueError('task requires title/instructions and supported task fields')
        key = _identifier(task.get('key', f'task-{i}'), 'task key', RUN_RE)
        pool = _identifier(task.get('pool', 'default'), 'pool name', RUN_RE)
        deps = task.get('depends_on', [])
        reviews = task.get('review_of', [])
        excluded = task.get('exclude_workers', [])
        for label, values in [('depends_on', deps), ('review_of', reviews),
                              ('exclude_workers', excluded)]:
            if not isinstance(values, list) or any(
                    not isinstance(v, str) or not RUN_RE.fullmatch(v) for v in values):
                raise ValueError(f'task {key}: {label} must be a list of identifiers')
            if len(values) != len(set(values)):
                raise ValueError(f'task {key}: duplicate {label}')
        deps = list(dict.fromkeys(deps + reviews))
        if key in deps:
            raise ValueError(f'task {key}: self dependency or review')
        result.append({'key': key, 'pool': pool, 'depends_on': deps,
                       'review_of': reviews, 'exclude_workers': excluded,
                       'title': _text(task['title'], 'task title', 200),
                       'instructions': _text(task['instructions'], 'task instructions', 60000)})
    by_key = {item['key']: item for item in result}
    if len(by_key) != len(result):
        raise ValueError('task keys must be unique')
    pending = {key: set(item['depends_on']) for key, item in by_key.items()}
    for deps in pending.values():
        for source in deps:
            if source not in by_key:
                raise ValueError(f'unknown task dependency: {source}')
    removed = set()
    while len(removed) < len(pending):
        ready = {key for key, deps in pending.items() if key not in removed and deps <= removed}
        if not ready:
            raise ValueError('cycle in task dependencies')
        removed.update(ready)
    return result


def _stored_specs(db: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    return [{'key': row['task_key'] or f'task-{row["number"]}',
             'pool': row['pool_id'], 'depends_on': json.loads(row['depends_on']),
             'review_of': json.loads(row['review_of']),
             'exclude_workers': json.loads(row['exclude_workers']),
             'title': row['title'], 'instructions': row['instructions']}
            for row in db.execute('SELECT * FROM slots WHERE run_id=? ORDER BY number', (run_id,))]


def _owner_alias(db: sqlite3.Connection, run: sqlite3.Row, task_id: str) -> str:
    ids = [row['task_id'] for row in db.execute(
        'SELECT task_id FROM workers WHERE run_id=? ORDER BY rowid', (run['id'],))]
    number = ids.index(task_id) + 1 if task_id in ids else len(ids) + 1
    project = re.sub(r'[^A-Za-z0-9_-]+', '-', Path(run['repo']).name).strip('-') or 'Project'
    return f'{project}-worker{number}'


def _eligible(db: sqlite3.Connection, run: sqlite3.Row,
              slot: sqlite3.Row, task_id: str) -> bool:
    alias = _owner_alias(db, run, task_id)
    n = alias.rsplit('worker', 1)[-1]
    excluded = set(json.loads(slot['exclude_workers']))
    if {task_id, alias, f'worker{n}'} & excluded:
        return False
    reviews = set(json.loads(slot['review_of']))
    if not reviews:
        return True
    for source in db.execute('SELECT task_key,number,completed_by FROM slots WHERE run_id=?',
                             (run['id'],)):
        if (source['task_key'] or f'task-{source["number"]}') in reviews and source['completed_by'] == task_id:
            return False
    return True


def _active_owner(db: sqlite3.Connection, run_id: str, task_id: str,
                  generation: int | None = None) -> sqlite3.Row:
    slot = db.execute("SELECT * FROM slots WHERE run_id=? AND task_id=? AND status='claimed'",
                      (run_id, task_id)).fetchone()
    if slot is None:
        raise PermissionError('worker no longer owns an active collaboration task')
    if generation is not None and slot['lease_generation'] != generation:
        raise PermissionError('stale task ownership generation')
    return slot


def _touch_owner(db: sqlite3.Connection, run_id: str, task_id: str,
                 generation: int) -> sqlite3.Row:
    slot = _active_owner(db, run_id, task_id, generation)
    db.execute('UPDATE slots SET last_seen=? WHERE run_id=? AND number=?',
               (time.time(), run_id, slot['number']))
    return slot


def _reclaim_slot(db: sqlite3.Connection, run_id: str, slot: sqlite3.Row,
                  reason: str) -> dict[str, Any]:
    # Keep the old worker's worktree and reachable commit references untouched.
    if slot['status'] != 'claimed' or not slot['task_id']:
        raise RuntimeError('only claimed work can be reclaimed')
    previous = {'task_id': slot['task_id'], 'worktree': slot['worktree'],
                'lease_generation': slot['lease_generation'],
                'checkpoint_sha': slot['checkpoint_sha'],
                'checkpoint_note': slot['checkpoint_note']}
    db.execute("""INSERT INTO reclaims(run_id,slot_number,old_task_id,old_worktree,
                  old_generation,checkpoint_sha,checkpoint_note,reason,reclaimed_at)
                  VALUES(?,?,?,?,?,?,?,?,?)""",
               (run_id, slot['number'], slot['task_id'], slot['worktree'],
                slot['lease_generation'], slot['checkpoint_sha'], slot['checkpoint_note'],
                reason, time.time()))
    db.execute("""UPDATE slots SET status='available',task_id=NULL,worktree=NULL,
                  start_commit=NULL,last_seen=NULL,checkpoint_sha=NULL,checkpoint_note=NULL
                  WHERE run_id=? AND number=? AND status='claimed'""",
               (run_id, slot['number']))
    return previous


def _expire_slots(db: sqlite3.Connection, run_id: str, *, returning_task: str | None = None) -> None:
    now = time.time()
    for slot in db.execute("SELECT * FROM slots WHERE run_id=? AND status='claimed'",
                           (run_id,)).fetchall():
        if slot['task_id'] != returning_task and slot['last_seen'] is not None and now - slot['last_seen'] > LEASE_SECONDS:
            _reclaim_slot(db, run_id, slot, '600 seconds without recorded tool activity')


def heartbeat(run_id: str, task_id: str, *, lease_generation: int) -> dict[str, Any]:
    task_id = _task(task_id)
    with _connection(write=True) as db:
        run = _run(db, run_id)
        if run['integrator_task'] == task_id and run['state'] in ('integrating','integrated'):
            if lease_generation != run['integrator_generation']:
                raise PermissionError('stale integration ownership generation')
            db.execute('UPDATE runs SET integrator_last_seen=? WHERE id=?',
                       (time.time(),run_id))
            return {'run_id': run_id, 'integrator': task_id,
                    'lease_generation': lease_generation, 'last_seen': time.time()}
        slot = _touch_owner(db, run_id, task_id, lease_generation)
        return {'run_id': run_id, 'task_key': slot['task_key'],
                'lease_generation': lease_generation, 'last_seen': time.time()}


def reclaim(run_id: str, task_key: str, *, force: bool = False,
            reason: str = 'Lease expired') -> dict[str, Any]:
    task_key = _identifier(task_key, 'task key', RUN_RE)
    reason = _text(reason, 'reclaim reason', 1000)
    with _connection(write=True) as db:
        run = _run(db, run_id)
        if run['state'] != 'open':
            raise RuntimeError('only open runs allow task reclaim')
        slot = db.execute("SELECT * FROM slots WHERE run_id=? AND COALESCE(task_key,'task-'||number)=?",
                          (run_id, task_key)).fetchone()
        if slot is None:
            raise KeyError('task key not found')
        if slot['status'] != 'claimed':
            raise RuntimeError('only claimed tasks can be reclaimed')
        if not force and (slot['last_seen'] is None or
                          time.time() - slot['last_seen'] <= LEASE_SECONDS):
            raise RuntimeError('lease has not expired; explicit force required')
        previous = _reclaim_slot(db, run_id, slot, reason)
        return {'run_id': run_id, 'task_key': task_key, 'previous': previous,
                'reclaimable': True, 'reconcile_external_effects': True}

def publish_task(run_id: str, task_id: str, tasks: dict[str, Any] | list[dict[str, Any]], *,
                 lease_generation: int) -> dict[str, Any]:
    # Publish one new task or an entire cross-dependent task pool atomically.
    task_id = _task(task_id)
    batch = [tasks] if isinstance(tasks, dict) else tasks
    if not isinstance(batch, list) or not batch:
        raise ValueError('publish requires a task object or nonempty task array')
    with _connection(write=True) as db:
        run = _run(db, run_id)
        if run['state'] != 'open' or not run['planned']:
            raise RuntimeError('dynamic tasks require an open planned run')
        _touch_owner(db, run_id, task_id, lease_generation)
        current = _stored_specs(db, run_id)
        validated = _task_specs(current + batch)
        new_tasks = validated[len(current):]
        first_number = db.execute('SELECT COALESCE(MAX(number),0)+1 FROM slots WHERE run_id=?',
                                  (run_id,)).fetchone()[0]
        for offset, new in enumerate(new_tasks):
            db.execute("INSERT INTO slots(run_id,number,title,instructions,task_key,pool_id,"
                       " depends_on,review_of,exclude_workers) VALUES(?,?,?,?,?,?,?,?,?)",
                       (run_id, first_number + offset, new['title'], new['instructions'], new['key'],
                        new['pool'], json.dumps(new['depends_on']), json.dumps(new['review_of']),
                        json.dumps(new['exclude_workers'])))
        db.execute('UPDATE runs SET graph_revision=graph_revision+1 WHERE id=?', (run_id,))
        return {'run_id': run_id, 'task_key': new_tasks[0]['key'] if len(new_tasks) == 1 else None,
                'slot': first_number if len(new_tasks) == 1 else None,
                'published': [item['key'] for item in new_tasks],
                'graph_revision': run['graph_revision'] + 1}



def revise_task(run_id: str, task_id: str, task_key: str,
                updates: dict[str, Any], *,
                lease_generation: int, expected_revision: int) -> dict[str, Any]:
    task_id = _task(task_id)
    task_key = _identifier(task_key, 'task key', RUN_RE)
    editable = {'title','instructions','pool','depends_on','review_of','exclude_workers'}
    if not updates or set(updates) - editable:
        raise ValueError('invalid or empty task updates')
    with _connection(write=True) as db:
        run = _run(db, run_id)
        if run['state'] != 'open' or not run['planned']:
            raise RuntimeError('only an open planned run supports DAG changes')
        if run['graph_revision'] != expected_revision:
            raise RuntimeError('DAG revision has changed; reload task status')
        _touch_owner(db, run_id, task_id, lease_generation)
        current = _stored_specs(db, run_id)
        target = next((t for t in current if t['key'] == task_key), None)
        if target is None:
            raise KeyError('unknown task key')
        slot = db.execute('SELECT status FROM slots WHERE run_id=? AND task_key=?',
                          (run_id, task_key)).fetchone()
        if slot['status'] != 'available':
            raise RuntimeError('claimed or completed tasks cannot be revised')
        changed = {**target, **updates}
        validated = _task_specs([changed if task['key'] == task_key else task for task in current])
        final = next(t for t in validated if t['key'] == task_key)
        db.execute("""UPDATE slots SET title=?,instructions=?,pool_id=?,depends_on=?,
                      review_of=?,exclude_workers=? WHERE run_id=? AND task_key=?""",
                   (final['title'], final['instructions'], final['pool'],
                    json.dumps(final['depends_on']), json.dumps(final['review_of']),
                    json.dumps(final['exclude_workers']), run_id, task_key))
        db.execute('UPDATE runs SET graph_revision=graph_revision+1 WHERE id=?', (run_id,))
        return {'run_id': run_id, 'task_key': task_key,
                'graph_revision': expected_revision + 1}


def checkpoint(run_id: str, task_id: str, *, lease_generation: int,
               commit_sha: str, note: str) -> dict[str, Any]:
    task_id = _task(task_id)
    if not REF_RE.fullmatch(commit_sha):
        raise ValueError('checkpoint requires a full Git commit')
    note = _text(note, 'checkpoint note', 5000)
    with _connection() as db:
        run = _run(db, run_id)
        slot = _active_owner(db, run_id, task_id, lease_generation)
    if not slot['start_commit'] or not slot['worktree']:
        raise RuntimeError('task has not materialized inputs yet')
    root = Path(slot['worktree'])
    _verify_same_repo(root, run)
    if _git(root, 'rev-parse', '--verify', 'HEAD') != commit_sha:
        raise RuntimeError('checkpoint SHA must be worker HEAD')
    if run_git(root, ['merge-base', '--is-ancestor', slot['start_commit'], commit_sha]).returncode:
        raise RuntimeError('checkpoint is not derived from verified task inputs')
    with _connection(write=True) as db:
        current = _touch_owner(db, run_id, task_id, lease_generation)
        if current['number'] != slot['number'] or current['start_commit'] != slot['start_commit']:
            raise PermissionError('task assignment changed during checkpoint')
        # Git ref is written only while ownership is locked and verified.
        ref = f'refs/codex-loop/collab/{run_id}/checkpoint-{slot["number"]}-g{lease_generation}'
        _git(root, 'update-ref', ref, commit_sha)
        db.execute('UPDATE slots SET checkpoint_sha=?,checkpoint_note=? WHERE run_id=? AND number=?',
                   (commit_sha, note, run_id, slot['number']))
    return {'run_id': run_id, 'task_key': slot['task_key'], 'checkpoint_sha': commit_sha}


def _ordered_slots(db: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    slots = db.execute('SELECT * FROM slots WHERE run_id=? ORDER BY number', (run_id,)).fetchall()
    by_key = {slot['task_key'] or f'task-{slot["number"]}': slot for slot in slots}
    ordered, visited = [], set()
    while len(visited) < len(slots):
        completed_keys = {x['task_key'] or f'task-{x["number"]}' for x in ordered}
        ready = [row for row in slots if row['number'] not in visited and
                 set(json.loads(row['depends_on'])).issubset(completed_keys)]
        if not ready:
            raise RuntimeError('stored collaboration task DAG is invalid')
        ordered.extend(ready)
        visited.update(row['number'] for row in ready)
    return ordered


def _ready_slots(db: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    slots = db.execute('SELECT * FROM slots WHERE run_id=? ORDER BY number', (run_id,)).fetchall()
    done = {slot['task_key'] or f'task-{slot["number"]}' for slot in slots if slot['status'] == 'done'}
    return [slot for slot in slots if slot['status'] == 'available' and
            set(json.loads(slot['depends_on'])).issubset(done)]


def _choose_slot(db: sqlite3.Connection, run_id: str, task_id: str) -> sqlite3.Row | None:
    run = _run(db, run_id)
    ready = [slot for slot in _ready_slots(db, run_id) if _eligible(db, run, slot, task_id)]
    if not ready:
        return None
    active = {r['pool_id']: r['n'] for r in db.execute(
        "SELECT pool_id,COUNT(*) n FROM slots WHERE run_id=? AND status='claimed' GROUP BY pool_id", (run_id,))}
    last = {r['pool_id']: r['last_claim'] for r in db.execute(
        'SELECT pool_id,last_claim FROM pool_dispatch WHERE run_id=?', (run_id,))}
    # No capacity ceiling: protect a ready pool with zero active workers first,
    # then rotate under-served pools, while using every available Chat.
    chosen = min(ready, key=lambda slot: (active.get(slot['pool_id'], 0),
                                          last.get(slot['pool_id'], 0), slot['number']))
    next_seq = 1 + max(last.values(), default=0)
    db.execute('INSERT INTO pool_dispatch(run_id,pool_id,last_claim) VALUES(?,?,?) '
               'ON CONFLICT(run_id,pool_id) DO UPDATE SET last_claim=excluded.last_claim',
               (run_id, chosen['pool_id'], next_seq))
    return chosen


def _ancestors(db: sqlite3.Connection, run_id: str, target: sqlite3.Row) -> list[sqlite3.Row]:
    ordered = _ordered_slots(db, run_id)
    by_key = {slot['task_key'] or f'task-{slot["number"]}': slot for slot in ordered}
    required = set()
    frontier = list(json.loads(target['depends_on']))
    while frontier:
        key = frontier.pop()
        if key not in required:
            required.add(key)
            frontier.extend(json.loads(by_key[key]['depends_on']))
    return [slot for slot in ordered if (slot['task_key'] or f'task-{slot["number"]}') in required]


def _own_commits(root: Path, slot: sqlite3.Row) -> list[str]:
    if not slot['start_commit'] or not slot['commit_sha']:
        raise RuntimeError(f'slot {slot["number"]} lacks verified start or final commit')
    if run_git(root, ['merge-base', '--is-ancestor', slot['start_commit'], slot['commit_sha']]).returncode:
        raise RuntimeError(f'slot {slot["number"]} rewritten its source history')
    commits = _git(root, 'rev-list', '--reverse', f'{slot["start_commit"]}..{slot["commit_sha"]}').splitlines()
    for commit in commits:
        if len(_git(root, 'rev-list', '--parents', '-n', '1', commit).split()) != 2:
            raise RuntimeError('merge commit in worker history requires manual integration')
    return commits


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
               goal_key: str, run_id: str | None = None,
               serial_tail: str | None = None) -> dict[str, Any]:
    identity = _repo_identity(repo, target_branch)
    parent = Path(worktree_parent).expanduser().resolve(strict=True)
    if parent == Path(identity['repo']) or parent.is_relative_to(Path(identity['repo'])):
        raise ValueError('worktree parent must be outside the target-branch checkout')
    specs = _task_specs(tasks)
    if serial_tail is not None:
        serial_tail = _text(serial_tail, 'post-integration serial chain', 60000)
    with _connection(write=True) as db:
        run = _make_run(db, identity, goal=goal_key, strategy=strategy,
                        parent=parent, planned=True, run_id=run_id)
        for i, task in enumerate(specs, 1):
            db.execute('''INSERT INTO slots(run_id,number,title,instructions,task_key,pool_id,depends_on,review_of,exclude_workers)
                          VALUES(?,?,?,?,?,?,?,?,?)''',
                       (run, i, task['title'], task['instructions'], task['key'], task['pool'],
                        json.dumps(task['depends_on']),json.dumps(task['review_of']),
                        json.dumps(task['exclude_workers'])))
        if serial_tail is not None:
            db.execute('INSERT INTO serial_tails(run_id,instructions) VALUES(?,?)',
                       (run, serial_tail))
    return {'run_id': run, 'slots': len(specs), 'pools': sorted({t['pool'] for t in specs}), 'strategy': strategy,
            'target_branch': target_branch, 'base_commit': identity['base_commit'],
            'worktree_parent': str(parent), 'serial_tail_planned': serial_tail is not None,
            'launch': 'use the identical run-id launch prompt in each fresh chat'}


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
                              AND r.planned=0 AND (s.task_id=? OR s.completed_by=?) ORDER BY r.rowid DESC LIMIT 1''',
                         (identity['repo_key'], identity['target_branch'], _text(goal_key, 'goal key', 200), task_id, task_id)).fetchone()
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
        if run['state'] == 'open':
            _expire_slots(db, run_id, returning_task=task_id)
        existing = db.execute('SELECT * FROM slots WHERE run_id=? AND (task_id=? OR completed_by=?) ORDER BY number DESC LIMIT 1', (run_id, task_id, task_id)).fetchone()
        abandoned = db.execute("SELECT 1 FROM slots WHERE run_id=? AND status='available' LIMIT 1", (run_id,)).fetchone()
        if existing is not None:
            number = existing['number']
        elif abandoned:
            number = None  # Claim an expired unplanned slot instead of orphaning it.
        else:
            number = int(db.execute('SELECT COALESCE(MAX(number),0)+1 FROM slots WHERE run_id=?', (run_id,)).fetchone()[0])
            db.execute("INSERT INTO slots(run_id,number,title,instructions,status,task_id) VALUES(?,?,?,?, 'claimed', ?)",
                       (run_id, number, _text(title, 'title', 200), _text(instructions, 'instructions', 60000), task_id))
    return claim(run_id, task_id, worktree_parent=worktree_parent, existing_worktree=existing_worktree)


def claim(run_id: str, task_id: str, *, worktree_parent: str,
          existing_worktree: str | None = None) -> dict[str, Any]:
    task_id = _task(task_id)
    # One Codex Loop task_id/Chat owns one worktree, but can finish and pull many
    # independent DAG tasks; SQLite selects a ready task fairly across pools.
    with _connection(write=True) as db:
        run = _run(db, run_id)
        parent = Path(worktree_parent).expanduser().resolve(strict=True)
        if str(parent) != run['worktree_parent']:
            raise PermissionError('worktree parent differs from registered authorized parent')
        if run['state'] == 'open':
            _expire_slots(db, run_id, returning_task=task_id)
        worker = db.execute('SELECT * FROM workers WHERE run_id=? AND task_id=?',
                            (run_id, task_id)).fetchone()
        slot = db.execute("SELECT * FROM slots WHERE run_id=? AND task_id=? AND status='claimed'",
                          (run_id, task_id)).fetchone()
        if slot is None:
            if run['state'] != 'open':
                if worker:
                    last = _slot(db, run_id, task_id)
                    return {'run_id': run_id, 'task_id': task_id, 'slot': last['number'],
                            'status': last['status'], 'worktree': worker['worktree'],
                            'registered': True, 'run_state': run['state']}
                raise RuntimeError('run is not accepting slot claims')
            slot = _choose_slot(db, run_id, task_id)
            if not run['planned'] and slot is None:
                raise RuntimeError('unplanned participants must register through collab join')
            if slot is None:
                offer = db.execute("""SELECT * FROM delegations WHERE run_id=? AND status='offered'
                                       AND recipient IS NULL AND sender!=? ORDER BY id LIMIT 1""", (run_id, task_id)).fetchone()
                if offer is None:
                    if _ready_slots(db, run_id):
                        raise RuntimeError('no eligible ready task for this worker')
                    if db.execute("SELECT 1 FROM slots WHERE run_id=? AND status='available' LIMIT 1", (run_id,)).fetchone():
                        raise RuntimeError('no ready task: remaining tasks are waiting for declared dependencies')
                    raise RuntimeError('no unclaimed slot or pool delegation remains in this run')
                number = int(db.execute('SELECT COALESCE(MAX(number),0)+1 FROM slots WHERE run_id=?',
                                        (run_id,)).fetchone()[0])
                db.execute("""INSERT INTO slots(run_id,number,title,instructions,status,task_id,task_key)
                           VALUES(?,?,?,?,'claimed',?,?)""",
                           (run_id, number, offer['title'], offer['instructions'], task_id, f'delegation-{number}'))
                db.execute("""UPDATE delegations SET status='accepted',recipient=?,updated_at=CURRENT_TIMESTAMP
                              WHERE id=?""", (task_id, offer['id']))
                db.execute('UPDATE slots SET lease_generation=1,last_seen=? WHERE run_id=? AND number=?',
                           (time.time(),run_id,number))
                slot = _active_owner(db, run_id, task_id)
            else:
                db.execute("""UPDATE slots SET task_id=?,status='claimed',
                              lease_generation=lease_generation+1,last_seen=?
                              WHERE run_id=? AND number=? AND status='available'""",
                           (task_id, time.time(), run_id, slot['number']))
                slot = _active_owner(db, run_id, task_id)
        if slot['lease_generation'] == 0:
            db.execute('UPDATE slots SET lease_generation=1 WHERE run_id=? AND number=?',
                       (run_id,slot['number']))
            slot = _active_owner(db, run_id, task_id)
        if slot['status'] == 'claimed':
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=? AND number=?',
                       (time.time(), run_id, slot['number']))
        number, stored = slot['number'], slot['worktree']
        repo, base, strategy = Path(run['repo']), run['base_commit'], run['strategy']
        worktree = worker['worktree'] if worker else str(parent / f'{run_id}-worker-{task_id}')
        if existing_worktree:
            path = Path(existing_worktree).expanduser().resolve(strict=True)
            if worker and str(path) != worker['worktree']:
                raise RuntimeError('Chat already owns a different worktree')
            if not worker:
                worktree = str(path)
        else:
            path = Path(worktree)
        if stored and stored != str(path):
            raise RuntimeError('task has a different registered worktree; resume it')
        if not worker:
            competing = db.execute("""SELECT w.task_id FROM workers w JOIN runs r ON r.id=w.run_id
                                     WHERE w.worktree=? AND w.task_id!=? AND r.state IN ('open','integrating')""",
                                   (str(path), task_id)).fetchone()
            if competing:
                raise RuntimeError('worktree already belongs to another active worker')
            db.execute('INSERT INTO workers(run_id,task_id,worktree) VALUES(?,?,?)',
                       (run_id, task_id, str(path)))
        recovery = db.execute('SELECT * FROM reclaims WHERE run_id=? AND slot_number=? ORDER BY id DESC LIMIT 1',
                              (run_id, number)).fetchone()
        if recovery and recovery['adopted_by'] is None:
            former = recovery['old_task_id']
            # Active delegated obligations follow the task, never vanish with the chat.
            db.execute('''UPDATE delegations SET sender=?,updated_at=CURRENT_TIMESTAMP
                          WHERE run_id=? AND sender=? AND status NOT IN ('completed','cancelled')''',
                       (task_id,run_id,former))
            db.execute('''UPDATE delegations SET status='offered',recipient=NULL,
                          reject_reason='recipient lease reclaimed',updated_at=CURRENT_TIMESTAMP
                          WHERE run_id=? AND recipient=? AND status IN ('accepted','rejected')''',
                       (run_id,former))
            db.execute('UPDATE reclaims SET adopted_by=? WHERE id=?',(task_id,recovery['id']))
        if worker and worker['last_commit'] and slot['start_commit'] is None:
            expected_previous_head = worker['last_commit']
        else:
            expected_previous_head = None
    if existing_worktree:
        _verify_same_repo(path, run)
        if path == parent:
            raise ValueError('existing worktree cannot equal worktree parent')
    elif not path.exists():
        if strategy == 'detached':
            _git(repo, 'worktree', 'add', '--detach', str(path), base)
        else:
            _git(repo, 'worktree', 'add', '-b', f'codex-loop/{run_id}/worker-{task_id}', str(path), base)
    _verify_same_repo(path, run)
    resumed_active = bool(stored and slot['start_commit'])
    resumed_legacy = bool(stored and not slot['start_commit'] and not slot['task_key'])
    if not resumed_active and not resumed_legacy and _git(path, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('worker worktree has uncommitted work; preserve or resolve it before claiming')
    head = _git(path, 'rev-parse', '--verify', 'HEAD')
    if expected_previous_head and head != expected_previous_head:
        raise RuntimeError('worker HEAD changed after its previous completed task; reconcile before claiming')
    if not worker and not existing_worktree and not stored and head != base:
        raise RuntimeError('new worker worktree base differs from recorded run base')
    if not slot['start_commit']:
        if resumed_legacy:
            # Existing pre-DAG workers can resume dirty or committed in-flight work.
            # Their full branch delta still starts from the recorded Run baseline.
            head = base
        with _connection() as db:
            current = db.execute('SELECT * FROM slots WHERE run_id=? AND number=?', (run_id, number)).fetchone()
            sources = [] if resumed_legacy else _ancestors(db, run_id, current)
            applied = {row['source_slot'] for row in db.execute(
                'SELECT source_slot FROM worker_inputs WHERE run_id=? AND task_id=?', (run_id, task_id))}
        for source in sources:
            if source['number'] in applied:
                continue
            if source['status'] != 'done':
                raise RuntimeError('dependency was invalidated before its materialization')
            commits = _own_commits(repo, source)
            if source['completed_by'] == task_id:
                if run_git(path, ['merge-base','--is-ancestor', source['commit_sha'], head]).returncode:
                    raise RuntimeError('worker lost a previous dependency commit')
            else:
                # Re-entry after an interrupted write: recognize -x trailers
                # rather than replaying an ambiguous cherry-pick.
                messages = _git(path, 'log', '--format=%B', f'{base}..HEAD')
                missing = [sha for sha in commits if
                           f'(cherry picked from commit {sha})' not in messages]
                if len(missing) != len(commits) and missing:
                    raise RuntimeError('partial dependency cherry-pick; inspect and reconcile Git history')
                if missing:
                    try:
                        _git(path, 'cherry-pick', '-x', *missing)
                    except Exception as exc:
                        raise RuntimeError(f'dependency materialization interrupted: {exc}; '
                                           'resolve native Git state, then retry claim') from exc
            head = _git(path, 'rev-parse', '--verify', 'HEAD')
            with _connection(write=True) as db:
                db.execute('INSERT OR IGNORE INTO worker_inputs(run_id,task_id,source_slot) VALUES(?,?,?)',
                           (run_id, task_id, source['number']))
        with _connection(write=True) as db:
            current = _active_owner(db, run_id, task_id, slot['lease_generation'])
            if current['number'] != number:
                raise PermissionError('another task replaced the materializing claim')
            updated = db.execute('UPDATE slots SET worktree=?,start_commit=? WHERE run_id=? AND number=? AND task_id=?',
                                 (str(path), head, run_id, number, task_id))
            if updated.rowcount != 1:
                raise PermissionError('lease changed while materializing task inputs')
    source = capture_workspace_binding(repo)
    origin = str(source.get('origin_hint') or '')
    provenance = None
    if origin.startswith('github.com/'):
        provenance = {'schema_version': 1, 'kind': 'codex_loop_source_provenance',
                      'repository': origin[len('github.com/'):], 'origin_hint': origin,
                      'branch': run['target_branch'], 'base_commit': base,
                      'base_tree': _git(repo, 'rev-parse', f'{base}^{{tree}}'),
                      'path_bound': False, 'verified': True,
                      'verification_basis': 'local_collaboration_target_branch_at_run_creation'}
    with _connection() as db:
        recovery = db.execute('SELECT * FROM reclaims WHERE run_id=? AND slot_number=? ORDER BY id DESC LIMIT 1',
                              (run_id,number)).fetchone()
    return {'run_id': run_id, 'slot': number, 'task_id': task_id,
            'task_key': slot['task_key'] or f'task-{number}', 'pool': slot['pool_id'],
            'depends_on': json.loads(slot['depends_on']),
            'title': slot['title'], 'instructions': slot['instructions'],
            'worktree': str(path), 'strategy': strategy, 'base_commit': base,
            'lease_generation': slot['lease_generation'],
            'last_seen': time.time(),
            'recovery': dict(recovery) if recovery else None,
            'reconcile_external_effects': bool(recovery),
            'target_branch': run['target_branch'], 'source_provenance': provenance,
            'registered': True,
            'communication': 'read pending messages at next/resume and before shared interface edits'}


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
        serial = db.execute('SELECT * FROM serial_tails WHERE run_id=? AND owner_task=?',
                            (run_id, task_id)).fetchone()
        return {'run_id': run_id, 'slot': slot['number'], 'messages': [dict(row) for row in rows],
                'delegations': _delegations_for(db, run_id, task_id),
                'serial_tail': dict(serial) if serial else None}


def inbox_for_task(task_id: str) -> list[dict[str, Any]]:
    # Normal next/resume context fetch: read-only, no implicit acknowledgement.
    if not db_path().exists():
        return []
    with _connection() as db:
        runs = db.execute('SELECT run_id FROM workers WHERE task_id=?', (task_id,)).fetchall()
    return [inbox(row['run_id'], task_id) for row in runs]


def _delegation(db: sqlite3.Connection, run_id: str, delegation_id: int) -> sqlite3.Row:
    row = db.execute('SELECT * FROM delegations WHERE run_id=? AND id=?',
                     (run_id, delegation_id)).fetchone()
    if row is None:
        raise KeyError(f'unknown delegation {delegation_id} in run {run_id}')
    return row


def _available_recipient(db: sqlite3.Connection, run_id: str, task_id: str) -> None:
    slot = _slot(db, run_id, task_id)
    if slot['status'] != 'claimed' or not slot['worktree']:
        raise RuntimeError('delegation recipient must be an active, worktree-bound participant')


def _notice(db: sqlite3.Connection, run_id: str, sender: str, recipient: str, body: str) -> None:
    db.execute('INSERT INTO messages(run_id,sender,recipient,body) VALUES(?,?,?,?)',
               (run_id, sender, recipient, body))


def delegate(run_id: str, task_id: str, *, request_key: str, title: str,
             instructions: str, recipient_task: str | None = None) -> dict[str, Any]:
    # A stable request key makes retries idempotent across interrupted host calls.
    task_id = _task(task_id)
    request_key = _identifier(request_key, 'delegation request key', RUN_RE)
    title = _text(title, 'delegation title', 200)
    instructions = _text(instructions, 'delegation instructions', 60000)
    if recipient_task is not None:
        recipient_task = _task(recipient_task)
        if recipient_task == task_id:
            raise ValueError('a worker cannot delegate to itself')
    with _connection(write=True) as db:
        run = _run(db, run_id)
        source = _slot(db, run_id, task_id)
        existing = db.execute('SELECT * FROM delegations WHERE run_id=? AND sender=? AND request_key=?',
                              (run_id, task_id, request_key)).fetchone()
        if existing is not None:
            if (existing['title'], existing['instructions']) != (title, instructions):
                raise RuntimeError('delegation request key reused for different work')
            # Subsequent accept/reassign operations must not be undone by a caller retry.
            return dict(existing)
        if run['state'] != 'open' or source['status'] != 'claimed' or not source['worktree']:
            raise RuntimeError('only an active worker may delegate before integration')
        if recipient_task:
            _available_recipient(db, run_id, recipient_task)
        cur = db.execute('''INSERT INTO delegations(run_id,sender,request_key,recipient,title,instructions)
                            VALUES(?,?,?,?,?,?)''',
                         (run_id, task_id, request_key, recipient_task, title, instructions))
        return dict(_delegation(db, run_id, cur.lastrowid))


def accept_delegation(run_id: str, task_id: str, *, delegation_id: int) -> dict[str, Any]:
    task_id = _task(task_id)
    with _connection(write=True) as db:
        run = _run(db, run_id)
        item = _delegation(db, run_id, delegation_id)
        if item['status'] == 'accepted' and item['recipient'] == task_id:
            return dict(item)
        if run['state'] != 'open' or item['status'] != 'offered':
            raise RuntimeError('delegation is not open for acceptance')
        if item['sender'] == task_id or (item['recipient'] is not None and item['recipient'] != task_id):
            raise PermissionError('delegation is not offered to this worker')
        _available_recipient(db, run_id, task_id)
        db.execute('''UPDATE delegations SET status='accepted',recipient=?,updated_at=CURRENT_TIMESTAMP
                      WHERE id=?''', (task_id, delegation_id))
        _notice(db, run_id, task_id, item['sender'],
                f'Delegation #{delegation_id} accepted by {task_id}: {item["title"]}')
        return dict(_delegation(db, run_id, delegation_id))


def reject_delegation(run_id: str, task_id: str, *, delegation_id: int, reason: str) -> dict[str, Any]:
    task_id = _task(task_id)
    reason = _text(reason, 'rejection reason', 5000)
    with _connection(write=True) as db:
        item = _delegation(db, run_id, delegation_id)
        if item['recipient'] != task_id:
            raise PermissionError('only the assigned recipient may reject this delegation')
        if item['status'] == 'rejected':
            return dict(item)
        if item['status'] not in ('offered', 'accepted') or _run(db, run_id)['state'] != 'open':
            raise RuntimeError('delegation cannot be rejected in this state')
        db.execute('''UPDATE delegations SET status='rejected',reject_reason=?,updated_at=CURRENT_TIMESTAMP
                      WHERE id=?''', (reason, delegation_id))
        _notice(db, run_id, task_id, item['sender'],
                f'Delegation #{delegation_id} rejected by {task_id}: {reason}. Reoffer or cancel.')
        return dict(_delegation(db, run_id, delegation_id))


def reoffer_delegation(run_id: str, task_id: str, *, delegation_id: int,
                       recipient_task: str | None = None) -> dict[str, Any]:
    task_id = _task(task_id)
    if recipient_task is not None:
        recipient_task = _task(recipient_task)
        if recipient_task == task_id:
            raise ValueError('a worker cannot delegate to itself')
    with _connection(write=True) as db:
        item = _delegation(db, run_id, delegation_id)
        if item['sender'] != task_id:
            raise PermissionError('only the originating worker may reoffer work')
        if _run(db, run_id)['state'] != 'open':
            raise RuntimeError('cannot reoffer work after integration started')
        if item['status'] == 'offered' and item['recipient'] == recipient_task:
            return dict(item)
        if item['status'] != 'rejected':
            raise RuntimeError('only rejected work can be reoffered')
        if recipient_task:
            _available_recipient(db, run_id, recipient_task)
        db.execute('''UPDATE delegations SET status='offered',recipient=?,reject_reason=NULL,
                      updated_at=CURRENT_TIMESTAMP WHERE id=?''', (recipient_task, delegation_id))
        return dict(_delegation(db, run_id, delegation_id))


def cancel_delegation(run_id: str, task_id: str, *, delegation_id: int, reason: str) -> dict[str, Any]:
    task_id = _task(task_id)
    reason = _text(reason, 'cancellation reason', 5000)
    with _connection(write=True) as db:
        item = _delegation(db, run_id, delegation_id)
        if item['sender'] != task_id:
            raise PermissionError('only the originating worker can withdraw delegated work')
        if item['status'] == 'cancelled':
            return dict(item)
        if _run(db, run_id)['state'] != 'open' or item['status'] not in ('offered', 'rejected'):
            raise RuntimeError('accepted or completed work cannot be cancelled; ask recipient to reject first')
        db.execute('''UPDATE delegations SET status='cancelled',result=?,updated_at=CURRENT_TIMESTAMP
                      WHERE id=?''', (reason, delegation_id))
        cleared = dict(_delegation(db, run_id, delegation_id))
        if _slot(db, run_id, task_id)['status'] == 'done':
            cleared['election'] = _elect(db, run_id, task_id)
        return cleared


def complete_delegation(run_id: str, task_id: str, *, delegation_id: int,
                        result: str, commit_sha: str | None = None) -> dict[str, Any]:
    # A source-changing result can cite a commit reachable from recipient HEAD.
    task_id = _task(task_id)
    result = _text(result, 'delegation result', 10000)
    if commit_sha is not None and not REF_RE.fullmatch(commit_sha):
        raise ValueError('delegation commit SHA must be a full Git object ID')
    with _connection() as db:
        run = _run(db, run_id)
        item = _delegation(db, run_id, delegation_id)
        slot = _slot(db, run_id, task_id)
    if item['recipient'] != task_id:
        raise PermissionError('only the accepted worker can complete this delegation')
    if item['status'] == 'completed':
        if (item['result'], item['commit_sha']) != (result, commit_sha):
            raise RuntimeError('completed delegation result changed; inspect before retry')
        return dict(item)
    if run['state'] != 'open' or item['status'] != 'accepted' or slot['status'] != 'claimed':
        raise RuntimeError('delegation is not accepted by an active worker')
    if commit_sha:
        worktree = Path(slot['worktree'])
        _verify_same_repo(worktree, run)
        if run_git(worktree, ['merge-base', '--is-ancestor', commit_sha, 'HEAD']).returncode:
            raise RuntimeError('delegation commit is not in recipient worktree HEAD')
        if run_git(worktree, ['merge-base', '--is-ancestor', run['base_commit'], commit_sha]).returncode:
            raise RuntimeError('delegation commit is not descended from shared base')
    with _connection(write=True) as db:
        item = _delegation(db, run_id, delegation_id)
        if item['status'] == 'completed' and (item['result'], item['commit_sha']) == (result, commit_sha):
            return dict(item)
        if item['status'] != 'accepted' or item['recipient'] != task_id or _run(db, run_id)['state'] != 'open':
            raise RuntimeError('delegation changed while result was checked')
        db.execute('''UPDATE delegations SET status='completed',result=?,commit_sha=?,
                      updated_at=CURRENT_TIMESTAMP WHERE id=?''', (result, commit_sha, delegation_id))
        _notice(db, run_id, task_id, item['sender'],
                f'Delegation #{delegation_id} completed by {task_id}: {result[:500]}')
        return dict(_delegation(db, run_id, delegation_id))


def _delegations_for(db: sqlite3.Connection, run_id: str, task_id: str) -> list[dict[str, Any]]:
    # Include current open-pool offers so any already-running worker can claim them.
    rows = db.execute('''SELECT * FROM delegations WHERE run_id=? AND
          (sender=? OR recipient=? OR (status='offered' AND recipient IS NULL)) ORDER BY id''',
          (run_id, task_id, task_id)).fetchall()
    return [dict(row) for row in rows]


def _elect(db: sqlite3.Connection, run_id: str, task_id: str) -> dict[str, Any]:
    run = _run(db, run_id)
    states = db.execute('SELECT status,COUNT(*) count FROM slots WHERE run_id=? GROUP BY status', (run_id,)).fetchall()
    counts = {r['status']: r['count'] for r in states}
    pending = db.execute("SELECT COUNT(*) FROM delegations WHERE run_id=? AND status NOT IN ('completed','cancelled')",
                         (run_id,)).fetchone()[0]
    if run['state'] == 'open' and counts and set(counts) == {'done'} and not pending:
        db.execute("""UPDATE runs SET state='integrating',integrator_task=?,
                      integrator_generation=1,integrator_last_seen=?
                      WHERE id=? AND state='open'""", (task_id,time.time(),run_id))
        return {'integrate_now': True, 'integration_owner': task_id,
                'integrator_generation': 1, 'run_state': 'integrating',
                'counts': counts, 'pending_delegations': 0}
    return {'integrate_now': run['state'] == 'integrating' and run['integrator_task'] == task_id,
            'integration_owner': run['integrator_task'],
            'integrator_generation': run['integrator_generation'],
            'run_state': run['state'], 'counts': counts, 'pending_delegations': pending}


def finish(run_id: str, task_id: str, *, commit_sha: str, auto_claim: bool = True,
           slot_number: int | None = None, lease_generation: int | None = None) -> dict[str, Any]:
    task_id = _task(task_id)
    if not REF_RE.fullmatch(commit_sha):
        raise ValueError('commit SHA must be a full hexadecimal Git object id')
    with _connection() as db:
        run = _run(db, run_id)
        # Retried finish after an ambiguous response must never finish the next
        # task accidentally, even if the Chat already auto-claimed it.
        active = db.execute("SELECT * FROM slots WHERE run_id=? AND task_id=? AND status='claimed'",
                            (run_id, task_id)).fetchone()
        if slot_number is not None and (not isinstance(slot_number, int) or slot_number < 1):
            raise ValueError('slot number must be a positive integer')
        prior = db.execute("""SELECT * FROM slots WHERE run_id=? AND completed_by=?
                              AND commit_sha=? AND status='done' AND (? IS NULL OR number=?)
                              ORDER BY number DESC LIMIT 1""",
                           (run_id, task_id, commit_sha, slot_number, slot_number)).fetchone()
        if slot_number is not None and active and slot_number != active['number'] and not prior:
            raise RuntimeError('slot number differs from the current claimed task')
        if prior:
            if slot_number is None and active and active['start_commit']==commit_sha:
                raise RuntimeError('ambiguous no-op finish: pass the claimed --slot number')
            return {'run_id': run_id, 'task_id': task_id, 'commit_sha': commit_sha,
                    'already_finished': True, 'continue_now': bool(active),
                    'next_slot': active['number'] if active else None,
                    'integrate_now': run['state']=='integrating' and run['integrator_task']==task_id}
        slot = active
        if slot and ((lease_generation is not None and lease_generation != slot['lease_generation']) or
                     (lease_generation is None and slot['lease_generation'] > 1)):
            raise PermissionError('task ownership generation changed or missing after reclaim')
    if not slot or not slot['worktree'] or not slot['start_commit']:
        raise RuntimeError('no materialized, claimed task is registered for this worker')
    worktree = Path(slot['worktree'])
    _verify_same_repo(worktree, run)
    observed = _git(worktree, 'rev-parse', '--verify', 'HEAD')
    if observed != commit_sha:
        raise ValueError(f'commit must equal current worktree HEAD: {observed}')
    if run_git(worktree, ['merge-base', '--is-ancestor', slot['start_commit'], observed]).returncode:
        raise ValueError('worker output no longer descends from its verified task inputs')
    if _git(worktree, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('worktree contains uncommitted or untracked work; preserve before finishing')
    with _connection() as db:
        reported_commits = db.execute("""SELECT id,commit_sha FROM delegations WHERE run_id=? AND
                                recipient=? AND status='completed' AND commit_sha IS NOT NULL""",
                                      (run_id, task_id)).fetchall()
    for record in reported_commits:
        if run_git(worktree, ['merge-base', '--is-ancestor', record['commit_sha'], observed]).returncode:
            raise RuntimeError(f'delegation #{record["id"]} commit is missing from final worker HEAD')
    with _connection(write=True) as db:
        current = db.execute("SELECT * FROM slots WHERE run_id=? AND task_id=? AND status='claimed'",
                             (run_id, task_id)).fetchone()
        if not current or current['number'] != slot['number'] or (
                current['lease_generation'] != slot['lease_generation']):
            raise PermissionError('task ownership changed during finish; stale result rejected')
        incomplete = db.execute("""SELECT COUNT(*) FROM delegations WHERE run_id=? AND recipient=?
                                   AND status IN ('offered','accepted')""", (run_id, task_id)).fetchone()[0]
        if incomplete:
            raise RuntimeError(f'{incomplete} delegated task(s) remain unfinished')
        if _run(db, run_id)['state'] != 'open':
            raise RuntimeError('run was closed before this task finished')
        # The SQLite lease is locked before writing the slot ref: a stale worker
        # cannot overwrite its replacement's Git result.
        ref = f'refs/codex-loop/collab/{run_id}/slot-{slot["number"]}'
        _git(worktree, 'update-ref', ref, observed)
        db.execute("""UPDATE slots SET status='done',commit_sha=?,completed_by=?,task_id=NULL,worktree=NULL
                      WHERE run_id=? AND number=? AND status='claimed'""",
                   (observed, task_id, run_id, current['number']))
        db.execute('UPDATE workers SET last_commit=? WHERE run_id=? AND task_id=?',
                   (observed, run_id, task_id))
        db.execute('INSERT OR IGNORE INTO worker_inputs(run_id,task_id,source_slot) VALUES(?,?,?)',
                   (run_id, task_id, current['number']))
        result = _elect(db, run_id, task_id)
        parent = _run(db, run_id)['worktree_parent']
    answer = {'run_id': run_id, 'task_id': task_id, 'commit_sha': observed, **result}
    if not result['integrate_now'] and run['planned'] and auto_claim:
        try:
            # Claim after the committed finish; no idle Chat or extra lifecycle.
            following = claim(run_id, task_id, worktree_parent=parent)
        except RuntimeError as exc:
            if 'no unclaimed slot' not in str(exc) and 'no ready task' not in str(exc):
                answer['next_task_blocked'] = str(exc)
                answer['action'] = 'finish is committed; inspect/recover claimed worktree then call collab claim'
        else:
            answer.update({'continue_now': True, 'next_task': following})
    return answer


def elect(run_id: str, task_id: str) -> dict[str, Any]:
    _task(task_id)
    with _connection(write=True) as db:
        if _slot(db, run_id, task_id)['status'] != 'done':
            raise RuntimeError('only completed workers can claim integration')
        return {'run_id': run_id, **_elect(db, run_id, task_id)}

def reclaim_integrator(run_id: str, task_id: str, *,
                       integration_worktree: str, force: bool = False,
                       reason: str = 'Expired integration lease') -> dict[str, Any]:
    """Transfer a stalled integrator without replaying any ambiguous Git operation."""
    task_id = _task(task_id)
    reason = _text(reason, 'takeover reason', 1000)
    with _connection() as db:
        run = _run(db, run_id)
        serial = db.execute('SELECT * FROM serial_tails WHERE run_id=?', (run_id,)).fetchone()
    tail_open = bool(serial and serial['status'] == 'active')
    if run['state'] != 'integrating' and not (run['state'] == 'integrated' and tail_open):
        raise RuntimeError('no active integration or serial continuation to reclaim')
    if run['integrator_task'] == task_id:
        return {'run_id': run_id, 'integrator': task_id,
                'integrator_generation': run['integrator_generation'], 'unchanged': True}
    if not force and (run['integrator_last_seen'] is None or
                      time.time() - run['integrator_last_seen'] <= LEASE_SECONDS):
        raise RuntimeError('integration lease has not expired; use explicit force')
    root = Path(integration_worktree).expanduser().resolve(strict=True)
    _verify_same_repo(root, run)
    if _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') != run['target_branch']:
        raise RuntimeError('integration target must still be checked out on the target branch')
    if _git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('integration target is dirty or has interrupted Git work; reconcile before takeover')
    if any(run_git(root, ['rev-parse','--verify','-q', marker]).returncode == 0
           for marker in ('CHERRY_PICK_HEAD','MERGE_HEAD','REBASE_HEAD')):
        raise RuntimeError('Git merge/rebase/cherry-pick still in progress; reconcile first')
    head = _git(root, 'rev-parse', '--verify', 'HEAD')
    if run_git(root, ['merge-base', '--is-ancestor',run['base_commit'],head]).returncode:
        raise RuntimeError('integration target no longer descends from the run baseline')
    if run['state'] == 'integrated' and run_git(root, [
            'merge-base','--is-ancestor',run['candidate_head'],head]).returncode:
        raise RuntimeError('serial continuation no longer descends from integrated candidate')
    with _connection(write=True) as db:
        current = _run(db, run_id)
        if (current['integrator_task'] != run['integrator_task'] or
                current['integrator_generation'] != run['integrator_generation'] or
                current['state'] != run['state']):
            raise PermissionError('integration ownership changed concurrently')
        if not force and time.time()-current['integrator_last_seen'] <= LEASE_SECONDS:
            raise PermissionError('integrator renewed its lease before takeover')
        db.execute("""UPDATE runs SET integrator_task=?,integrator_generation=integrator_generation+1,
                      integrator_last_seen=? WHERE id=?""", (task_id,time.time(),run_id))
        if tail_open:
            db.execute("""UPDATE serial_tails SET owner_task=? WHERE run_id=? AND status='active'
                          AND owner_task=?""", (task_id,run_id,run['integrator_task']))
        _notice(db, run_id, task_id, run['integrator_task'],
                f'Integrator ownership reclaimed by {task_id}: {reason}')
    return {'run_id': run_id, 'integrator': task_id,
            'previous_owner': run['integrator_task'],
            'integrator_generation': run['integrator_generation']+1,
            'integration_attempted': bool(run['integration_attempted']),
            'candidate_head': run['candidate_head'], 'serial_tail_active': tail_open,
            'reconcile_git_before_replay': bool(run['integration_attempted']),
            'old_owner_fenced': True}



def prepare_integration(run_id: str, task_id: str, *, integration_worktree: str) -> dict[str, Any]:
    task_id = _task(task_id)
    with _connection() as db:
        run = _run(db, run_id)
        if run['state'] != 'integrating' or run['integrator_task'] != task_id:
            raise PermissionError('only the elected integrator can merge this run')
        if run['integration_attempted']:
            raise RuntimeError('integration was already attempted; inspect and reconcile Git state before any retry')
        slots = _ordered_slots(db, run_id)
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
        batches.append((slot['number'], _own_commits(root, slot)))
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
        db.execute('UPDATE runs SET candidate_head=?,integrator_last_seen=? WHERE id=? AND integrator_task=? AND state=?',
                   (head,time.time(), run_id, task_id, 'integrating'))
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
        slots = _ordered_slots(db, run_id)
    expected = []
    for slot in slots:
        expected.extend(_own_commits(root, slot))
    merged_messages = _git(root, 'log', '--format=%B', f'{run["integration_start_head"]}..HEAD')
    missing = [sha for sha in expected if f'(cherry picked from commit {sha})' not in merged_messages]
    if missing:
        raise RuntimeError(f'worker commits not yet merged: {missing}; continue git cherry-pick -x before resolving')
    with _connection(write=True) as db:
        fresh = _run(db, run_id)
        if fresh['candidate_head'] or fresh['state'] != 'integrating' or fresh['integrator_task'] != task_id:
            raise RuntimeError('integration state already finalized or changed')
        db.execute('UPDATE runs SET candidate_head=?,integrator_last_seen=? WHERE id=?', (head,time.time(),run_id))
    return {'run_id': run_id, 'status': 'READY_FOR_TEST', 'candidate_head': head,
            'resolution_evidence': resolution_evidence, 'action': 'review merged diff and run tests before integration-complete'}


def integration_complete(run_id: str, task_id: str, *, integration_worktree: str, test_evidence: str) -> dict[str, Any]:
    """Finalize the merged run and atomically assign its prewritten serial tail."""
    task_id = _task(task_id)
    _text(test_evidence, 'test evidence', 5000)
    with _connection() as db:
        run = _run(db, run_id)
    if run['integrator_task'] != task_id or run['state'] not in ('integrating', 'integrated') or not run['candidate_head']:
        raise RuntimeError('no completed integration candidate owned by this task')
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
        if row['candidate_head'] != run['candidate_head'] or row['integrator_task'] != task_id:
            raise RuntimeError('integration ownership changed concurrently')
        if row['state'] == 'integrating':
            db.execute("UPDATE runs SET state='integrated',integrator_last_seen=? WHERE id=?", (time.time(),run_id))
            # No extra Slot/task_id: the active Integrator automatically owns the
            # full uninterrupted serial chain in the same SQLite transaction.
            db.execute("UPDATE serial_tails SET status='active',owner_task=? WHERE run_id=? AND status='pending'",
                       (task_id, run_id))
        elif row['state'] != 'integrated':
            raise RuntimeError('integration state changed concurrently')
        serial = db.execute('SELECT * FROM serial_tails WHERE run_id=?', (run_id,)).fetchone()
        if serial and serial['owner_task'] != task_id:
            raise RuntimeError('serial continuation owned by another task')
    return {'run_id': run_id, 'state': 'integrated', 'commit': run['candidate_head'],
            'test_evidence': test_evidence, 'pushed': False,
            'serial_tail': dict(serial) if serial else None,
            'continue_now': bool(serial and serial['status'] == 'active')}


def serial_complete(run_id: str, task_id: str, *, integration_worktree: str,
                    evidence: str) -> dict[str, Any]:
    """Close a serial chain after its plan-defined gates, without inventing Slots."""
    task_id = _task(task_id)
    evidence = _text(evidence, 'serial completion evidence', 5000)
    with _connection() as db:
        run = _run(db, run_id)
        serial = db.execute('SELECT * FROM serial_tails WHERE run_id=?', (run_id,)).fetchone()
    if run['state'] != 'integrated' or run['integrator_task'] != task_id:
        raise PermissionError('only the integrated run owner can complete its serial chain')
    if serial is None or serial['owner_task'] != task_id:
        raise RuntimeError('this task owns no post-integration serial chain')
    root = Path(integration_worktree).expanduser().resolve(strict=True)
    _verify_same_repo(root, run)
    if _git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD') != run['target_branch']:
        raise ValueError('serial continuation must finish on the target branch checkout')
    head = _git(root, 'rev-parse', '--verify', 'HEAD')
    if run_git(root, ['merge-base', '--is-ancestor', run['candidate_head'], head]).returncode:
        raise RuntimeError('serial continuation no longer descends from merged run')
    if _git(root, 'status', '--porcelain', '--untracked-files=all'):
        raise RuntimeError('serial continuation worktree is dirty')
    with _connection(write=True) as db:
        row = db.execute('SELECT * FROM serial_tails WHERE run_id=?', (run_id,)).fetchone()
        if row['owner_task'] != task_id:
            raise PermissionError('serial ownership changed')
        if row['status'] == 'complete':
            if row['final_head'] != head:
                raise RuntimeError('serial chain is already complete at a different commit')
        elif row['status'] == 'active':
            db.execute("UPDATE serial_tails SET status='complete',evidence=?,final_head=? WHERE run_id=? AND status='active'",
                       (evidence, head, run_id))
        else:
            raise RuntimeError('serial chain is not active')
        completed = db.execute('SELECT * FROM serial_tails WHERE run_id=?', (run_id,)).fetchone()
    return {'run_id': run_id, 'serial_tail': dict(completed), 'continue_now': False,
            'next': 'evaluate the frozen plan for its next prewritten parallel wave or final acceptance'}


def status(run_id: str) -> dict[str, Any]:
    with _connection() as db:
        run = _run(db, run_id)
        rows = db.execute('SELECT number,title,instructions,task_key,pool_id,depends_on,review_of,exclude_workers,status,COALESCE(task_id,completed_by) task_id,commit_sha,worktree,start_commit,lease_generation,last_seen,checkpoint_sha,checkpoint_note FROM slots WHERE run_id=? ORDER BY number', (run_id,)).fetchall()
        delegations = db.execute('SELECT * FROM delegations WHERE run_id=? ORDER BY id', (run_id,)).fetchall()
        serial = db.execute('SELECT * FROM serial_tails WHERE run_id=?', (run_id,)).fetchone()
        ready = {slot['number'] for slot in _ready_slots(db, run_id)}
        reclaims = [dict(row) for row in db.execute(
            'SELECT * FROM reclaims WHERE run_id=? ORDER BY id', (run_id,))]
    pools: dict[str, dict[str, int]] = {}
    for row in rows:
        counters = pools.setdefault(row['pool_id'], {'ready':0, 'waiting':0, 'claimed':0, 'done':0})
        state = ('ready' if row['number'] in ready else
                 'waiting' if row['status']=='available' else row['status'])
        counters[state] += 1
    now = time.time()
    assignments = []
    for row in rows:
        item = dict(row)
        seen = item.get('last_seen')
        item['seconds_since_activity'] = max(0, round(now - seen, 1)) if seen is not None else None
        item['lease_reclaimable'] = bool(item['status'] == 'claimed' and
                                         seen is not None and now - seen > LEASE_SECONDS)
        assignments.append(item)
    return {'run_id': run_id, 'state': run['state'], 'target_branch': run['target_branch'],
            'pools': pools,
            'goal_key': run['goal_key'], 'graph_revision': run['graph_revision'],
            'lease_seconds': LEASE_SECONDS, 'reclaims': reclaims,
            'integrator_task': run['integrator_task'],
            'integrator_generation': run['integrator_generation'],
            'integrator_last_seen': run['integrator_last_seen'],
            'candidate_head': run['candidate_head'], 'slots': assignments,
            'delegations': [dict(row) for row in delegations],
            'serial_tail': dict(serial) if serial else None}


def completion_obstacle(task_id: str) -> str | None:
    if not db_path().exists():
        return None
    with _connection() as db:
        rows = db.execute("""SELECT r.id,r.state,r.integrator_task,
                         COALESCE((SELECT status FROM slots WHERE run_id=r.id AND task_id=? AND status='claimed'), 'done') status
                         FROM runs r JOIN workers w ON w.run_id=r.id WHERE w.task_id=?""",
                         (task_id, task_id)).fetchall()
        unsettled = {r['id']: db.execute('''SELECT COUNT(*) FROM delegations WHERE run_id=? AND sender=?
                              AND status NOT IN ('completed','cancelled')''', (r['id'], task_id)).fetchone()[0]
                     for r in rows}
        serial_open = {r['id']: db.execute("SELECT COUNT(*) FROM serial_tails WHERE run_id=? AND owner_task=? AND status!='complete'",
                                           (r['id'], task_id)).fetchone()[0] for r in rows}
    for row in rows:
        if unsettled[row['id']]:
            return f'{unsettled[row["id"]]} delegated subtask(s) await completion or cancellation'
        if row['status'] != 'done':
            return 'local collaboration work has not been committed and finished'
        if row['state'] == 'integrating' and row['integrator_task'] == task_id:
            return 'elected local integrator has not completed merged validation'
        if serial_open[row['id']]:
            return 'post-integration serial chain has not completed its planned gates'
    return None
