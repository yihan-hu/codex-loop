from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .state import StateStore, scrub_persisted_text

SCHEMA_VERSION = 1
BACKENDS = {"off", "google_drive"}
DEFAULT_TTL_DAYS = {
    "active": 30,
    "completed": 7,
    "cancelled": 7,
    "abandoned": 14,
}


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash_identity(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def persistence_policy(backend: str = "off") -> dict[str, Any]:
    if backend not in BACKENDS:
        raise ValueError(f"unsupported persistence backend: {backend}")
    return {
        "backend": backend,
        "enabled": backend != "off",
        "default_backend": "off",
        "credentials_owner": "host",
        "source_repository_contains_credentials": False,
        "mode": "state_only" if backend != "off" else "off",
        "workspace_snapshot": False,
        "cleanup": "ttl_plus_opportunistic_gc",
    }


def build_state_manifest(
    root: Path,
    cwd: Path,
    store: StateStore,
    *,
    backend: str = "google_drive",
    repository: str | None = None,
    ttl_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    policy = persistence_policy(backend)
    if not policy["enabled"]:
        raise ValueError("persistence export requires an enabled backend")
    current = _utc_now(now)
    status = str(store.get_meta("task_status", "active"))
    effective_ttl = int(ttl_days if ttl_days is not None else DEFAULT_TTL_DAYS.get(status, 14))
    if effective_ttl < 1 or effective_ttl > 365:
        raise ValueError("ttl_days must be between 1 and 365")
    checkpoint = store.latest_checkpoint()
    checkpoint_summary = checkpoint.get("summary", {}) if checkpoint else {}
    binding = store.get_meta("workspace_binding", {}) or {}

    criteria = []
    for item in store.criteria():
        criteria.append({
            "ordinal": int(item["ordinal"]),
            "text": scrub_persisted_text(str(item["text"]), limit=4096) or "",
            "status": str(item["status"]),
        })

    external_actions = []
    for item in store.external_actions():
        external_actions.append({
            "kind": str(item.get("kind") or ""),
            "action_class": str(item.get("action_class") or ""),
            "state": str(item.get("state") or ""),
            "identity_sha256": _hash_identity(item.get("identity")),
            "failure_resolved": bool(item.get("failure_resolved", 0)),
        })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "codex_loop_state_only",
        "created_at": _iso(current),
        "expires_at": _iso(current + timedelta(days=effective_ttl)),
        "persistence": policy,
        "task": {
            "task_id": store.task_id,
            "status": status,
            "objective": scrub_persisted_text(str(store.get_meta("objective", "")), limit=8192) or "",
            "profile": str(store.get_meta("profile", "regular")),
            "generation": store.generation(),
            "plan_revision": int(store.get_meta("plan_revision", 0)),
        },
        "criteria": criteria,
        "external_actions": external_actions,
        "resume": {
            "checkpoint_present": checkpoint is not None,
            "checkpoint_generation": None if checkpoint is None else int(checkpoint["generation"]),
            "next_action": scrub_persisted_text(checkpoint_summary.get("next_action"), limit=4096),
            "completion_status": (checkpoint_summary.get("completion") or {}).get("status"),
        },
        "workspace": {
            "repository": scrub_persisted_text(repository, limit=512),
            "base_commit": binding.get("base_commit"),
            "base_tree": binding.get("base_tree"),
        },
        "privacy": {
            "contains_chain_of_thought": False,
            "contains_credentials": False,
            "contains_hidden_instructions": False,
            "contains_tool_transcript": False,
            "external_action_identity_is_hashed": True,
        },
    }
    return manifest


def write_state_manifest(store: StateStore, manifest: dict[str, Any]) -> Path:
    validate_state_manifest(manifest)
    directory = store.path.parent / "persistence"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "state-only.json"
    payload = json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    return path


def validate_state_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("persistence manifest must be a JSON object")
    allowed_top = {"schema_version", "kind", "created_at", "expires_at", "persistence", "task", "criteria", "external_actions", "resume", "workspace", "privacy"}
    extra_top = sorted(set(manifest) - allowed_top)
    if extra_top:
        raise ValueError(f"persistence manifest contains unsupported top-level fields: {extra_top}")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported persistence schema_version")
    if manifest.get("kind") != "codex_loop_state_only":
        raise ValueError("unsupported persistence manifest kind")
    policy = manifest.get("persistence") or {}
    if policy.get("backend") not in BACKENDS - {"off"}:
        raise ValueError("manifest backend must be an enabled supported backend")
    if policy.get("credentials_owner") != "host":
        raise ValueError("persistence credentials must remain host-owned")
    privacy = manifest.get("privacy") or {}
    forbidden_true = [
        "contains_chain_of_thought",
        "contains_credentials",
        "contains_hidden_instructions",
        "contains_tool_transcript",
    ]
    if any(bool(privacy.get(key)) for key in forbidden_true):
        raise ValueError("manifest declares forbidden private/session content")
    for key in ("created_at", "expires_at"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError(f"{key} must be a UTC Z timestamp")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(manifest.get("criteria"), list):
        raise ValueError("criteria must be a list")
    if not isinstance(manifest.get("external_actions"), list):
        raise ValueError("external_actions must be a list")
    allowed_nested = {
        "persistence": {"backend", "enabled", "default_backend", "credentials_owner", "source_repository_contains_credentials", "mode", "workspace_snapshot", "cleanup"},
        "task": {"task_id", "status", "objective", "profile", "generation", "plan_revision"},
        "resume": {"checkpoint_present", "checkpoint_generation", "next_action", "completion_status"},
        "workspace": {"repository", "base_commit", "base_tree"},
        "privacy": {"contains_chain_of_thought", "contains_credentials", "contains_hidden_instructions", "contains_tool_transcript", "external_action_identity_is_hashed"},
    }
    for section, allowed in allowed_nested.items():
        value = manifest.get(section)
        if not isinstance(value, dict):
            raise ValueError(f"{section} must be an object")
        extra = sorted(set(value) - allowed)
        if extra:
            raise ValueError(f"{section} contains unsupported fields: {extra}")
    criterion_keys = {"ordinal", "text", "status"}
    action_keys = {"kind", "action_class", "state", "identity_sha256", "failure_resolved"}
    if any(not isinstance(item, dict) or set(item) - criterion_keys for item in manifest["criteria"]):
        raise ValueError("criteria contains unsupported fields")
    if any(not isinstance(item, dict) or set(item) - action_keys for item in manifest["external_actions"]):
        raise ValueError("external_actions contains unsupported fields")
    return manifest


def load_state_manifest(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) > 512 * 1024:
        raise ValueError("persistence manifest exceeds 512 KiB")
    return validate_state_manifest(json.loads(payload.decode("utf-8")))


def cleanup_decision(manifest: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    validate_state_manifest(manifest)
    current = _utc_now(now)
    expires = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
    expired = current >= expires
    unresolved = any(
        item.get("state") in {"planned", "dispatched", "outcome_unknown"}
        or (item.get("state") == "terminal_failure" and not item.get("failure_resolved"))
        for item in manifest.get("external_actions", [])
    )
    return {
        "expired": expired,
        "unresolved_external_actions": unresolved,
        "action": "retain_for_reconciliation" if unresolved else ("trash" if expired else "retain"),
        "permanent_delete": False,
        "rule": "trash-first; permanent deletion remains Drive/user policy",
    }
