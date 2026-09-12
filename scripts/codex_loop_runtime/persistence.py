from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .change_tracker import capture_baseline
from .release_lineage import capture_workspace_binding
from .state import MAX_REQUEST_AUTHORITY_CHARS, StateStore, create_store, open_store, scrub_persisted_text, set_active_task, validate_task_id

SCHEMA_VERSION = 4
BACKENDS = {"off", "google_drive"}
DEFAULT_TTL_DAYS = {"active": 30, "completed": 7, "cancelled": 7, "abandoned": 14}
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
_EXTERNAL_REQUIRES_RECONCILIATION = {"dispatched", "outcome_unknown"}


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
    text = str(value)
    prefix = "resume-sha256:"
    if text.startswith(prefix) and _SHA64_RE.fullmatch(text[len(prefix):]):
        return text[len(prefix):]
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
        "cleanup": "ttl_plus_bounded_adapter_gc",
    }


def _historical_summary(store: StateStore) -> dict[str, Any]:
    with store.connect() as db:
        row = db.execute("SELECT COUNT(*) AS n, MAX(generation) AS max_generation FROM validations").fetchone()
    return {
        "validation_count": int(row["n"]),
        "latest_validation_generation": None if row["max_generation"] is None else int(row["max_generation"]),
        "freshness_on_resume": "HISTORICAL",
    }


def build_state_manifest(
    root: Path,
    cwd: Path,
    store: StateStore,
    *,
    backend: str = "google_drive",
    repository: str | None = None,
    source_commit: str | None = None,
    source_tree: str | None = None,
    ttl_days: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    policy = persistence_policy(backend)
    if not policy["enabled"]:
        raise ValueError("persistence export requires an enabled backend")
    current = _utc_now(now)
    status = str(store.get_meta("task_status", "active"))
    ttl = int(ttl_days if ttl_days is not None else DEFAULT_TTL_DAYS.get(status, 14))
    if ttl < 1 or ttl > 365:
        raise ValueError("ttl_days must be between 1 and 365")
    for label, value in (("source_commit", source_commit), ("source_tree", source_tree)):
        if value is not None and not _SHA40_RE.fullmatch(str(value).strip().lower()):
            raise ValueError(f"{label} must be a full 40-hex Git SHA")
    checkpoint = store.latest_checkpoint()
    checkpoint_summary = checkpoint.get("summary", {}) if checkpoint else {}
    binding = store.get_meta("workspace_binding", {}) or {}
    external_actions = [
        {
            "kind": str(item.get("kind") or ""),
            "action_class": str(item.get("action_class") or ""),
            "state": str(item.get("state") or ""),
            "identity_sha256": _hash_identity(item.get("identity")),
            "failure_resolved": bool(item.get("failure_resolved", 0)),
        }
        for item in store.external_actions()
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "codex_loop_resume",
        "created_at": _iso(current),
        "expires_at": _iso(current + timedelta(days=ttl)),
        "persistence": policy,
        "task": {
            "task_id": store.task_id,
            "status": status,
            "request_anchor": scrub_persisted_text(store.request_anchor(), limit=MAX_REQUEST_AUTHORITY_CHARS) or "",
            "objective": scrub_persisted_text(str(store.get_meta("objective", "")), limit=8192) or "",
            "profile": str(store.get_meta("profile", "regular")),
            "requires_validation": bool(store.get_meta("requires_validation", False)),
            "requires_clean_process_exit": bool(store.get_meta("requires_clean_process_exit", False)),
        },
        "plan": store.plan(),
        "acceptance": [scrub_persisted_text(str(x.get("text", "")), limit=4096) or "" for x in store.criteria()],
        "steers": [scrub_persisted_text(str(x.get("text", "")), limit=MAX_REQUEST_AUTHORITY_CHARS) or "" for x in store.request_steers()],
        "external_actions": external_actions,
        "resume": {
            "checkpoint_present": checkpoint is not None,
            "next_action": scrub_persisted_text(checkpoint_summary.get("next_action"), limit=4096),
        },
        "workspace": {
            "repository": scrub_persisted_text(repository, limit=512),
            "base_commit": binding.get("base_commit"),
            "base_tree": binding.get("base_tree"),
            "source_commit": None if source_commit is None else str(source_commit).lower(),
            "source_tree": None if source_tree is None else str(source_tree).lower(),
        },
        "historical": _historical_summary(store),
        "privacy": {
            "contains_chain_of_thought": False,
            "contains_credentials": False,
            "contains_hidden_instructions": False,
            "contains_tool_transcript": False,
            "external_action_identity_is_hashed": True,
        },
    }
    return validate_state_manifest(manifest)


def write_state_manifest(store: StateStore, manifest: dict[str, Any]) -> Path:
    manifest = validate_state_manifest(manifest)
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
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported persistence schema_version")
    if manifest.get("kind") != "codex_loop_resume":
        raise ValueError("unsupported persistence manifest kind")
    required = {"schema_version", "kind", "created_at", "expires_at", "persistence", "task", "plan", "acceptance", "steers", "external_actions", "resume", "workspace", "historical", "privacy"}
    extra = set(manifest) - required
    missing = required - set(manifest)
    if extra or missing:
        raise ValueError(f"persistence manifest shape mismatch; missing={sorted(missing)} extra={sorted(extra)}")
    result = json.loads(json.dumps(manifest))
    for key in ("created_at", "expires_at"):
        value = result.get(key)
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError(f"{key} must be a UTC Z timestamp")
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    policy = result["persistence"]
    if policy.get("backend") not in BACKENDS - {"off"} or policy.get("credentials_owner") != "host":
        raise ValueError("persistence backend must be enabled and host-owned")
    task = result["task"]
    if not str(task.get("request_anchor") or "").strip() or not str(task.get("objective") or "").strip():
        raise ValueError("persistence task requires request_anchor and objective")
    if not isinstance(task.get("requires_validation"), bool) or not isinstance(task.get("requires_clean_process_exit"), bool):
        raise ValueError("persistence task validation flags must be boolean")
    if not isinstance(result["plan"], list) or not isinstance(result["acceptance"], list) or not isinstance(result["steers"], list):
        raise ValueError("plan, acceptance, and steers must be lists")
    in_progress = 0
    for item in result["plan"]:
        if not isinstance(item, dict) or set(item) != {"step", "status"}:
            raise ValueError("plan items require exactly step and status")
        if not str(item["step"]).strip() or item["status"] not in {"pending", "in_progress", "completed"}:
            raise ValueError("invalid plan item")
        in_progress += item["status"] == "in_progress"
    if in_progress > 1:
        raise ValueError("plan may contain at most one in_progress step")
    if any(not isinstance(x, str) or not x.strip() for x in result["acceptance"] + result["steers"]):
        raise ValueError("acceptance and steer text must be non-empty strings")
    if not isinstance(result["external_actions"], list):
        raise ValueError("external_actions must be a list")
    for item in result["external_actions"]:
        if not isinstance(item, dict):
            raise ValueError("external action must be an object")
        if item.get("action_class") not in {"read_only", "recheckable", "external_non_idempotent"}:
            raise ValueError("invalid external action class")
        if item.get("state") not in {"planned", "dispatched", "terminal_success", "terminal_failure", "outcome_unknown", "cancelled_before_dispatch"}:
            raise ValueError("invalid external action state")
        identity_hash = item.get("identity_sha256")
        if identity_hash is not None and not _SHA64_RE.fullmatch(str(identity_hash)):
            raise ValueError("external action identity_sha256 must be a 64-hex hash")
        if item.get("action_class") == "external_non_idempotent" and not identity_hash:
            raise ValueError("non-idempotent persisted action requires hashed stable identity")
    for key in ("base_commit", "base_tree", "source_commit", "source_tree"):
        value = result["workspace"].get(key)
        if value is not None and not _SHA40_RE.fullmatch(str(value).lower()):
            raise ValueError(f"workspace.{key} must be null or a full 40-hex Git SHA")
    privacy = result["privacy"]
    if any(bool(privacy.get(k)) for k in ("contains_chain_of_thought", "contains_credentials", "contains_hidden_instructions", "contains_tool_transcript")):
        raise ValueError("manifest declares forbidden private/session content")
    if privacy.get("external_action_identity_is_hashed") is not True:
        raise ValueError("external action identities must be hashed")
    if result["historical"].get("freshness_on_resume") != "HISTORICAL":
        raise ValueError("persisted validation must be historical on resume")
    return result


def load_state_manifest(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) > 512 * 1024:
        raise ValueError("persistence manifest exceeds 512 KiB")
    return validate_state_manifest(json.loads(payload.decode("utf-8")))


def cleanup_decision(
    manifest: dict[str, Any], *, now: datetime | None = None, ownership_proven: bool = False,
    bounded_scope_proven: bool = False, recoverable_delete_supported: bool = False,
    permanent_delete_supported: bool = False,
) -> dict[str, Any]:
    manifest = validate_state_manifest(manifest)
    current = _utc_now(now)
    expires = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
    expired = current >= expires
    unresolved = any(
        x.get("state") in {"planned", "dispatched", "outcome_unknown"}
        or (x.get("state") == "terminal_failure" and not x.get("failure_resolved"))
        for x in manifest["external_actions"]
    )
    scope_proven = bool(ownership_proven and bounded_scope_proven)
    if unresolved:
        action, reason, adapter = "retain_for_reconciliation", "unresolved_external_action", None
    elif not expired:
        action, reason, adapter = "retain", "not_expired", None
    elif not scope_proven:
        action, reason, adapter = "cleanup_pending", "ownership_or_bounded_scope_unproven", None
    elif recoverable_delete_supported:
        action, reason, adapter = "recoverable_delete", "expired_clean_manifest", "trash"
    elif permanent_delete_supported:
        action, reason, adapter = "permanent_delete", "expired_clean_manifest", "delete_file"
    else:
        action, reason, adapter = "cleanup_pending", "no_supported_delete_primitive", None
    return {
        "artifact_class": "durable_recovery_state", "backend": manifest["persistence"]["backend"],
        "expired": expired, "unresolved_external_actions": unresolved, "scope_proven": scope_proven,
        "action": action, "adapter_operation": adapter, "destructive": action == "permanent_delete", "reason": reason,
    }


def build_resume_plan(manifest: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    manifest = validate_state_manifest(manifest)
    workspace = manifest["workspace"]
    required: list[dict[str, Any]] = [{"kind": "workspace_presence"}]
    expected_commit = workspace.get("source_commit") or workspace.get("base_commit")
    expected_tree = workspace.get("source_tree") or workspace.get("base_tree")
    if expected_commit:
        required.append({"kind": "repository_head", "expected": expected_commit})
    if expected_tree:
        required.append({"kind": "repository_tree", "expected": expected_tree})
    unresolved = []
    for item in manifest["external_actions"]:
        state = str(item.get("state"))
        if state in _EXTERNAL_REQUIRES_RECONCILIATION or (state == "terminal_failure" and not item.get("failure_resolved")):
            descriptor = {"kind": item["kind"], "identity_sha256": item.get("identity_sha256"), "historical_state": state, "action_class": item["action_class"]}
            unresolved.append(descriptor)
            required.append({"kind": "external_action_state", "action": descriptor})
    expires = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
    return {
        "schema_version": 2,
        "status": "NEEDS_RECONCILIATION" if required else "RESUMED",
        "manifest_sha256": _canonical_sha256(manifest),
        "manifest_expired": _utc_now(now) >= expires,
        "prior_task_id": manifest["task"].get("task_id"),
        "required_observations": required,
        "unresolved_external_actions": unresolved,
        "freshness_rules": {"validation": "HISTORICAL", "external_actions": "REOBSERVE_IF_UNRESOLVED"},
        "rule": "restore the same lifecycle id and retained authority/plan, then let current repository and external reality win",
    }


def _validate_observations(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("resume observations must be a JSON object")
    allowed = {"workspace_presence", "repository_head", "repository_tree", "external_actions"}
    extra = set(value) - allowed
    if extra:
        raise ValueError(f"resume observations contain unsupported fields: {sorted(extra)}")
    if not isinstance(value.get("workspace_presence"), bool):
        raise ValueError("resume observations require boolean workspace_presence")
    for key in ("repository_head", "repository_tree"):
        item = value.get(key)
        if item is not None and not _SHA40_RE.fullmatch(str(item).lower()):
            raise ValueError(f"{key} must be null or a full 40-hex SHA")
    actions = value.get("external_actions", [])
    if not isinstance(actions, list):
        raise ValueError("external_actions observation must be a list")
    normalized = []
    for item in actions:
        if not isinstance(item, dict) or item.get("state") not in {"terminal_success", "terminal_failure", "outcome_unknown"}:
            raise ValueError("invalid external action observation")
        identity_hash = str(item.get("identity_sha256") or "")
        if not _SHA64_RE.fullmatch(identity_hash):
            raise ValueError("external action observation requires identity_sha256")
        normalized.append({
            "kind": str(item.get("kind") or ""), "identity_sha256": identity_hash,
            "state": str(item["state"]), "evidence": str(item.get("evidence") or ""),
        })
    return {**value, "external_actions": normalized}


def resume_state_manifest(root: Path, manifest: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_state_manifest(manifest)
    observations = _validate_observations(observations)
    root = root.resolve()
    task = manifest["task"]
    task_id = validate_task_id(str(task.get("task_id") or ""))
    try:
        open_store(None, task_id)
    except RuntimeError as exc:
        if "unknown codex-loop task" not in str(exc):
            raise
    else:
        raise RuntimeError("this lifecycle already exists locally; use next/authority instead of persistence-resume")

    store = create_store(None, task_id=task_id)
    baseline_files = 0
    try:
        store.configure_task(
            task_id, str(task["objective"]), list(manifest["acceptance"]),
            request_anchor=str(task["request_anchor"]), profile=str(task.get("profile") or "regular"),
            requires_validation=bool(task.get("requires_validation", False)),
            requires_clean_process_exit=bool(task.get("requires_clean_process_exit", False)),
        )
        store.set_plan(list(manifest["plan"]))
        for text in manifest["steers"]:
            store.record_steer(str(text))
        expected_workspace = dict(manifest["workspace"])
        expected_commit = expected_workspace.get("source_commit") or expected_workspace.get("base_commit")
        expected_tree = expected_workspace.get("source_tree") or expected_workspace.get("base_tree")
        expected_repository = str(expected_workspace.get("repository") or "").strip()
        if expected_commit or expected_tree or expected_repository:
            store.set_meta("resume_expected_workspace", expected_workspace)
        observed_commit = observations.get("repository_head")
        observed_tree = observations.get("repository_tree")
        source_diverged = bool(
            (expected_commit and observed_commit is not None and observed_commit != expected_commit)
            or (expected_tree and observed_tree is not None and observed_tree != expected_tree)
        )
        missing_source = []
        if expected_commit and observed_commit is None:
            missing_source.append("repository_head")
        if expected_tree and observed_tree is None:
            missing_source.append("repository_tree")

        workspace_identity_verified = bool(expected_commit or expected_tree) and not source_diverged and not missing_source
        if observations["workspace_presence"] and workspace_identity_verified:
            store.set_meta("workspace_binding", capture_workspace_binding(root))
            store.set_meta("workspace_cwd", str(root))
            baseline_files = capture_baseline(root, store)
            set_active_task(root, store.task_id)

        observed_actions = {(x["kind"], x["identity_sha256"]): x for x in observations["external_actions"]}
        unresolved_external = []
        for old in manifest["external_actions"]:
            state = str(old.get("state"))
            if state not in _EXTERNAL_REQUIRES_RECONCILIATION and not (state == "terminal_failure" and not old.get("failure_resolved")):
                continue
            identity_hash = str(old.get("identity_sha256") or "")
            obs = observed_actions.get((str(old["kind"]), identity_hash))
            identity = f"resume-sha256:{identity_hash}" if identity_hash else None
            action_id = store.record_external(
                str(old["kind"]), "planned", identity, {"resume": True, "persisted_state": state},
                action_class=str(old["action_class"]),
            )
            if state in {"dispatched", "outcome_unknown", "terminal_failure"} or obs is not None:
                store.record_external(
                    str(old["kind"]), "dispatched", identity, {"resume": True, "persisted_state": state},
                    action_class=str(old["action_class"]), action_id=action_id,
                )
            if not obs or obs["state"] == "outcome_unknown":
                if state == "outcome_unknown" or (obs is not None and obs["state"] == "outcome_unknown"):
                    store.record_external(
                        str(old["kind"]), "outcome_unknown", identity,
                        {"resume": True, "evidence": "persisted or current outcome remains unknown"},
                        action_class=str(old["action_class"]), action_id=action_id,
                    )
                elif state == "terminal_failure":
                    store.record_external(
                        str(old["kind"]), "terminal_failure", identity,
                        {"resume": True, "evidence": "persisted unresolved terminal failure"},
                        action_class=str(old["action_class"]), action_id=action_id,
                    )
                unresolved_external.append({
                    "kind": old["kind"], "identity_sha256": identity_hash,
                    "state": "missing_observation" if not obs else "outcome_unknown",
                })
                continue
            store.record_external(
                str(old["kind"]), obs["state"], identity, {"resume": True, "evidence": obs["evidence"]},
                action_class=str(old["action_class"]), action_id=action_id,
            )
            if obs["state"] == "terminal_failure":
                unresolved_external.append({"kind": old["kind"], "identity_sha256": identity_hash, "state": "terminal_failure"})

        store.set_meta("resume_lineage", {"resumed": True, "resume_source_manifest_sha256": _canonical_sha256(manifest), "resume_source_task": task_id})
        store.set_meta("historical_recovery_evidence", {"validation": "HISTORICAL", "historical": manifest["historical"]})
    except Exception:
        shutil.rmtree(store.path.parent, ignore_errors=True)
        raise

    if not observations["workspace_presence"]:
        status = "NEEDS_RECONCILIATION"
    elif source_diverged:
        status = "SOURCE_DIVERGED"
    elif unresolved_external:
        status = "EXTERNAL_ACTION_UNRESOLVED"
    elif missing_source:
        status = "NEEDS_RECONCILIATION"
    elif observations["workspace_presence"] and expected_repository and not workspace_identity_verified:
        status = "NEEDS_RECONCILIATION"
    else:
        status = "RESUMED"
    return {
        "status": status, "created_task": True, "task_id": store.task_id, "state": str(store.path),
        "baseline_files": baseline_files, "source_diverged": source_diverged,
        "missing_source_observations": missing_source, "unresolved_external_actions": unresolved_external,
        "plan": store.plan(), "historical_validation": "HISTORICAL",
        "workspace_bound": bool(store.get_meta("workspace_binding")),
        "rule": "the original lifecycle id, request, steers, and plan resume; current repository/tool/external reality is authoritative",
    }
