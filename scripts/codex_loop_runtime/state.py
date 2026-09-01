from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .command_identity import identify_validation

from .workspace import repo_root

PROFILES = {
    "regular", "bug_fix", "feature", "refactor", "test_repair", "ci_repair",
    "code_review", "review_fix", "command_only", "investigation",
}
READ_ONLY_PROFILES = {"code_review", "investigation"}
NO_WRITE_PROFILES = READ_ONLY_PROFILES | {"command_only"}
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS criteria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ordinal INTEGER NOT NULL UNIQUE,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    evidence TEXT,
    evidence_generation INTEGER
);
CREATE TABLE IF NOT EXISTS baseline (
    path TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    mode INTEGER NOT NULL,
    protected INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mutations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation INTEGER NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    pre_sha256 TEXT,
    post_sha256 TEXT,
    protected INTEGER NOT NULL DEFAULT 0,
    override_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS validation_plans (
    plan_id TEXT PRIMARY KEY,
    generation INTEGER NOT NULL,
    command_json TEXT NOT NULL,
    cwd TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    consumed_at TEXT
);
CREATE TABLE IF NOT EXISTS validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation INTEGER NOT NULL,
    command_json TEXT NOT NULL,
    cwd TEXT NOT NULL DEFAULT '',
    exit_code INTEGER,
    passed INTEGER NOT NULL,
    workload_status TEXT NOT NULL DEFAULT 'unknown',
    process_status TEXT NOT NULL DEFAULT 'unknown',
    cleanup_status TEXT NOT NULL DEFAULT 'unknown',
    evidence_kind TEXT NOT NULL DEFAULT 'none',
    workload_evidence TEXT,
    process_evidence TEXT,
    cleanup_evidence TEXT,
    disposition TEXT NOT NULL DEFAULT 'blocking',
    disposition_evidence TEXT,
    source TEXT NOT NULL DEFAULT 'local_runtime',
    evidence TEXT,
    plan_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS external_actions (
    action_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    identity TEXT,
    action_class TEXT NOT NULL,
    state TEXT NOT NULL,
    details_json TEXT,
    failure_resolved INTEGER NOT NULL DEFAULT 0,
    failure_resolution_evidence TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation INTEGER NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS processes (
    handle TEXT PRIMARY KEY,
    pid INTEGER,
    argv_json TEXT NOT NULL,
    cwd TEXT NOT NULL,
    state TEXT NOT NULL,
    exit_code INTEGER,
    failure_message TEXT,
    failure_resolved INTEGER NOT NULL DEFAULT 0,
    failure_resolution_evidence TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS steers (
    steer_id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    evidence TEXT,
    acked_generation INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS release_receipts (
    release_id TEXT PRIMARY KEY,
    generation INTEGER NOT NULL,
    source_commit TEXT NOT NULL,
    source_tree TEXT NOT NULL,
    artifact_name TEXT NOT NULL,
    artifact_sha256 TEXT NOT NULL,
    evidence TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS isolations (
    isolation_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    parent_generation INTEGER NOT NULL,
    exit_generation INTEGER,
    requested_executor TEXT NOT NULL,
    actual_executor TEXT NOT NULL,
    requested_capabilities_json TEXT NOT NULL,
    actual_capabilities_json TEXT NOT NULL,
    missing_capabilities_json TEXT NOT NULL,
    mutation_policy TEXT NOT NULL,
    context_spec_json TEXT NOT NULL,
    result_json TEXT,
    checkpoint_id INTEGER,
    workspace_changed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_isolation ON isolations(status) WHERE status='active';
CREATE TABLE IF NOT EXISTS isolation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    isolation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    generation INTEGER NOT NULL,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def validate_task_id(task_id: str) -> str:
    value = str(task_id)
    if not TASK_ID_RE.fullmatch(value):
        raise ValueError("task_id must contain only ASCII letters, digits, underscore, or hyphen (1-64 chars)")
    return value


def _unicode_safe(value: str) -> str:
    return str(value).encode("utf-8", errors="replace").decode("utf-8")


def scrub_persisted_text(value: str | None, *, limit: int = 8192) -> str | None:
    if value is None:
        return None
    text = _unicode_safe(str(value))[:limit]
    text = re.sub(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}", r"\1 [redacted]", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|credential|authorization|cookie)\b(\s*[:=]\s*)([^\s,;]+)",
        lambda m: f"{m.group(1)}{m.group(2)}[redacted]",
        text,
    )
    return text


def scrub_persisted_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return scrub_persisted_text(value, limit=4096) or ""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:64]:
            clean_key = (scrub_persisted_text(str(key), limit=256) or "").strip()
            if clean_key:
                result[clean_key] = scrub_persisted_value(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [scrub_persisted_value(item, depth=depth + 1) for item in list(value)[:128]]
    return scrub_persisted_text(str(value), limit=4096) or ""


def _prune_isolation_events(db: sqlite3.Connection, *, keep_warnings: int = 64, keep_other: int = 448) -> None:
    # Preserve a bounded warning history even if a long isolation emits many steer/progress events.
    db.execute(
        "DELETE FROM isolation_events WHERE kind='warning' AND id NOT IN "
        "(SELECT id FROM isolation_events WHERE kind='warning' ORDER BY id DESC LIMIT ?)",
        (int(keep_warnings),),
    )
    db.execute(
        "DELETE FROM isolation_events WHERE kind<>'warning' AND id NOT IN "
        "(SELECT id FROM isolation_events WHERE kind<>'warning' ORDER BY id DESC LIMIT ?)",
        (int(keep_other),),
    )


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def _ensure_private_dir(path: Path) -> Path:
    parent = path.parent
    if not parent.exists() and parent != path:
        _ensure_private_dir(parent)
    try:
        path.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        pass
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise RuntimeError(f"private runtime path is not a real directory: {path}")
    if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
        raise PermissionError(f"private runtime directory is not owned by current user: {path}")
    os.chmod(path, 0o700)
    return path


def root_state_dir(cwd: str | Path) -> Path:
    root = repo_root(cwd)
    digest = hashlib.sha256(str(root).encode("utf-8", errors="surrogateescape")).hexdigest()[:16]
    base = Path(tempfile.gettempdir()) / "codex-loop"
    _ensure_private_dir(base)
    target = base / digest
    _ensure_private_dir(target)
    return target


def _active_path(cwd: str | Path) -> Path:
    return root_state_dir(cwd) / "active_task.json"


def set_active_task(cwd: str | Path, task_id: str) -> None:
    task_id = validate_task_id(task_id)
    path = _active_path(cwd)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"task_id": task_id}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _chmod(path, 0o600)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def active_task_id(cwd: str | Path) -> str | None:
    path = _active_path(cwd)
    try:
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise RuntimeError("active task metadata is not a regular file")
        if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
            raise PermissionError("active task metadata is not owned by current user")
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("task_id")
        return validate_task_id(str(value)) if value else None
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        raise RuntimeError("active task metadata is invalid JSON")


def new_task_id() -> str:
    return uuid.uuid4().hex


def _tasks_dir(cwd: str | Path) -> Path:
    tasks = root_state_dir(cwd) / "tasks"
    _ensure_private_dir(tasks)
    return tasks


def state_dir_for(cwd: str | Path, task_id: str | None = None, *, create: bool = True) -> Path:
    resolved = task_id or active_task_id(cwd)
    if not resolved:
        raise RuntimeError("no active codex-loop task; run bootstrap or pass --task-id")
    resolved = validate_task_id(resolved)
    tasks = _tasks_dir(cwd)
    path = tasks / resolved
    if create:
        _ensure_private_dir(path)
    else:
        try:
            st = path.lstat()
        except FileNotFoundError as exc:
            raise RuntimeError(f"unknown codex-loop task: {resolved}") from exc
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise RuntimeError(f"task state path is invalid: {path}")
        if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
            raise PermissionError(f"task state path is not owned by current user: {path}")
    return path


def state_path_for(cwd: str | Path, task_id: str | None = None, *, create: bool = True) -> Path:
    return state_dir_for(cwd, task_id, create=create) / "state.sqlite3"


def argv_record(argv: list[str]) -> dict[str, Any]:
    safe = [_unicode_safe(str(v)) for v in argv]
    encoded = json.dumps(safe, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    # Persist only a scrubbed executable label plus a digest of the full argv.
    # Arguments themselves may contain credentials and must never be written to SQLite.
    argv0 = scrub_persisted_text(safe[0], limit=1024) if safe else ""
    return {
        "argv0": argv0 or "",
        "argc": len(safe),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        _ensure_private_dir(self.path.parent)
        with self.connect() as db:
            db.executescript(SCHEMA)
            # New non-idempotent deduplication is enforced transactionally so legacy task
            # databases containing duplicate identities remain inspectable/cleanable.
            db.execute("DROP INDEX IF EXISTS external_non_idempotent_identity")
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(external_actions)")}
            if "failure_resolved" not in columns:
                db.execute("ALTER TABLE external_actions ADD COLUMN failure_resolved INTEGER NOT NULL DEFAULT 0")
            if "failure_resolution_evidence" not in columns:
                db.execute("ALTER TABLE external_actions ADD COLUMN failure_resolution_evidence TEXT")
            criteria_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(criteria)")}
            if "evidence_generation" not in criteria_columns:
                db.execute("ALTER TABLE criteria ADD COLUMN evidence_generation INTEGER")
            steer_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(steers)")}
            if "acked_generation" not in steer_columns:
                db.execute("ALTER TABLE steers ADD COLUMN acked_generation INTEGER")
            validation_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(validations)")}
            if "cwd" not in validation_columns:
                db.execute("ALTER TABLE validations ADD COLUMN cwd TEXT NOT NULL DEFAULT ''")
            if "plan_id" not in validation_columns:
                db.execute("ALTER TABLE validations ADD COLUMN plan_id TEXT")
            for name, ddl in (
                ("workload_status", "TEXT NOT NULL DEFAULT 'unknown'"),
                ("process_status", "TEXT NOT NULL DEFAULT 'unknown'"),
                ("cleanup_status", "TEXT NOT NULL DEFAULT 'unknown'"),
                ("evidence_kind", "TEXT NOT NULL DEFAULT 'none'"),
                ("workload_evidence", "TEXT"),
                ("process_evidence", "TEXT"),
                ("cleanup_evidence", "TEXT"),
            ):
                if name not in validation_columns:
                    db.execute(f"ALTER TABLE validations ADD COLUMN {name} {ddl}")
            mutation_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(mutations)")}
            if "override_reason" not in mutation_columns:
                db.execute("ALTER TABLE mutations ADD COLUMN override_reason TEXT")
            process_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(processes)")}
            if "failure_resolved" not in process_columns:
                db.execute("ALTER TABLE processes ADD COLUMN failure_resolved INTEGER NOT NULL DEFAULT 0")
            if "failure_resolution_evidence" not in process_columns:
                db.execute("ALTER TABLE processes ADD COLUMN failure_resolution_evidence TEXT")
        _chmod(self.path, 0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def set_meta(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True)
        with self.connect() as db:
            db.execute(
                "INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, encoded),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    @property
    def task_id(self) -> str:
        return str(self.get_meta("task_id", ""))

    def ensure_active(self) -> None:
        status = str(self.get_meta("task_status", "uninitialized"))
        if status != "active":
            raise RuntimeError(f"task is not active: {status}")

    def generation(self) -> int:
        return int(self.get_meta("generation", 0))

    def bump_generation(self) -> int:
        value = self.generation() + 1
        self.set_meta("generation", value)
        self.set_meta("changes_reviewed_generation", -1)
        return value

    def configure_task(
        self,
        task_id: str,
        objective: str,
        criteria: list[str],
        *,
        profile: str = "regular",
        requires_validation: bool = True,
        git_mutation_reason: str | None = None,
        git_mutation_scope: dict[str, bool] | None = None,
        no_validation_reason: str | None = None,
    ) -> None:
        task_id = validate_task_id(task_id)
        if profile not in PROFILES:
            raise ValueError(f"invalid task profile: {profile}")
        objective = scrub_persisted_text(objective) or ""
        if not objective.strip():
            raise ValueError("task objective must not be empty")
        clean_criteria = [scrub_persisted_text(x, limit=4096) or "" for x in criteria]
        clean_criteria = [x for x in clean_criteria if x.strip()]
        auto_criterion = not clean_criteria
        if auto_criterion:
            clean_criteria = [objective]
        reason = scrub_persisted_text(git_mutation_reason, limit=4096)
        scope = {"head": False, "branch": False, "index": False}
        if git_mutation_scope is not None:
            scope.update({k: bool(git_mutation_scope.get(k, False)) for k in scope})
        if any(scope.values()) and not (reason and reason.strip()):
            raise ValueError("Git mutation authorization requires a concise reason")
        no_validation_reason = scrub_persisted_text(no_validation_reason, limit=4096)
        if not requires_validation and not (no_validation_reason and no_validation_reason.strip()):
            raise ValueError("disabling validation requires a concise reason")
        with self.connect() as db:
            for table in ("criteria", "baseline", "mutations", "validation_plans", "validations", "external_actions", "checkpoints", "processes", "steers", "release_receipts", "isolation_events", "isolations"):
                db.execute(f"DELETE FROM {table}")
            db.execute("DELETE FROM metadata")
            db.executemany(
                "INSERT INTO criteria(ordinal,text,status) VALUES(?,?, 'pending')",
                [(i, text) for i, text in enumerate(clean_criteria)],
            )
        self.set_meta("task_id", task_id)
        self.set_meta("objective", objective)
        self.set_meta("profile", profile)
        self.set_meta("criteria_auto_generated", auto_criterion)
        self.set_meta("requires_validation", bool(requires_validation))
        self.set_meta("no_validation_reason", no_validation_reason)
        self.set_meta("allow_git_mutation", any(scope.values()))
        self.set_meta("git_mutation_reason", reason)
        self.set_meta("git_mutation_scope", scope)
        self.set_meta("generation", 0)
        self.set_meta("changes_reviewed_generation", -1)
        self.set_meta("plan_revision", 0)
        self.set_meta("task_status", "active")

    def cancel(self, reason: str | None = None) -> None:
        clean_reason = scrub_persisted_text(reason, limit=2048)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM metadata WHERE key='task_status'").fetchone()
            status = json.loads(row["value"]) if row is not None else "uninitialized"
            if str(status) != "active":
                raise RuntimeError(f"task is not active: {status}")
            generation_row = db.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
            generation = int(json.loads(generation_row["value"])) if generation_row is not None else 0
            active_iso = db.execute("SELECT isolation_id FROM isolations WHERE status='active' LIMIT 1").fetchone()
            if active_iso is not None:
                isolation_id = str(active_iso["isolation_id"])
                db.execute(
                    "UPDATE isolations SET status='aborted',exit_generation=?,completed_at=CURRENT_TIMESTAMP WHERE isolation_id=? AND status='active'",
                    (generation, isolation_id),
                )
                db.execute(
                    "INSERT INTO isolation_events(isolation_id,kind,generation,details_json) VALUES(?,?,?,?)",
                    (isolation_id, "aborted", generation, json.dumps({"reason": "parent_task_cancelled"}, ensure_ascii=True)),
                )
                _prune_isolation_events(db)

            # A merely planned action has not crossed the dispatch boundary, so cancellation can
            # close it deterministically. Dispatched/unknown actions remain unresolved until the
            # host observes a real terminal outcome.
            cancellation_details = json.dumps({"observed": "cancelled before dispatch"}, ensure_ascii=True)
            db.execute(
                "UPDATE external_actions SET state='cancelled_before_dispatch',details_json=?,failure_resolved=1,"
                "failure_resolution_evidence='cancelled before dispatch',updated_at=CURRENT_TIMESTAMP "
                "WHERE state='planned'",
                (cancellation_details,),
            )
            db.execute(
                "INSERT INTO metadata(key,value) VALUES('task_status',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps("cancelled"),),
            )
            db.execute(
                "INSERT INTO metadata(key,value) VALUES('cancel_reason',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(clean_reason),),
            )

    def criteria(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT ordinal,text,status,evidence,evidence_generation FROM criteria ORDER BY ordinal")]

    def set_criterion(self, ordinal: int, status: str, evidence: str | None = None) -> None:
        if status not in {"pending", "pass", "fail", "blocked"}:
            raise ValueError("invalid criterion status")
        clean = scrub_persisted_text(evidence, limit=4096)
        if status == "pass" and not (clean and clean.strip()):
            raise ValueError("passing an acceptance criterion requires concise observable evidence")
        evidence_generation = self.generation() if status == "pass" else None
        with self.connect() as db:
            cur = db.execute("UPDATE criteria SET status=?,evidence=?,evidence_generation=? WHERE ordinal=?", (status, clean, evidence_generation, int(ordinal)))
            if cur.rowcount != 1:
                raise ValueError(f"criterion {ordinal} does not exist")

    def replace_baseline(self, entries: list[tuple[str, str, int, int, bool]]) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM baseline")
            db.executemany(
                "INSERT INTO baseline(path,sha256,size,mode,protected) VALUES(?,?,?,?,?)",
                [(p, h, int(s), int(mode), int(protected)) for p, h, s, mode, protected in entries],
            )

    def baseline(self) -> dict[str, dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT path,sha256,size,mode,protected FROM baseline").fetchall()
        return {
            str(row["path"]): {
                "sha256": row["sha256"], "size": int(row["size"]), "mode": int(row["mode"]),
                "protected": bool(row["protected"]),
            }
            for row in rows
        }

    def protected_paths(self) -> set[str]:
        with self.connect() as db:
            rows = db.execute("SELECT path FROM baseline WHERE protected=1").fetchall()
        result = {str(row["path"]) for row in rows}
        result.update(str(x) for x in self.get_meta("protected_paths", []))
        return result

    def record_mutation(
        self, path: str, kind: str, pre_hash: str | None, post_hash: str | None, *,
        protected: bool = False, override_reason: str | None = None,
    ) -> int:
        generation = self.bump_generation()
        clean_reason = scrub_persisted_text(override_reason, limit=4096)
        with self.connect() as db:
            db.execute(
                "INSERT INTO mutations(generation,path,kind,pre_sha256,post_sha256,protected,override_reason) VALUES(?,?,?,?,?,?,?)",
                (generation, _unicode_safe(path), kind, pre_hash, post_hash, int(protected), clean_reason),
            )
        return generation

    def mutation_paths(self) -> set[str]:
        with self.connect() as db:
            rows = db.execute("SELECT DISTINCT path FROM mutations WHERE path <> '*' ").fetchall()
        return {str(row["path"]) for row in rows}

    def mutations(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM mutations ORDER BY id")]

    def _validation_record(self, argv: list[str], cwd: str | Path) -> tuple[str, dict[str, Any]]:
        cwd_norm = str(Path(cwd).resolve())
        identity = identify_validation(argv, cwd_norm)
        rec = argv_record(argv)
        rec["cwd"] = identity.cwd
        rec["opaque"] = bool(identity.opaque)
        rec["sha256"] = identity.digest
        return cwd_norm, rec

    def create_validation_plan(self, generation: int, argv: list[str], *, cwd: str | Path) -> dict[str, Any]:
        self.ensure_active()
        generation = int(generation)
        if generation != self.generation():
            raise RuntimeError(f"cannot plan validation for stale generation {generation}; current generation is {self.generation()}")
        cwd_norm, rec = self._validation_record(argv, cwd)
        plan_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute(
                "INSERT INTO validation_plans(plan_id,generation,command_json,cwd,consumed) VALUES(?,?,?,?,0)",
                (plan_id, generation, json.dumps(rec, sort_keys=True), cwd_norm),
            )
        return {"plan_id": plan_id, "generation": generation, "cwd": cwd_norm, "identity": rec["sha256"]}

    def record_validation(
        self, generation: int, argv: list[str], exit_code: int, *, cwd: str | Path,
        source: str = "local_runtime", evidence: str | None = None,
    ) -> int:
        from .execution_supervision import legacy_observation
        if source != "local_runtime":
            raise ValueError("host-observed validation must consume a validation plan via record_host_validation")
        clean_evidence = scrub_persisted_text(evidence, limit=4096) or f"local runtime observed exit code {int(exit_code)}"
        observation = legacy_observation(int(exit_code), clean_evidence)
        cwd_norm, rec = self._validation_record(argv, cwd)
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO validations(generation,command_json,cwd,exit_code,passed,source,evidence,plan_id,workload_status,process_status,cleanup_status,evidence_kind,workload_evidence,process_evidence,cleanup_evidence) VALUES(?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?)",
                (int(generation), json.dumps(rec, sort_keys=True), cwd_norm, int(exit_code), int(observation.workload_status == 'passed'), source, clean_evidence, str(observation.workload_status), str(observation.process_status), str(observation.cleanup_status), str(observation.evidence_kind), clean_evidence, observation.process_evidence, observation.cleanup_evidence),
            )
            return int(cur.lastrowid)

    def record_host_validation(
        self, plan_id: str, generation: int, argv: list[str], exit_code: int | None, *, cwd: str | Path, evidence: str,
        workload_status: str | None = None, process_status: str | None = None, cleanup_status: str | None = None,
        evidence_kind: str | None = None, workload_evidence: str | None = None, process_evidence: str | None = None, cleanup_evidence: str | None = None,
    ) -> int:
        from .execution_supervision import CleanupStatus, EvidenceKind, ExecutionObservation, ProcessStatus, WorkloadStatus, legacy_observation
        self.ensure_active()
        clean_evidence = scrub_persisted_text(evidence, limit=4096)
        if not (clean_evidence and clean_evidence.strip()): raise ValueError("host-observed validation requires concise observable evidence")
        if workload_status is None and process_status is None and cleanup_status is None and evidence_kind is None:
            if exit_code is None: raise ValueError("legacy validation recording requires --exit-code")
            obs = legacy_observation(int(exit_code), clean_evidence)
        else:
            obs = ExecutionObservation(
                workload_status=WorkloadStatus(workload_status or 'unknown'),
                process_status=ProcessStatus(process_status or 'unknown'),
                cleanup_status=CleanupStatus(cleanup_status or 'unknown'),
                evidence_kind=EvidenceKind(evidence_kind or 'none'),
                workload_evidence=scrub_persisted_text(workload_evidence, limit=4096),
                process_evidence=scrub_persisted_text(process_evidence, limit=4096),
                cleanup_evidence=scrub_persisted_text(cleanup_evidence, limit=4096),
                exit_code=None if exit_code is None else int(exit_code),
            ).validate()
        plan_id = validate_task_id(plan_id); generation=int(generation); cwd_norm, rec=self._validation_record(argv,cwd); encoded=json.dumps(rec,sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT generation,command_json,cwd,consumed FROM validation_plans WHERE plan_id=?",(plan_id,)).fetchone()
            if row is None: raise ValueError("host validation plan does not exist")
            if bool(row["consumed"]): raise ValueError("host validation plan has already been consumed")
            if generation != self.generation() or generation != int(row["generation"]): raise RuntimeError(f"host validation is stale: planned generation {int(row['generation'])}, observed generation {generation}, current generation {self.generation()}")
            if cwd_norm != str(row["cwd"]): raise ValueError("host validation cwd does not match the planned cwd")
            if encoded != str(row["command_json"]): raise ValueError("host validation command identity does not match the planned command")
            cur=db.execute(
                "INSERT INTO validations(generation,command_json,cwd,exit_code,passed,source,evidence,plan_id,workload_status,process_status,cleanup_status,evidence_kind,workload_evidence,process_evidence,cleanup_evidence) VALUES(?,?,?,?,?,'host_observed',?,?,?,?,?,?,?,?,?)",
                (generation,encoded,cwd_norm,obs.exit_code,int(obs.workload_status == 'passed'),clean_evidence,plan_id,str(obs.workload_status),str(obs.process_status),str(obs.cleanup_status),str(obs.evidence_kind),obs.workload_evidence,obs.process_evidence,obs.cleanup_evidence),
            )
            db.execute("UPDATE validation_plans SET consumed=1,consumed_at=CURRENT_TIMESTAMP WHERE plan_id=? AND consumed=0",(plan_id,))
            return int(cur.lastrowid)

    def latest_validation(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM validations ORDER BY id DESC LIMIT 1").fetchone()
        return None if row is None else dict(row)

    def resolve_validation(self, validation_id: int, disposition: str, evidence: str) -> None:
        if disposition != "baseline_unrelated":
            raise ValueError("only baseline_unrelated validation disposition is supported")
        clean = scrub_persisted_text(evidence, limit=4096)
        if not (clean and clean.strip()):
            raise ValueError("baseline_unrelated validation disposition requires observable evidence")
        with self.connect() as db:
            row = db.execute("SELECT passed,generation FROM validations WHERE id=?", (int(validation_id),)).fetchone()
            if row is None:
                raise ValueError(f"validation {validation_id} does not exist")
            if bool(row["passed"]):
                raise ValueError("passing validation cannot be marked baseline_unrelated")
            if int(row["generation"]) != 0:
                raise ValueError("baseline_unrelated requires a failure actually observed at baseline generation 0")
            db.execute(
                "UPDATE validations SET disposition=?,disposition_evidence=? WHERE id=?",
                (disposition, clean, int(validation_id)),
            )

    def validation_state_for_generation(self, generation: int) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM validations WHERE generation=? ORDER BY id", (int(generation),)).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            try:
                rec = json.loads(item["command_json"])
                identity = str(rec.get("sha256") or item["command_json"]) if isinstance(rec, dict) else item["command_json"]
            except json.JSONDecodeError:
                identity = item["command_json"]
            latest[identity] = item
        current = list(latest.values())
        legacy_identity = [x for x in current if not str(x.get("cwd") or "").strip()]
        eligible = [x for x in current if str(x.get("cwd") or "").strip()]
        blocking = [x for x in eligible if x.get("disposition", "blocking") != "baseline_unrelated"]
        nonblocking = [x for x in eligible if x.get("disposition") == "baseline_unrelated"]
        return {
            "commands": current,
            "passed_count": sum(1 for x in blocking if bool(x["passed"])),
            "failed_count": sum(1 for x in blocking if not bool(x["passed"])),
            "nonblocking_count": len(nonblocking),
            "nonblocking": nonblocking,
            "legacy_identity_count": len(legacy_identity),
            "legacy_identity": legacy_identity,
        }

    def record_release_receipt(
        self,
        *,
        release_id: str,
        generation: int,
        source_commit: str,
        source_tree: str,
        artifact_name: str,
        artifact_sha256: str,
        evidence: str,
    ) -> dict[str, Any]:
        release_id = validate_task_id(release_id)
        clean_name = (scrub_persisted_text(artifact_name, limit=512) or "").strip()
        clean_evidence = (scrub_persisted_text(evidence, limit=4096) or "").strip()
        if not clean_name or not clean_evidence:
            raise ValueError("release receipt requires artifact name and evidence")
        with self.connect() as db:
            db.execute(
                "INSERT INTO release_receipts(release_id,generation,source_commit,source_tree,artifact_name,artifact_sha256,evidence) VALUES(?,?,?,?,?,?,?)",
                (release_id, int(generation), source_commit, source_tree, clean_name, artifact_sha256, clean_evidence),
            )
            row = db.execute("SELECT * FROM release_receipts WHERE release_id=?", (release_id,)).fetchone()
        assert row is not None
        return dict(row)

    def release_receipt(self, release_id: str) -> dict[str, Any] | None:
        release_id = validate_task_id(release_id)
        with self.connect() as db:
            row = db.execute("SELECT * FROM release_receipts WHERE release_id=?", (release_id,)).fetchone()
        return dict(row) if row is not None else None

    def latest_release_receipt(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM release_receipts ORDER BY created_at DESC, release_id DESC LIMIT 1").fetchone()
        return dict(row) if row is not None else None

    def release_receipts(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM release_receipts ORDER BY created_at,release_id")]

    def record_external(
        self,
        kind: str,
        state: str,
        identity: str | None = None,
        details: Any = None,
        *,
        action_class: str = "recheckable",
        action_id: str | None = None,
    ) -> str:
        if state not in {"planned", "dispatched", "terminal_success", "terminal_failure", "outcome_unknown", "cancelled_before_dispatch"}:
            raise ValueError("invalid external action state")
        if action_class not in {"read_only", "recheckable", "external_non_idempotent"}:
            raise ValueError("invalid external action class")
        provided_action_id = action_id is not None
        action_id = validate_task_id(action_id) if provided_action_id else uuid.uuid4().hex
        clean_kind = (scrub_persisted_text(kind, limit=256) or "").strip()
        clean_identity_input = (scrub_persisted_text(identity, limit=2048) or "").strip()
        if not clean_kind:
            raise ValueError("external action kind must not be empty")
        if action_class == "external_non_idempotent" and not clean_identity_input:
            raise ValueError("non-idempotent external action requires a stable identity before dispatch")
        if state in {"terminal_success", "terminal_failure", "outcome_unknown"} and details is None:
            raise ValueError(f"external action state {state} requires concise observable details")

        def scrub(value: Any) -> Any:
            if isinstance(value, dict):
                out: dict[str, Any] = {}
                for key, item in list(value.items())[:100]:
                    key_s = _unicode_safe(str(key))[:256]
                    if re.search(r"(key|secret|token|password|credential|authorization|cookie)", key_s, re.I):
                        out[key_s] = "[redacted]"
                    else:
                        out[key_s] = scrub(item)
                return out
            if isinstance(value, list):
                return [scrub(x) for x in value[:100]]
            if isinstance(value, str):
                return scrub_persisted_text(value, limit=4096) or ""
            if value is None or isinstance(value, (bool, int, float)):
                return value
            return scrub_persisted_text(str(value), limit=4096)

        clean_identity = clean_identity_input or None
        clean_details = scrub(details) if details is not None else None
        details_json = json.dumps(clean_details, ensure_ascii=True) if clean_details is not None else None
        if details_json is not None and len(details_json.encode("utf-8")) > 16 * 1024:
            raise ValueError("external action details exceed 16 KiB; store concise evidence instead of raw logs")
        allowed = {
            "planned": {"planned", "dispatched", "cancelled_before_dispatch"},
            "dispatched": {"dispatched", "terminal_success", "terminal_failure", "outcome_unknown"},
            "outcome_unknown": {"outcome_unknown", "terminal_success", "terminal_failure"},
            "terminal_success": {"terminal_success"},
            "terminal_failure": {"terminal_failure"},
            "cancelled_before_dispatch": {"cancelled_before_dispatch"},
        }
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT kind,identity,action_class,state FROM external_actions WHERE action_id=?", (action_id,)
            ).fetchone()
            if action_class == "external_non_idempotent" and clean_identity is not None:
                matches = db.execute(
                    "SELECT action_id,kind,identity,action_class,state FROM external_actions WHERE kind=? AND identity=? AND action_class='external_non_idempotent' ORDER BY created_at,action_id",
                    (clean_kind, clean_identity),
                ).fetchall()
                if len(matches) > 1:
                    raise RuntimeError(
                        "legacy task state contains multiple non-idempotent actions with the same stable identity; "
                        "do not retry the external action, inspect the real external state and retire this task"
                    )
                same = matches[0] if matches else None
                if same is not None and str(same["action_id"]) != action_id:
                    if provided_action_id:
                        raise ValueError("non-idempotent external identity already belongs to another action")
                    if state == "planned":
                        return str(same["action_id"])
                    raise ValueError(f"non-idempotent external identity already exists as {same['action_id']}; advance it with --action-id")
            status_row = db.execute("SELECT value FROM metadata WHERE key='task_status'").fetchone()
            task_status = str(json.loads(status_row["value"]) if status_row is not None else "uninitialized")
            if task_status != "active":
                if existing is None:
                    raise RuntimeError(f"cannot create external action while task is {task_status}")
                previous = str(existing["state"])
                if previous not in {"dispatched", "outcome_unknown", "terminal_success", "terminal_failure"}:
                    raise RuntimeError(
                        f"cannot advance external action from {previous} while task is {task_status}; only already-dispatched outcomes may be reconciled"
                    )
                if state in {"planned", "dispatched"}:
                    raise RuntimeError(f"cannot dispatch new external work while task is {task_status}")
            if existing is None:
                if action_class == "external_non_idempotent" and state not in {"planned", "dispatched"}:
                    raise ValueError("a non-idempotent external action must cross planned/dispatched before a terminal outcome")
                db.execute(
                    "INSERT INTO external_actions(action_id,kind,identity,action_class,state,details_json) VALUES(?,?,?,?,?,?)",
                    (action_id, clean_kind, clean_identity, action_class, state, details_json),
                )
            else:
                if existing["kind"] != clean_kind or existing["action_class"] != action_class:
                    raise ValueError("external action kind/action_class are immutable")
                if existing["identity"] is not None and clean_identity is not None and existing["identity"] != clean_identity:
                    raise ValueError("external action identity cannot change")
                if state not in allowed[str(existing["state"])]:
                    raise ValueError(f"invalid external action transition: {existing['state']} -> {state}")
                db.execute(
                    "UPDATE external_actions SET state=?,details_json=?,identity=COALESCE(?,identity),updated_at=CURRENT_TIMESTAMP WHERE action_id=?",
                    (state, details_json, clean_identity, action_id),
                )
        return action_id

    def external_action(self, action_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM external_actions WHERE action_id=?", (action_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown external action: {action_id}")
        return dict(row)

    def external_actions(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM external_actions ORDER BY created_at,action_id")]

    def unresolved_external_count(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) AS n FROM external_actions WHERE state IN ('planned','dispatched','outcome_unknown')").fetchone()
        return int(row["n"])

    def unresolved_external_failure_count(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) AS n FROM external_actions WHERE state='terminal_failure' AND failure_resolved=0").fetchone()
        return int(row["n"])

    def ambiguous_non_idempotent_identity_count(self) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM ("
                "SELECT kind,identity FROM external_actions "
                "WHERE action_class='external_non_idempotent' AND identity IS NOT NULL "
                "GROUP BY kind,identity HAVING COUNT(*)>1)"
            ).fetchone()
        return int(row["n"])

    def resolve_external_failure(self, action_id: str, evidence: str) -> None:
        clean = scrub_persisted_text(evidence, limit=4096) or ""
        if not clean.strip():
            raise ValueError("resolving an external failure requires concise observable evidence")
        with self.connect() as db:
            row = db.execute("SELECT state FROM external_actions WHERE action_id=?", (action_id,)).fetchone()
            if row is None:
                raise ValueError(f"unknown external action: {action_id}")
            if row["state"] != "terminal_failure":
                raise ValueError("only terminal_failure external actions can be resolved")
            db.execute(
                "UPDATE external_actions SET failure_resolved=1,failure_resolution_evidence=?,updated_at=CURRENT_TIMESTAMP WHERE action_id=?",
                (clean, action_id),
            )

    def authorize_git_mutation(self, reason: str, *, head: bool = False, branch: bool = False, index: bool = False) -> None:
        self.ensure_active()
        clean = (scrub_persisted_text(reason, limit=4096) or "").strip()
        if not clean:
            raise ValueError("Git mutation authorization requires a concise reason")
        scope = {"head": bool(head), "branch": bool(branch), "index": bool(index)}
        if not any(scope.values()):
            raise ValueError("Git mutation authorization requires at least one explicit scope: head, branch, or index")
        self.set_meta("allow_git_mutation", True)
        self.set_meta("git_mutation_reason", clean)
        self.set_meta("git_mutation_scope", scope)

    def mark_reviewed(self) -> None:
        self.set_meta("changes_reviewed_generation", self.generation())

    def record_checkpoint(self, summary: Any) -> int:
        encoded = json.dumps(summary, ensure_ascii=True, sort_keys=True)
        if len(encoded.encode("utf-8")) > 256 * 1024:
            raise ValueError("checkpoint is too large")
        with self.connect() as db:
            cur = db.execute("INSERT INTO checkpoints(generation,summary_json) VALUES(?,?)", (self.generation(), encoded))
            return int(cur.lastrowid)

    def latest_checkpoint(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT id,generation,summary_json,created_at FROM checkpoints ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return {"id": int(row["id"]), "generation": int(row["generation"]), "summary": json.loads(row["summary_json"]), "created_at": row["created_at"]}

    @staticmethod
    def _decode_isolation_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for source, target in (
            ("requested_capabilities_json", "requested_capabilities"),
            ("actual_capabilities_json", "actual_capabilities"),
            ("missing_capabilities_json", "missing_capabilities"),
            ("context_spec_json", "context_spec"),
            ("result_json", "result"),
        ):
            raw = item.pop(source, None)
            item[target] = None if raw is None else json.loads(raw)
        item["workspace_changed"] = bool(item.get("workspace_changed", 0))
        return item

    def active_isolation(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM isolations WHERE status='active' LIMIT 1").fetchone()
        return self._decode_isolation_row(row)

    def isolation(self, isolation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM isolations WHERE isolation_id=?", (str(isolation_id),)).fetchone()
        return self._decode_isolation_row(row)

    def isolation_history(self, *, limit: int = 32) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 128))
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM isolations ORDER BY created_at DESC, isolation_id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._decode_isolation_row(row) for row in rows if row is not None]

    def create_isolation(
        self,
        *,
        isolation_id: str,
        role: str,
        objective: str,
        parent_generation: int,
        requested_executor: str,
        actual_executor: str,
        requested_capabilities: dict[str, bool],
        actual_capabilities: dict[str, bool],
        missing_capabilities: list[str],
        mutation_policy: str,
        context_spec: dict[str, Any],
        checkpoint_id: int | None,
    ) -> dict[str, Any]:
        self.ensure_active()
        fields = {
            "role": (scrub_persisted_text(role, limit=256) or "").strip(),
            "objective": (scrub_persisted_text(objective, limit=8192) or "").strip(),
            "requested_executor": (scrub_persisted_text(requested_executor, limit=256) or "").strip(),
            "actual_executor": (scrub_persisted_text(actual_executor, limit=256) or "").strip(),
            "mutation_policy": (scrub_persisted_text(mutation_policy, limit=256) or "").strip(),
        }
        if not all(fields.values()):
            raise ValueError("isolation role/objective/executor/mutation policy must not be empty")
        safe_context_spec = scrub_persisted_value(context_spec)
        context_encoded = json.dumps(safe_context_spec, ensure_ascii=True, sort_keys=True)
        if len(context_encoded.encode("utf-8")) > 256 * 1024:
            raise ValueError("isolation context projection is too large")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM isolations WHERE status='active' LIMIT 1").fetchone() is not None:
                raise RuntimeError("an isolated task is already active; nested isolation is not supported")
            db.execute(
                "INSERT INTO isolations(isolation_id,role,objective,status,parent_generation,requested_executor,actual_executor,"
                "requested_capabilities_json,actual_capabilities_json,missing_capabilities_json,mutation_policy,context_spec_json,checkpoint_id) "
                "VALUES(?,?,?,'active',?,?,?,?,?,?,?,?,?)",
                (
                    str(isolation_id), fields["role"], fields["objective"], int(parent_generation),
                    fields["requested_executor"], fields["actual_executor"],
                    json.dumps(requested_capabilities, ensure_ascii=True, sort_keys=True),
                    json.dumps(actual_capabilities, ensure_ascii=True, sort_keys=True),
                    json.dumps(list(missing_capabilities), ensure_ascii=True),
                    fields["mutation_policy"], context_encoded, checkpoint_id,
                ),
            )
            db.execute(
                "INSERT INTO isolation_events(isolation_id,kind,generation,details_json) VALUES(?,?,?,?)",
                (str(isolation_id), "entered", int(parent_generation), json.dumps({"role": fields["role"]}, ensure_ascii=True)),
            )
            _prune_isolation_events(db)
        created = self.isolation(isolation_id)
        if created is None:
            raise RuntimeError("failed to read isolation after creation")
        return created

    def record_isolation_event(self, isolation_id: str, kind: str, details: dict[str, Any] | None = None) -> int:
        clean_kind = (scrub_persisted_text(kind, limit=128) or "").strip()
        if not clean_kind:
            raise ValueError("isolation event kind must not be empty")
        safe_details = None if details is None else scrub_persisted_value(details)
        encoded = None if safe_details is None else json.dumps(safe_details, ensure_ascii=True, sort_keys=True)
        if encoded is not None and len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("isolation event details are too large")
        with self.connect() as db:
            if db.execute("SELECT 1 FROM isolations WHERE isolation_id=?", (str(isolation_id),)).fetchone() is None:
                raise ValueError(f"unknown isolation: {isolation_id}")
            generation_row = db.execute("SELECT value FROM metadata WHERE key='generation'").fetchone()
            generation = int(json.loads(generation_row["value"])) if generation_row is not None else 0
            cur = db.execute(
                "INSERT INTO isolation_events(isolation_id,kind,generation,details_json) VALUES(?,?,?,?)",
                (str(isolation_id), clean_kind, generation, encoded),
            )
            event_id = int(cur.lastrowid)
            _prune_isolation_events(db)
            return event_id

    def isolation_events(self, isolation_id: str | None = None, *, kind: str | None = None, limit: int = 64) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 256))
        clauses: list[str] = []
        params: list[Any] = []
        if isolation_id is not None:
            clauses.append("isolation_id=?")
            params.append(str(isolation_id))
        if kind is not None:
            clauses.append("kind=?")
            params.append(str(kind))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT id,isolation_id,kind,generation,details_json,created_at FROM isolation_events{where} ORDER BY id DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("details_json", None)
            item["details"] = None if raw is None else json.loads(raw)
            result.append(item)
        return result

    def isolation_warnings(self, isolation_id: str | None = None, *, limit: int = 32) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for event in reversed(self.isolation_events(isolation_id, kind="warning", limit=limit)):
            details = event.get("details") or {}
            if isinstance(details, dict):
                result.append(details)
        return result

    def finish_isolation(
        self,
        isolation_id: str,
        *,
        result: dict[str, Any],
        exit_generation: int,
        workspace_changed: bool,
    ) -> dict[str, Any]:
        safe_result = scrub_persisted_value(result)
        if not isinstance(safe_result, dict):
            raise ValueError("isolated result must be an object")
        encoded = json.dumps(safe_result, ensure_ascii=True, sort_keys=True)
        if len(encoded.encode("utf-8")) > 64 * 1024:
            raise ValueError("isolated result is too large")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM isolations WHERE isolation_id=?", (str(isolation_id),)).fetchone()
            if row is None:
                raise ValueError(f"unknown isolation: {isolation_id}")
            if str(row["status"]) != "active":
                raise RuntimeError(f"isolation is not active: {isolation_id}")
            db.execute(
                "UPDATE isolations SET status='finished',exit_generation=?,result_json=?,workspace_changed=?,completed_at=CURRENT_TIMESTAMP WHERE isolation_id=?",
                (int(exit_generation), encoded, int(bool(workspace_changed)), str(isolation_id)),
            )
            db.execute(
                "INSERT INTO isolation_events(isolation_id,kind,generation,details_json) VALUES(?,?,?,?)",
                (str(isolation_id), "finished", int(exit_generation), json.dumps({"workspace_changed": bool(workspace_changed)}, ensure_ascii=True)),
            )
            _prune_isolation_events(db)
        item = self.isolation(isolation_id)
        if item is None:
            raise RuntimeError("failed to read finished isolation")
        return item

    def abort_isolation(self, isolation_id: str, *, reason: str, exit_generation: int | None = None) -> dict[str, Any]:
        clean = (scrub_persisted_text(reason, limit=4096) or "").strip()
        if not clean:
            raise ValueError("aborting an isolated task requires a reason")
        generation = self.generation() if exit_generation is None else int(exit_generation)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM isolations WHERE isolation_id=?", (str(isolation_id),)).fetchone()
            if row is None:
                raise ValueError(f"unknown isolation: {isolation_id}")
            if str(row["status"]) != "active":
                raise RuntimeError(f"isolation is not active: {isolation_id}")
            db.execute(
                "UPDATE isolations SET status='aborted',exit_generation=?,completed_at=CURRENT_TIMESTAMP WHERE isolation_id=?",
                (generation, str(isolation_id)),
            )
            db.execute(
                "INSERT INTO isolation_events(isolation_id,kind,generation,details_json) VALUES(?,?,?,?)",
                (str(isolation_id), "aborted", generation, json.dumps({"reason": clean}, ensure_ascii=True)),
            )
            _prune_isolation_events(db)
        item = self.isolation(isolation_id)
        if item is None:
            raise RuntimeError("failed to read aborted isolation")
        return item

    def record_steer(self, text: str) -> str:
        clean = scrub_persisted_text(text, limit=4096) or ""
        if not clean.strip():
            raise ValueError("steer text must not be empty")
        steer_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO steers(steer_id,text,state) VALUES(?,?, 'pending')", (steer_id, clean))
        self.set_meta("plan_revision", int(self.get_meta("plan_revision", 0)) + 1)
        return steer_id

    def pending_steers(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT steer_id,text,state,evidence,created_at FROM steers WHERE state='pending' ORDER BY created_at")]

    def integrated_steers(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT steer_id,text,state,evidence,acked_generation,created_at,updated_at FROM steers WHERE state='acked' ORDER BY updated_at")]

    def stale_steers(self) -> list[dict[str, Any]]:
        generation = self.generation()
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT steer_id,text,state,evidence,acked_generation,created_at,updated_at FROM steers WHERE state='acked' AND COALESCE(acked_generation,-1)<>? ORDER BY updated_at",
                (generation,),
            )]

    def ack_steer(self, steer_id: str, evidence: str) -> None:
        clean = scrub_persisted_text(evidence, limit=4096) or ""
        if not clean.strip():
            raise ValueError("acknowledging a steer requires concise evidence of integration")
        generation = self.generation()
        with self.connect() as db:
            row = db.execute("SELECT state,acked_generation FROM steers WHERE steer_id=?", (steer_id,)).fetchone()
            if row is None:
                raise ValueError(f"unknown steer id: {steer_id}")
            if row["state"] == "acked" and int(row["acked_generation"] if row["acked_generation"] is not None else -1) == generation:
                raise ValueError(f"steer is already acknowledged at generation {generation}: {steer_id}")
            if row["state"] not in {"pending", "acked"}:
                raise ValueError(f"steer cannot be acknowledged from state {row['state']}: {steer_id}")
            db.execute(
                "UPDATE steers SET state='acked',evidence=?,acked_generation=?,updated_at=CURRENT_TIMESTAMP WHERE steer_id=?",
                (clean, generation, steer_id),
            )


    def set_freshness_waiver(self, opaque_paths: list[str], reason: str) -> dict[str, Any]:
        self.ensure_active()
        clean_reason = scrub_persisted_text(reason, limit=4096) or ""
        if not clean_reason.strip():
            raise ValueError("freshness waiver requires a concise reason")
        normalized = sorted({str(x) for x in opaque_paths if str(x)})
        if not normalized:
            raise ValueError("freshness waiver requires at least one opaque path")
        waiver = {"generation": self.generation(), "opaque_paths": normalized, "reason": clean_reason}
        self.set_meta("freshness_waiver", waiver)
        return waiver

    def freshness_waiver(self) -> dict[str, Any] | None:
        value = self.get_meta("freshness_waiver")
        return value if isinstance(value, dict) else None

    def prune_successful_processes(self, keep: int = 64) -> int:
        keep = max(0, int(keep))
        with self.connect() as db:
            rows = db.execute(
                "SELECT handle FROM processes WHERE state='exited' ORDER BY updated_at DESC, rowid DESC"
            ).fetchall()
            stale = [str(row["handle"]) for row in rows[keep:]]
            if not stale:
                return 0
            db.executemany("DELETE FROM processes WHERE handle=?", [(handle,) for handle in stale])
            return len(stale)

    def upsert_process(
        self,
        handle: str,
        pid: int | None,
        argv: list[str],
        cwd: str,
        state: str,
        exit_code: int | None = None,
        failure_message: str | None = None,
    ) -> None:
        if state not in {"running", "draining", "exited", "failed", "orphaned", "resolved"}:
            raise ValueError(f"invalid process state: {state}")
        with self.connect() as db:
            db.execute(
                "INSERT INTO processes(handle,pid,argv_json,cwd,state,exit_code,failure_message) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(handle) DO UPDATE SET pid=excluded.pid,state=excluded.state,exit_code=excluded.exit_code,failure_message=excluded.failure_message,updated_at=CURRENT_TIMESTAMP",
                (handle, pid, json.dumps(argv_record(argv), sort_keys=True), scrub_persisted_text(cwd, limit=4096), state, exit_code, scrub_persisted_text(failure_message, limit=4096)),
            )

    def process_rows(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM processes ORDER BY updated_at DESC")]

    def mark_running_processes_orphaned(self, reason: str) -> int:
        clean = scrub_persisted_text(reason, limit=2048) or "helper ownership lost"
        with self.connect() as db:
            cur = db.execute(
                "UPDATE processes SET state='orphaned',failure_message=?,updated_at=CURRENT_TIMESTAMP WHERE state IN ('running','draining')",
                (clean,),
            )
            return int(cur.rowcount)

    def resolve_orphaned_process(self, handle: str, evidence: str) -> None:
        clean = scrub_persisted_text(evidence, limit=2048) or ""
        if not clean.strip():
            raise ValueError("resolving an orphaned process requires host-observed evidence")
        with self.connect() as db:
            row = db.execute("SELECT state FROM processes WHERE handle=?", (handle,)).fetchone()
            if row is None:
                raise ValueError(f"unknown process handle: {handle}")
            if row["state"] not in {"orphaned", "failed"}:
                raise ValueError("only orphaned or failed process records can be resolved with host-observed evidence")
            db.execute(
                "UPDATE processes SET state='resolved',failure_resolved=1,failure_resolution_evidence=?,updated_at=CURRENT_TIMESTAMP WHERE handle=?",
                (clean, handle),
            )

    def running_process_count(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) AS n FROM processes WHERE state IN ('running','draining','orphaned')").fetchone()
        return int(row["n"])

    def unresolved_process_failure_count(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) AS n FROM processes WHERE state='failed' AND failure_resolved=0").fetchone()
        return int(row["n"])


def create_store(cwd: str | Path, *, task_id: str | None = None) -> StateStore:
    task_id = validate_task_id(task_id) if task_id is not None else new_task_id()
    tasks = _tasks_dir(cwd)
    task_dir = tasks / task_id
    try:
        task_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as exc:
        raise RuntimeError(f"codex-loop task already exists: {task_id}") from exc
    _ensure_private_dir(task_dir)
    store = StateStore(task_dir / "state.sqlite3")
    return store


def open_store(cwd: str | Path, task_id: str | None = None) -> StateStore:
    resolved = task_id or active_task_id(cwd)
    if not resolved:
        raise RuntimeError("no active codex-loop task; run bootstrap or pass --task-id")
    resolved = validate_task_id(resolved)
    path = root_state_dir(cwd) / "tasks" / resolved / "state.sqlite3"
    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise RuntimeError(f"unknown codex-loop task: {resolved}") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise RuntimeError(f"task state database is not a regular file: {path}")
    if hasattr(os, "geteuid") and st.st_uid != os.geteuid():
        raise PermissionError(f"task state database is not owned by current user: {path}")
    store = StateStore(path)
    if store.get_meta("task_id") != resolved:
        raise RuntimeError(f"task state identity mismatch: {resolved}")
    return store


def service_token() -> str:
    return secrets.token_urlsafe(32)
