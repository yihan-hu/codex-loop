from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable

REGISTRY_VERSION = 1
SESSION_VERSION = 1
WORKSPACE_KINDS = frozenset({"repository", "development_root"})
_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_PERMISSION_KEYS = frozenset({"authorized", "always_allow", "trusted", "granted", "permission", "permissions"})


def _unicode_safe(value: str) -> str:
    return str(value).encode("utf-8", errors="strict").decode("utf-8")


def normalize_alias(raw: str) -> str:
    value = _unicode_safe(str(raw)).strip().lower()
    if not value:
        raise ValueError("workspace name must not be empty")
    if not _ALIAS_RE.fullmatch(value):
        raise ValueError("workspace name must normalize to lowercase letters/digits plus . _ -")
    return value


def codex_loop_home() -> Path:
    override = os.environ.get("CODEX_LOOP_HOME")
    return Path(override).expanduser() if override else Path.home() / ".codex-loop"


def registry_path() -> Path:
    return codex_loop_home() / "workspace-registry.json"


def host_config_path() -> Path:
    return codex_loop_home() / "host.json"


def _ensure_private_dir(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = path.resolve()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError(f"host-local Codex Loop path is not a real directory: {path}")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError(f"host-local Codex Loop directory is not owned by current user: {path}")
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _check_private_regular_file(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"host-local Codex Loop state is not a regular file: {path}")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError(f"host-local Codex Loop state is not owned by current user: {path}")


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    parent = _ensure_private_dir(path.parent)
    if path.exists() or path.is_symlink():
        _check_private_regular_file(path)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        try:
            directory_fd = os.open(parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _empty_registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "workspaces": {}}


def _validate_registry(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("workspace registry must be a JSON object")
    if set(payload) != {"version", "workspaces"}:
        raise ValueError("workspace registry supports only version and workspaces fields")
    if payload.get("version") != REGISTRY_VERSION:
        raise ValueError(f"unsupported workspace registry version: {payload.get('version')!r}")
    raw_workspaces = payload.get("workspaces")
    if not isinstance(raw_workspaces, dict):
        raise ValueError("workspace registry workspaces must be an object")
    workspaces: dict[str, dict[str, str]] = {}
    for raw_name, raw_entry in raw_workspaces.items():
        if not isinstance(raw_name, str):
            raise ValueError("workspace aliases must be strings")
        name = normalize_alias(raw_name)
        if name != raw_name:
            raise ValueError(f"workspace registry key is not canonical: {raw_name!r}")
        if not isinstance(raw_entry, dict):
            raise ValueError(f"workspace entry must be an object: {name}")
        forbidden = _PERMISSION_KEYS.intersection(str(key).lower() for key in raw_entry)
        if forbidden:
            raise ValueError(f"workspace registry must never store authorization fields: {sorted(forbidden)}")
        if set(raw_entry) != {"path", "kind"}:
            raise ValueError(f"workspace entry supports only path and kind fields: {name}")
        path_raw = raw_entry.get("path")
        kind = raw_entry.get("kind")
        if not isinstance(path_raw, str) or not path_raw:
            raise ValueError(f"workspace path must be a non-empty string: {name}")
        path = Path(path_raw).expanduser()
        if not path.is_absolute():
            raise ValueError(f"workspace path must be absolute: {name}")
        if kind not in WORKSPACE_KINDS:
            raise ValueError(f"workspace kind must be one of {sorted(WORKSPACE_KINDS)}: {name}")
        workspaces[name] = {"path": str(path), "kind": str(kind)}
    return {"version": REGISTRY_VERSION, "workspaces": workspaces}


def load_registry() -> dict[str, Any]:
    path = registry_path()
    try:
        _check_private_regular_file(path)
    except FileNotFoundError:
        return _empty_registry()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"workspace registry is invalid JSON and was not reset: {path}") from exc
    return _validate_registry(payload)


def _canonical_existing_directory(raw_path: str | os.PathLike[str]) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ValueError("workspace path must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"workspace path does not exist: {path}") from exc
    if not resolved.is_dir():
        raise ValueError(f"workspace path must be a directory: {resolved}")
    return resolved


def workspace_fingerprint(name: str, entry: dict[str, str]) -> str:
    canonical = {
        "kind": entry["kind"],
        "name": normalize_alias(name),
        "path": entry["path"],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def register_workspace(name: str, path: str | os.PathLike[str], kind: str, *, update: bool = False) -> dict[str, Any]:
    alias = normalize_alias(name)
    if kind not in WORKSPACE_KINDS:
        raise ValueError(f"workspace kind must be one of {sorted(WORKSPACE_KINDS)}")
    resolved = _canonical_existing_directory(path)
    registry = load_registry()
    existing = registry["workspaces"].get(alias)
    if existing is not None and not update:
        raise ValueError(f"workspace alias is already registered: {alias}; use explicit update")
    entry = {"path": str(resolved), "kind": kind}
    registry["workspaces"][alias] = entry
    _atomic_json_write(registry_path(), _validate_registry(registry))
    return {
        "name": alias,
        "path": entry["path"],
        "kind": kind,
        "registered": True,
        "updated": existing is not None,
        "granted": False,
    }


def remove_workspace(name: str) -> dict[str, Any]:
    alias = normalize_alias(name)
    registry = load_registry()
    existing = registry["workspaces"].get(alias)
    if existing is None:
        raise KeyError(f"workspace is not registered: {alias}")
    del registry["workspaces"][alias]
    _atomic_json_write(registry_path(), registry)
    return {"name": alias, "removed": True, "granted": False}


def list_workspaces() -> list[dict[str, str]]:
    registry = load_registry()
    return [
        {"name": name, "kind": entry["kind"], "path": entry["path"]}
        for name, entry in sorted(registry["workspaces"].items())
    ]


def _session_id(raw: str | None, *, generate: bool = False) -> str | None:
    value = raw or os.environ.get("CODEX_LOOP_SESSION_ID")
    if value is None and generate:
        return secrets.token_urlsafe(24)
    if value is None:
        return None
    value = str(value).strip()
    if len(value) < 16 or len(value) > 256 or any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
        raise ValueError("session id must be 16-256 printable non-whitespace ASCII characters")
    return value


def _session_root() -> Path:
    return Path(tempfile.gettempdir()) / "codex-loop" / "workspace-sessions"


def _session_path(session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return _session_root() / f"{digest}.json"


def _empty_session() -> dict[str, Any]:
    return {"version": SESSION_VERSION, "scope": "conversation", "grants": {}}


def _validate_session(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"version", "scope", "grants"}:
        raise ValueError("workspace session state has an invalid schema")
    if payload.get("version") != SESSION_VERSION or payload.get("scope") != "conversation":
        raise ValueError("workspace session state has an unsupported version or scope")
    grants = payload.get("grants")
    if not isinstance(grants, dict):
        raise ValueError("workspace session grants must be an object")
    normalized: dict[str, dict[str, str]] = {}
    for raw_name, raw_grant in grants.items():
        name = normalize_alias(str(raw_name))
        if name != raw_name or not isinstance(raw_grant, dict):
            raise ValueError("workspace session grant is malformed")
        if set(raw_grant) != {"workspace_fingerprint", "authorization_evidence_sha256"}:
            raise ValueError("workspace session grant supports only fingerprint and evidence digest")
        fingerprint = str(raw_grant.get("workspace_fingerprint", ""))
        evidence_digest = str(raw_grant.get("authorization_evidence_sha256", ""))
        if not _HEX64_RE.fullmatch(fingerprint) or not _HEX64_RE.fullmatch(evidence_digest):
            raise ValueError("workspace session grant digests must be sha256 hex")
        normalized[name] = {
            "workspace_fingerprint": fingerprint,
            "authorization_evidence_sha256": evidence_digest,
        }
    return {"version": SESSION_VERSION, "scope": "conversation", "grants": normalized}


def _load_session(session_id: str | None) -> dict[str, Any]:
    if session_id is None:
        return _empty_session()
    path = _session_path(session_id)
    try:
        _check_private_regular_file(path)
    except FileNotFoundError:
        return _empty_session()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("workspace session state is invalid JSON") from exc
    return _validate_session(payload)


def grant_workspace(name: str, authorization_evidence: str, *, session_id: str | None = None) -> dict[str, Any]:
    alias = normalize_alias(name)
    evidence = str(authorization_evidence).strip()
    if not evidence:
        raise ValueError("workspace-grant requires host-observed explicit authorization evidence")
    registry = load_registry()
    entry = registry["workspaces"].get(alias)
    if entry is None:
        raise KeyError(f"workspace is not registered: {alias}")
    path_state = inspect_registered_path(entry)
    if not path_state["valid"]:
        raise RuntimeError(f"registered workspace path is not usable: {path_state['reason']}")
    resolved_session = _session_id(session_id, generate=True)
    assert resolved_session is not None
    session = _load_session(resolved_session)
    session["grants"][alias] = {
        "workspace_fingerprint": workspace_fingerprint(alias, entry),
        "authorization_evidence_sha256": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
    }
    _atomic_json_write(_session_path(resolved_session), _validate_session(session))
    return {
        "name": alias,
        "scope": "conversation",
        "granted": True,
        "session_id": resolved_session,
        "authorization_evidence_recorded": True,
        "path": entry["path"],
        "kind": entry["kind"],
    }


def session_grants(*, session_id: str | None = None) -> dict[str, Any]:
    resolved_session = _session_id(session_id, generate=False)
    session = _load_session(resolved_session)
    registry = load_registry()
    active: list[str] = []
    stale: list[str] = []
    for name, grant in sorted(session["grants"].items()):
        entry = registry["workspaces"].get(name)
        if entry is None or grant["workspace_fingerprint"] != workspace_fingerprint(name, entry):
            stale.append(name)
        else:
            active.append(name)
    return {
        "scope": "conversation",
        "session_present": resolved_session is not None,
        "granted": active,
        "stale": stale,
    }


def inspect_registered_path(entry: dict[str, str]) -> dict[str, Any]:
    configured = Path(entry["path"])
    try:
        resolved = configured.resolve(strict=True)
    except FileNotFoundError:
        return {"valid": False, "exists": False, "realpath": None, "reason": "registered_path_missing"}
    if not resolved.is_dir():
        return {"valid": False, "exists": True, "realpath": str(resolved), "reason": "registered_path_not_directory"}
    if resolved != configured:
        return {"valid": False, "exists": True, "realpath": str(resolved), "reason": "registered_realpath_changed_or_symlinked"}
    return {"valid": True, "exists": True, "realpath": str(resolved), "reason": None}


def _canonical_host_roots(raw_roots: Iterable[str | os.PathLike[str]]) -> list[Path]:
    roots: list[Path] = []
    for raw in raw_roots:
        roots.append(_canonical_existing_directory(raw))
    return roots


def _within(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def resolve_workspace(
    name: str,
    *,
    session_id: str | None = None,
    host_authorized_roots: Iterable[str | os.PathLike[str]] = (),
) -> dict[str, Any]:
    alias = normalize_alias(name)
    registry = load_registry()
    entry = registry["workspaces"].get(alias)
    if entry is None:
        return {
            "name": alias,
            "registered": False,
            "granted": False,
            "host_authorized": False,
            "accessible": False,
            "reasons": ["workspace_not_registered"],
        }
    path_state = inspect_registered_path(entry)
    resolved_session = _session_id(session_id, generate=False)
    session = _load_session(resolved_session)
    grant = session["grants"].get(alias)
    fingerprint = workspace_fingerprint(alias, entry)
    granted = grant is not None and grant["workspace_fingerprint"] == fingerprint
    grant_stale = grant is not None and not granted
    host_roots = _canonical_host_roots(host_authorized_roots)
    realpath = Path(path_state["realpath"]) if path_state["valid"] else None
    host_authorized = bool(realpath is not None and any(_within(realpath, root) for root in host_roots))
    reasons: list[str] = []
    if not path_state["valid"]:
        reasons.append(str(path_state["reason"]))
    if not granted:
        reasons.append("session_grant_stale_registry_changed" if grant_stale else "workspace_not_granted_this_conversation")
    if not host_authorized:
        reasons.append("host_authorization_unproven_or_denied")
    return {
        "name": alias,
        "registered": True,
        "path": entry["path"],
        "kind": entry["kind"],
        "path_exists": path_state["exists"],
        "realpath": path_state["realpath"],
        "path_valid": path_state["valid"],
        "granted": granted,
        "grant_scope": "conversation" if granted else None,
        "host_authorized": host_authorized,
        "accessible": bool(path_state["valid"] and granted and host_authorized),
        "reasons": reasons,
    }


def effective_local_roots(
    *,
    primary_root: str | os.PathLike[str] | None,
    session_id: str | None,
    host_authorized_roots: Iterable[str | os.PathLike[str]],
) -> list[str]:
    host_roots = _canonical_host_roots(host_authorized_roots)
    effective: list[Path] = []
    if primary_root is not None:
        primary = _canonical_existing_directory(primary_root)
        if not any(_within(primary, root) for root in host_roots):
            raise PermissionError("primary local root is not within a host-authorized root")
        effective.append(primary)
    grants = session_grants(session_id=session_id)["granted"]
    for name in grants:
        state = resolve_workspace(name, session_id=session_id, host_authorized_roots=host_roots)
        if state["accessible"]:
            candidate = Path(state["realpath"])
            if candidate not in effective:
                effective.append(candidate)
    return [str(path) for path in effective]
