from __future__ import annotations

import hashlib
import json
import re
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .change_tracker import capture_baseline
from .release_lineage import capture_workspace_binding
from .state import StateStore, create_store, scrub_persisted_text, set_active_task

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSIONS = {1}
BACKENDS = {"off", "google_drive"}
DEFAULT_TTL_DAYS = {
    "active": 30,
    "completed": 7,
    "cancelled": 7,
    "abandoned": 14,
}
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
_EXTERNAL_TERMINAL = {"terminal_success", "terminal_failure", "outcome_unknown"}
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
    audit = store.get_meta("objective_completion_audit")
    return {
        "validation_count": int(row["n"]),
        "latest_validation_generation": None if row["max_generation"] is None else int(row["max_generation"]),
        "reviewed_generation": int(store.get_meta("changes_reviewed_generation", -1)),
        "objective_audit_present": isinstance(audit, dict),
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
    effective_ttl = int(ttl_days if ttl_days is not None else DEFAULT_TTL_DAYS.get(status, 14))
    if effective_ttl < 1 or effective_ttl > 365:
        raise ValueError("ttl_days must be between 1 and 365")
    checkpoint = store.latest_checkpoint()
    checkpoint_summary = checkpoint.get("summary", {}) if checkpoint else {}
    binding = store.get_meta("workspace_binding", {}) or {}

    if source_commit is not None:
        source_commit = str(source_commit).strip().lower()
        if not _SHA40_RE.fullmatch(source_commit):
            raise ValueError("source_commit must be a full 40-hex Git commit SHA")
    if source_tree is not None:
        source_tree = str(source_tree).strip().lower()
        if not _SHA40_RE.fullmatch(source_tree):
            raise ValueError("source_tree must be a full 40-hex Git tree SHA")

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
            "requires_validation": bool(store.get_meta("requires_validation", True)),
            "no_validation_reason": scrub_persisted_text(store.get_meta("no_validation_reason"), limit=4096),
            "requires_clean_process_exit": bool(store.get_meta("requires_clean_process_exit", False)),
        },
        "criteria": criteria,
        "external_actions": external_actions,
        "resume": {
            "checkpoint_present": checkpoint is not None,
            "checkpoint_generation": None if checkpoint is None else int(checkpoint["generation"]),
            "next_action": scrub_persisted_text(checkpoint_summary.get("next_action"), limit=4096),
            "completion_status": (checkpoint_summary.get("completion") or {}).get("status"),
            "lineage_policy": "fork_historical_state_under_current_reality",
        },
        "workspace": {
            "repository": scrub_persisted_text(repository, limit=512),
            "base_commit": binding.get("base_commit"),
            "base_tree": binding.get("base_tree"),
            "source_commit": source_commit,
            "source_tree": source_tree,
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


def _migrate_v1(manifest: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(manifest)
    migrated["schema_version"] = SCHEMA_VERSION
    task = migrated.setdefault("task", {})
    task.setdefault("requires_validation", True)
    task.setdefault("no_validation_reason", None)
    task.setdefault("requires_clean_process_exit", False)
    resume = migrated.setdefault("resume", {})
    resume.setdefault("lineage_policy", "fork_historical_state_under_current_reality")
    workspace = migrated.setdefault("workspace", {})
    workspace.setdefault("source_commit", None)
    workspace.setdefault("source_tree", None)
    migrated.setdefault("historical", {
        "validation_count": None,
        "latest_validation_generation": None,
        "reviewed_generation": None,
        "objective_audit_present": None,
        "freshness_on_resume": "HISTORICAL",
    })
    return migrated


def validate_state_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("persistence manifest must be a JSON object")
    version = manifest.get("schema_version")
    if version in LEGACY_SCHEMA_VERSIONS:
        manifest = _migrate_v1(manifest)
    elif version != SCHEMA_VERSION:
        raise ValueError("unsupported persistence schema_version")
    else:
        manifest = deepcopy(manifest)

    allowed_top = {
        "schema_version", "kind", "created_at", "expires_at", "persistence", "task",
        "criteria", "external_actions", "resume", "workspace", "historical", "privacy",
    }
    extra_top = sorted(set(manifest) - allowed_top)
    if extra_top:
        raise ValueError(f"persistence manifest contains unsupported top-level fields: {extra_top}")
    if manifest.get("kind") != "codex_loop_state_only":
        raise ValueError("unsupported persistence manifest kind")
    policy = manifest.get("persistence") or {}
    if policy.get("backend") not in BACKENDS - {"off"}:
        raise ValueError("manifest backend must be an enabled supported backend")
    if policy.get("credentials_owner") != "host":
        raise ValueError("persistence credentials must remain host-owned")
    privacy = manifest.get("privacy") or {}
    forbidden_true = [
        "contains_chain_of_thought", "contains_credentials", "contains_hidden_instructions", "contains_tool_transcript",
    ]
    if any(bool(privacy.get(key)) for key in forbidden_true):
        raise ValueError("manifest declares forbidden private/session content")
    if privacy.get("external_action_identity_is_hashed") is not True:
        raise ValueError("external action identities must be hashed in persistence manifests")
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
        "task": {"task_id", "status", "objective", "profile", "generation", "plan_revision", "requires_validation", "no_validation_reason", "requires_clean_process_exit"},
        "resume": {"checkpoint_present", "checkpoint_generation", "next_action", "completion_status", "lineage_policy"},
        "workspace": {"repository", "base_commit", "base_tree", "source_commit", "source_tree"},
        "historical": {"validation_count", "latest_validation_generation", "reviewed_generation", "objective_audit_present", "freshness_on_resume"},
        "privacy": {"contains_chain_of_thought", "contains_credentials", "contains_hidden_instructions", "contains_tool_transcript", "external_action_identity_is_hashed"},
    }
    for section, allowed in allowed_nested.items():
        value = manifest.get(section)
        if not isinstance(value, dict):
            raise ValueError(f"{section} must be an object")
        extra = sorted(set(value) - allowed)
        if extra:
            raise ValueError(f"{section} contains unsupported fields: {extra}")

    task = manifest["task"]
    if not str(task.get("objective") or "").strip():
        raise ValueError("manifest task objective must not be empty")
    if not isinstance(task.get("requires_validation"), bool):
        raise ValueError("task.requires_validation must be boolean")
    if not isinstance(task.get("requires_clean_process_exit"), bool):
        raise ValueError("task.requires_clean_process_exit must be boolean")
    if not task["requires_validation"] and not str(task.get("no_validation_reason") or "").strip():
        raise ValueError("no-validation task requires no_validation_reason")

    criterion_keys = {"ordinal", "text", "status"}
    action_keys = {"kind", "action_class", "state", "identity_sha256", "failure_resolved"}
    if any(not isinstance(item, dict) or set(item) - criterion_keys for item in manifest["criteria"]):
        raise ValueError("criteria contains unsupported fields")
    if any(not isinstance(item, dict) or set(item) - action_keys for item in manifest["external_actions"]):
        raise ValueError("external_actions contains unsupported fields")
    for item in manifest["criteria"]:
        if not str(item.get("text") or "").strip():
            raise ValueError("criteria text must not be empty")
    for item in manifest["external_actions"]:
        if not str(item.get("kind") or "").strip():
            raise ValueError("external action kind must not be empty")
        if item.get("action_class") not in {"read_only", "recheckable", "external_non_idempotent"}:
            raise ValueError("external action contains invalid action_class")
        if item.get("state") not in {"planned", "dispatched", "terminal_success", "terminal_failure", "outcome_unknown", "cancelled_before_dispatch"}:
            raise ValueError("external action contains invalid state")
        identity_hash = item.get("identity_sha256")
        if identity_hash is not None and not _SHA64_RE.fullmatch(str(identity_hash)):
            raise ValueError("external action identity_sha256 must be a 64-hex hash")
        if item.get("action_class") == "external_non_idempotent" and not identity_hash:
            raise ValueError("non-idempotent persisted action requires hashed stable identity")

    for key in ("base_commit", "base_tree", "source_commit", "source_tree"):
        value = manifest["workspace"].get(key)
        if value is not None and not _SHA40_RE.fullmatch(str(value).lower()):
            raise ValueError(f"workspace.{key} must be null or full 40-hex Git SHA")
    if manifest["resume"].get("lineage_policy") != "fork_historical_state_under_current_reality":
        raise ValueError("unsupported resume lineage policy")
    if manifest["historical"].get("freshness_on_resume") != "HISTORICAL":
        raise ValueError("persisted historical evidence must become HISTORICAL on resume")
    return manifest


def load_state_manifest(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) > 512 * 1024:
        raise ValueError("persistence manifest exceeds 512 KiB")
    return validate_state_manifest(json.loads(payload.decode("utf-8")))


def cleanup_decision(
    manifest: dict[str, Any],
    *,
    now: datetime | None = None,
    ownership_proven: bool = False,
    bounded_scope_proven: bool = False,
    recoverable_delete_supported: bool = False,
    permanent_delete_supported: bool = False,
) -> dict[str, Any]:
    manifest = validate_state_manifest(manifest)
    current = _utc_now(now)
    expires = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
    expired = current >= expires
    unresolved = any(
        item.get("state") in {"planned", "dispatched", "outcome_unknown"}
        or (item.get("state") == "terminal_failure" and not item.get("failure_resolved"))
        for item in manifest.get("external_actions", [])
    )
    backend = str(manifest["persistence"]["backend"])
    scope_proven = bool(ownership_proven and bounded_scope_proven)

    if unresolved:
        action = "retain_for_reconciliation"
        reason = "unresolved_external_action"
        adapter_operation = None
    elif not expired:
        action = "retain"
        reason = "not_expired"
        adapter_operation = None
    elif not scope_proven:
        action = "cleanup_pending"
        reason = "ownership_or_bounded_scope_unproven"
        adapter_operation = None
    elif recoverable_delete_supported:
        action = "recoverable_delete"
        reason = "expired_clean_manifest_with_recoverable_delete"
        adapter_operation = "trash" if backend == "google_drive" else "recoverable_delete"
    elif permanent_delete_supported:
        action = "permanent_delete"
        reason = "expired_clean_manifest_with_only_permanent_delete"
        adapter_operation = "delete_file" if backend == "google_drive" else "permanent_delete"
    else:
        action = "cleanup_pending"
        reason = "no_supported_delete_primitive"
        adapter_operation = None

    return {
        "artifact_class": "durable_recovery_state",
        "backend": backend,
        "expired": expired,
        "unresolved_external_actions": unresolved,
        "ownership_proven": bool(ownership_proven),
        "bounded_scope_proven": bool(bounded_scope_proven),
        "scope_proven": scope_proven,
        "recoverable_delete_supported": bool(recoverable_delete_supported),
        "permanent_delete_supported": bool(permanent_delete_supported),
        "action": action,
        "adapter_operation": adapter_operation,
        "destructive": action == "permanent_delete",
        "reason": reason,
        "rule": "artifact-class and adapter-specific cleanup; retain unresolved state, require ownership and bounded scope, prefer recoverable deletion, otherwise allow supported permanent deletion",
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

    unresolved_actions: list[dict[str, Any]] = []
    for item in manifest["external_actions"]:
        state = str(item.get("state"))
        if state in _EXTERNAL_REQUIRES_RECONCILIATION or (state == "terminal_failure" and not item.get("failure_resolved")):
            descriptor = {
                "kind": str(item["kind"]),
                "identity_sha256": item.get("identity_sha256"),
                "historical_state": state,
                "action_class": str(item["action_class"]),
            }
            unresolved_actions.append(descriptor)
            required.append({"kind": "external_action_state", "action": descriptor})

    expires = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
    return {
        "schema_version": 1,
        "status": "NEEDS_RECONCILIATION" if required else "RESUMED",
        "manifest_sha256": _canonical_sha256(manifest),
        "manifest_expired": _utc_now(now) >= expires,
        "prior_task_id": manifest["task"].get("task_id"),
        "prior_generation": int(manifest["task"].get("generation", 0)),
        "required_observations": required,
        "unresolved_external_actions": unresolved_actions,
        "freshness_rules": {
            "criterion_pass": "STALE",
            "validation": "HISTORICAL",
            "change_review": "HISTORICAL",
            "objective_audit": "HISTORICAL",
            "capability_and_permission_state": "REOBSERVE",
        },
        "rule": "persisted state is historical recovery evidence; current observed reality is authoritative",
    }


def _validate_observations(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("resume observations must be a JSON object")
    allowed = {"workspace_presence", "repository_head", "repository_tree", "external_actions"}
    extra = sorted(set(value) - allowed)
    if extra:
        raise ValueError(f"resume observations contain unsupported fields: {extra}")
    if "workspace_presence" not in value or not isinstance(value["workspace_presence"], bool):
        raise ValueError("resume observations require boolean workspace_presence")
    for key in ("repository_head", "repository_tree"):
        item = value.get(key)
        if item is not None and not _SHA40_RE.fullmatch(str(item).lower()):
            raise ValueError(f"{key} must be null or a full 40-hex SHA")
    actions = value.get("external_actions", [])
    if not isinstance(actions, list):
        raise ValueError("external_actions observation must be a list")
    normalized: list[dict[str, Any]] = []
    for item in actions:
        if not isinstance(item, dict):
            raise ValueError("external action observation must be an object")
        extra_item = set(item) - {"kind", "identity_sha256", "state", "evidence"}
        if extra_item:
            raise ValueError(f"external action observation contains unsupported fields: {sorted(extra_item)}")
        kind = str(item.get("kind") or "").strip()
        identity_hash = str(item.get("identity_sha256") or "").strip().lower()
        state = str(item.get("state") or "").strip()
        evidence = (scrub_persisted_text(str(item.get("evidence") or ""), limit=4096) or "").strip()
        if not kind or not _SHA64_RE.fullmatch(identity_hash):
            raise ValueError("external action observation requires kind and identity_sha256")
        if state not in _EXTERNAL_TERMINAL:
            raise ValueError("external action observation state must be terminal_success, terminal_failure, or outcome_unknown")
        if not evidence:
            raise ValueError("external action observation requires concise current-reality evidence")
        normalized.append({"kind": kind, "identity_sha256": identity_hash, "state": state, "evidence": evidence})
    result = dict(value)
    result["repository_head"] = None if value.get("repository_head") is None else str(value["repository_head"]).lower()
    result["repository_tree"] = None if value.get("repository_tree") is None else str(value["repository_tree"]).lower()
    result["external_actions"] = normalized
    return result


def _observation_by_identity(observations: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(item["kind"]), str(item["identity_sha256"])): item
        for item in observations.get("external_actions", [])
    }


def resume_state_manifest(root: Path, manifest: dict[str, Any], observations: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_state_manifest(manifest)
    observations = _validate_observations(observations)
    root = root.resolve()
    if not observations["workspace_presence"]:
        return {
            "status": "NEEDS_RECONCILIATION",
            "created_task": False,
            "reason": "workspace_presence observation is false; refusing to bind recovery state to an absent workspace",
        }

    task = manifest["task"]
    criteria = [str(item["text"]) for item in sorted(manifest["criteria"], key=lambda x: int(x["ordinal"]))]
    store = create_store(root)
    try:
        store.configure_task(
            store.path.parent.name,
            str(task["objective"]),
            criteria,
            profile=str(task.get("profile") or "regular"),
            requires_validation=bool(task.get("requires_validation", True)),
            no_validation_reason=task.get("no_validation_reason"),
            requires_clean_process_exit=bool(task.get("requires_clean_process_exit", False)),
        )
        store.set_meta("requires_objective_completion_audit", True)
        store.set_meta("workspace_binding", capture_workspace_binding(root))
        baseline_files = capture_baseline(root, store)

        expected_commit = manifest["workspace"].get("source_commit") or manifest["workspace"].get("base_commit")
        expected_tree = manifest["workspace"].get("source_tree") or manifest["workspace"].get("base_tree")
        observed_commit = observations.get("repository_head")
        observed_tree = observations.get("repository_tree")
        source_diverged = bool(
            (expected_commit and observed_commit is not None and observed_commit != expected_commit)
            or (expected_tree and observed_tree is not None and observed_tree != expected_tree)
        )
        missing_source_observations: list[str] = []
        if expected_commit and observed_commit is None:
            missing_source_observations.append("repository_head")
        if expected_tree and observed_tree is None:
            missing_source_observations.append("repository_tree")

        lookup = _observation_by_identity(observations)
        unresolved_external: list[dict[str, Any]] = []
        reconciled_external: list[dict[str, Any]] = []
        for old in manifest["external_actions"]:
            historical_state = str(old.get("state"))
            needs_reconcile = historical_state in _EXTERNAL_REQUIRES_RECONCILIATION or (
                historical_state == "terminal_failure" and not old.get("failure_resolved")
            )
            if not needs_reconcile:
                continue
            identity_hash = str(old.get("identity_sha256") or "")
            identity = f"resume-sha256:{identity_hash}"
            action_id = store.record_external(
                str(old["kind"]),
                "planned",
                identity if identity_hash else None,
                {"resume": True, "historical_state": historical_state},
                action_class=str(old["action_class"]),
            )
            store.record_external(
                str(old["kind"]), "dispatched", identity if identity_hash else None,
                {"resume": True, "historical_state": historical_state, "dispatch_is_historical": True},
                action_class=str(old["action_class"]), action_id=action_id,
            )
            observation = lookup.get((str(old["kind"]), identity_hash))
            if historical_state == "terminal_failure":
                store.record_external(
                    str(old["kind"]), "terminal_failure", identity if identity_hash else None,
                    {"resume": True, "historical_terminal_failure": True},
                    action_class=str(old["action_class"]), action_id=action_id,
                )
                if observation and observation["state"] == "terminal_success":
                    store.resolve_external_failure(action_id, observation["evidence"])
                    reconciled_external.append({"kind": old["kind"], "identity_sha256": identity_hash, "observed": "terminal_success", "resolution": "historical_failure_resolved"})
                elif observation and observation["state"] == "terminal_failure":
                    unresolved_external.append({"kind": old["kind"], "identity_sha256": identity_hash, "state": "terminal_failure"})
                else:
                    unresolved_external.append({"kind": old["kind"], "identity_sha256": identity_hash, "state": observation["state"] if observation else "missing_observation"})
                continue

            if observation:
                store.record_external(
                    str(old["kind"]), observation["state"], identity if identity_hash else None,
                    {"resume": True, "current_reality_evidence": observation["evidence"]},
                    action_class=str(old["action_class"]), action_id=action_id,
                )
                if observation["state"] in {"terminal_success", "terminal_failure"}:
                    reconciled_external.append({"kind": old["kind"], "identity_sha256": identity_hash, "observed": observation["state"]})
                if observation["state"] in {"outcome_unknown", "terminal_failure"}:
                    unresolved_external.append({"kind": old["kind"], "identity_sha256": identity_hash, "state": observation["state"]})
            else:
                unresolved_external.append({"kind": old["kind"], "identity_sha256": identity_hash, "state": "missing_observation"})

        lineage = {
            "resumed": True,
            "resume_source_manifest_sha256": _canonical_sha256(manifest),
            "resume_source_task": task.get("task_id"),
            "prior_generation": int(task.get("generation", 0)),
            "current_generation": 0,
            "resume_epoch": 1,
            "freshness_domain": "new_task",
        }
        store.set_meta("resume_lineage", lineage)
        store.set_meta("historical_recovery_evidence", {
            "criteria_statuses": [str(item.get("status")) for item in manifest["criteria"]],
            "historical": manifest["historical"],
            "validation": "HISTORICAL",
            "change_review": "HISTORICAL",
            "objective_audit": "HISTORICAL",
        })
        store.set_meta("resume_source_observation", {
            "expected_commit": expected_commit,
            "expected_tree": expected_tree,
            "observed_commit": observed_commit,
            "observed_tree": observed_tree,
            "source_diverged": source_diverged,
        })
        store.set_meta("resume_reconciliation", {
            "missing_source_observations": missing_source_observations,
            "unresolved_external": unresolved_external,
            "reconciled_external": reconciled_external,
        })
        set_active_task(root, store.task_id)
    except Exception:
        shutil.rmtree(store.path.parent, ignore_errors=True)
        raise

    if source_diverged:
        status = "SOURCE_DIVERGED"
    elif unresolved_external:
        status = "EXTERNAL_ACTION_UNRESOLVED"
    elif missing_source_observations:
        status = "NEEDS_RECONCILIATION"
    else:
        status = "RESUMED"
    return {
        "status": status,
        "created_task": True,
        "task_id": store.task_id,
        "state": str(store.path),
        "baseline_files": baseline_files,
        "lineage": lineage,
        "source_diverged": source_diverged,
        "missing_source_observations": missing_source_observations,
        "unresolved_external_actions": unresolved_external,
        "reconciled_external_actions": reconciled_external,
        "criteria_restored_as": "pending",
        "historical_evidence_restored_as": "HISTORICAL",
        "rule": "current reality wins; no persisted PASS/review/validation/audit becomes fresh automatically",
    }
