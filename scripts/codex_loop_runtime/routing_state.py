from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

ROUTING_SCHEMA_VERSION = 1
HOST_SURFACES = frozenset({"unknown", "chatgpt_web", "codex_local"})
WORKSPACE_MODES = frozenset({"web", "local"})
INTERACTION_TARGETS = frozenset({"none", "cloud_browser", "local_chrome", "local_mac_gui"})
DEPLOYMENT_TARGETS = frozenset({"artifact_only", "chatgpt_web_skill", "local_codex_skill"})
ROUTE_ACTIONS = frozenset({
    "repository_observe",
    "repository_mutate",
    "rdc_repository",
    "browser_interaction",
    "skill_install",
    "chatgpt_skill_install",
    "local_skill_install",
    "github_publish",
})
PERMISSION_OBSERVATION_SCHEMA_VERSION = 1
PERMISSION_OBSERVATION_DEFAULT_TTL_SECONDS = 1800
PERMISSION_OBSERVATION_MAX_TTL_SECONDS = 14400

PERMISSION_PROBE_CAPABILITIES = frozenset({
    "github_push",
    "github_actions",
    "google_drive_read",
    "google_drive_write",
})


def _session_id(raw: str | None, *, generate: bool = False) -> str | None:
    value = raw or os.environ.get("CODEX_LOOP_SESSION_ID")
    if value is None and generate:
        return secrets.token_urlsafe(24)
    if value is None:
        return None
    value = str(value).strip()
    if len(value) < 16 or len(value) > 256 or any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
        raise ValueError("routing session id must be 16-256 printable non-whitespace ASCII characters")
    return value


def _routing_root() -> Path:
    return Path(tempfile.gettempdir()) / "codex-loop" / "routing-sessions"


def _routing_path(session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return _routing_root() / f"{digest}.json"


def _ensure_private_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError(f"routing state parent is not a real directory: {path}")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError(f"routing state parent is not owned by current user: {path}")
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _check_private_regular_file(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"routing state is not a regular file: {path}")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError(f"routing state is not owned by current user: {path}")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
        raise PermissionError(f"routing state permissions are too broad: {path}")


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
            dir_fd = os.open(parent, os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _evidence_digest(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _native_deployment_target(host_surface: str) -> str | None:
    if host_surface == "chatgpt_web":
        return "chatgpt_web_skill"
    if host_surface == "codex_local":
        return "local_codex_skill"
    return None


def _default_state(host_surface: str) -> dict[str, Any]:
    if host_surface not in HOST_SURFACES:
        raise ValueError(f"host surface must be one of {sorted(HOST_SURFACES)}")
    return {
        "schema_version": ROUTING_SCHEMA_VERSION,
        "scope": "conversation",
        "host_surface": host_surface,
        "workspace_mode": "web",
        "workspace_basis": "new_conversation_default",
        "interaction_target": "none",
        "interaction_basis": "new_conversation_default",
        "deployment_target": None,
        "deployment_basis": "unresolved",
        "selection_evidence_sha256": {
            "workspace_mode": None,
            "interaction_target": None,
            "deployment_target": None,
        },
        "generation": 0,
    }


def _validate_state(payload: Any) -> dict[str, Any]:
    expected = {
        "schema_version",
        "scope",
        "host_surface",
        "workspace_mode",
        "workspace_basis",
        "interaction_target",
        "interaction_basis",
        "deployment_target",
        "deployment_basis",
        "selection_evidence_sha256",
        "generation",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ValueError("routing session state has an invalid schema")
    if payload.get("schema_version") != ROUTING_SCHEMA_VERSION or payload.get("scope") != "conversation":
        raise ValueError("routing session state has an unsupported version or scope")
    if payload.get("host_surface") not in HOST_SURFACES:
        raise ValueError("routing session state has an invalid host surface")
    if payload.get("workspace_mode") not in WORKSPACE_MODES:
        raise ValueError("routing session state has an invalid workspace mode")
    if payload.get("interaction_target") not in INTERACTION_TARGETS:
        raise ValueError("routing session state has an invalid interaction target")
    deployment_target = payload.get("deployment_target")
    if deployment_target is not None and deployment_target not in DEPLOYMENT_TARGETS:
        raise ValueError("routing session state has an invalid deployment target")
    evidence = payload.get("selection_evidence_sha256")
    if not isinstance(evidence, dict) or set(evidence) != {"workspace_mode", "interaction_target", "deployment_target"}:
        raise ValueError("routing session state has invalid selection evidence")
    for value in evidence.values():
        if value is not None and (not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)):
            raise ValueError("routing selection evidence digest is invalid")
    generation = payload.get("generation")
    if not isinstance(generation, int) or generation < 0:
        raise ValueError("routing session generation must be a non-negative integer")
    for key in ("workspace_basis", "interaction_basis", "deployment_basis"):
        if not isinstance(payload.get(key), str) or not payload[key]:
            raise ValueError(f"routing session {key} must be a non-empty string")
    return payload


def route_init(*, session_id: str | None = None, host_surface: str = "unknown") -> dict[str, Any]:
    sid = _session_id(session_id, generate=True)
    assert sid is not None
    path = _routing_path(sid)
    if path.exists() or path.is_symlink():
        state = route_show(session_id=sid)
        if host_surface != "unknown" and state["host_surface"] != host_surface:
            raise ValueError("routing session is already bound to a different host surface; start a new routing session")
        return {**state, "session_id": sid, "created": False}
    state = _default_state(host_surface)
    _atomic_json_write(path, state)
    return {**state, "session_id": sid, "state_path": str(path), "created": True}


def route_show(*, session_id: str | None = None) -> dict[str, Any]:
    sid = _session_id(session_id)
    if sid is None:
        raise ValueError("routing session id is required; run route-init first")
    path = _routing_path(sid)
    try:
        _check_private_regular_file(path)
    except FileNotFoundError as exc:
        raise FileNotFoundError("routing session state was not found; run route-init for this conversation") from exc
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("routing session state is invalid JSON and was not reset") from exc
    state = _validate_state(payload)
    return {**state, "session_id": sid, "state_path": str(path)}


def route_transition(
    *,
    session_id: str | None = None,
    workspace_mode: str | None = None,
    interaction_target: str | None = None,
    deployment_target: str | None = None,
    selection_evidence: str | None = None,
) -> dict[str, Any]:
    current = route_show(session_id=session_id)
    sid = current["session_id"]
    state = {key: value for key, value in current.items() if key not in {"session_id", "state_path"}}
    changed: list[str] = []
    digest = _evidence_digest(selection_evidence)

    if workspace_mode is not None:
        if workspace_mode not in WORKSPACE_MODES:
            raise ValueError(f"workspace mode must be one of {sorted(WORKSPACE_MODES)}")
        if workspace_mode == "local" and digest is None:
            raise PermissionError("entering local workspace mode requires explicit current-conversation user selection evidence")
        if workspace_mode != state["workspace_mode"]:
            state["workspace_mode"] = workspace_mode
            state["workspace_basis"] = "explicit_user_local_workspace" if workspace_mode == "local" else "explicit_web_selection"
            state["selection_evidence_sha256"]["workspace_mode"] = digest
            changed.append("workspace_mode")

    if interaction_target is not None:
        if interaction_target not in INTERACTION_TARGETS:
            raise ValueError(f"interaction target must be one of {sorted(INTERACTION_TARGETS)}")
        if interaction_target in {"local_chrome", "local_mac_gui"} and digest is None:
            raise PermissionError("selecting a local interaction target requires explicit current-task user selection evidence")
        if interaction_target != state["interaction_target"]:
            state["interaction_target"] = interaction_target
            state["interaction_basis"] = "explicit_user_local_interaction" if interaction_target.startswith("local_") else "safe_remote_selection"
            state["selection_evidence_sha256"]["interaction_target"] = digest
            changed.append("interaction_target")

    if deployment_target is not None:
        normalized_target = None if deployment_target == "none" else deployment_target
        if normalized_target is not None and normalized_target not in DEPLOYMENT_TARGETS:
            raise ValueError(f"deployment target must be one of {sorted(DEPLOYMENT_TARGETS | {'none'})}")
        native_target = _native_deployment_target(state["host_surface"])
        cross_surface = normalized_target is not None and normalized_target not in {"artifact_only", native_target}
        if cross_surface and digest is None:
            raise PermissionError("selecting a non-native deployment target requires explicit current-task user selection evidence")
        if normalized_target != state["deployment_target"]:
            state["deployment_target"] = normalized_target
            if normalized_target is None:
                state["deployment_basis"] = "unresolved"
            elif normalized_target == "artifact_only":
                state["deployment_basis"] = "artifact_only"
            elif digest is not None:
                state["deployment_basis"] = "explicit_user_target"
            else:
                state["deployment_basis"] = "host_surface_native_default"
            state["selection_evidence_sha256"]["deployment_target"] = digest
            changed.append("deployment_target")

    if not changed:
        return {**current, "changed": []}
    state["generation"] = int(state["generation"]) + 1
    _atomic_json_write(_routing_path(sid), _validate_state(state))
    return {**route_show(session_id=sid), "changed": changed}


def _deployment_resolution(state: dict[str, Any]) -> tuple[str | None, str]:
    explicit = state.get("deployment_target")
    if explicit is not None:
        return str(explicit), str(state.get("deployment_basis") or "session_state")
    native = _native_deployment_target(str(state["host_surface"]))
    if native is not None:
        return native, "host_surface_native_default"
    return None, "unresolved"


def route_check(
    *,
    action: str,
    session_id: str | None = None,
    workspace_granted: bool = False,
    local_source_mutation_authorized: bool = False,
    local_computer_authorized: bool = False,
    local_install_authorized: bool = False,
) -> dict[str, Any]:
    if action not in ROUTE_ACTIONS:
        raise ValueError(f"route action must be one of {sorted(ROUTE_ACTIONS)}")
    state = route_show(session_id=session_id)
    result: dict[str, Any] = {
        "action": action,
        "allowed": False,
        "workspace_mode": state["workspace_mode"],
        "interaction_target": state["interaction_target"],
        "deployment_target": state["deployment_target"],
        "host_surface": state["host_surface"],
        "generation": state["generation"],
        "requirements": [],
    }

    if action in {"repository_observe", "repository_mutate", "rdc_repository", "github_publish"}:
        if action == "rdc_repository" and state["workspace_mode"] != "local":
            result.update({
                "rule": "RDC availability cannot select Local mode; repository access remains Web-routed until explicit local workspace selection is recorded",
                "effective_workspace": "web",
            })
            return result
        if state["workspace_mode"] == "web":
            result.update({"allowed": True, "effective_workspace": "web"})
            if action == "github_publish":
                result["publish_transport"] = "verified_web_mode"
            return result
        missing: list[str] = []
        if not workspace_granted:
            missing.append("current_conversation_workspace_grant")
        if action == "repository_mutate" and not local_source_mutation_authorized:
            missing.append("current_task_local_source_mutation_authorization")
        if missing:
            result.update({"requirements": missing, "effective_workspace": "local"})
            return result
        result.update({"allowed": True, "effective_workspace": "local"})
        if action == "github_publish":
            result["publish_transport"] = "verified_native_git"
        return result

    if action == "browser_interaction":
        target = state["interaction_target"]
        if target == "none":
            target = "cloud_browser"
            source = "safe_default"
        else:
            source = state["interaction_basis"]
        result.update({"effective_interaction_target": target, "interaction_source": source})
        if target in {"local_chrome", "local_mac_gui"} and not local_computer_authorized:
            result["requirements"] = ["current_task_local_computer_use_authorization"]
            return result
        result["allowed"] = True
        return result

    target, source = _deployment_resolution(state)
    result.update({"effective_deployment_target": target, "deployment_source": source})
    if target is None:
        result.update({
            "rule": "deployment target is unresolved; a generic install must not guess a local machine from prior context or tool availability",
            "requirements": ["host_surface_or_explicit_deployment_target"],
        })
        return result
    if action == "chatgpt_skill_install" and target != "chatgpt_web_skill":
        result["rule"] = "requested ChatGPT Web Skill installation conflicts with the deterministic deployment target"
        return result
    if action == "local_skill_install" and target != "local_codex_skill":
        result["rule"] = "local Codex installation is not the deterministic deployment target"
        return result
    if target == "artifact_only":
        result["rule"] = "artifact_only permits packaging but not installation"
        return result
    if target == "local_codex_skill" and not local_install_authorized:
        result["requirements"] = ["current_task_explicit_local_skill_install_authorization"]
        result["rule"] = "a local Skill target never turns prior context or RDC availability into current-task install authorization"
        return result
    result["allowed"] = True
    result["local_codex_auto_selected"] = False if state["host_surface"] == "chatgpt_web" else target == "local_codex_skill" and source == "host_surface_native_default"
    return result



def _permission_observation_path(session_id: str) -> Path:
    return _routing_path(session_id).with_suffix(".capabilities.json")


def _permission_observation_state(session_id: str) -> dict[str, Any]:
    path = _permission_observation_path(session_id)
    if not path.exists() and not path.is_symlink():
        return {"schema_version": PERMISSION_OBSERVATION_SCHEMA_VERSION, "observations": {}}
    _check_private_regular_file(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("permission observation state is invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PERMISSION_OBSERVATION_SCHEMA_VERSION or not isinstance(payload.get("observations"), dict):
        raise ValueError("permission observation state has an invalid schema")
    return payload


def _observation_scope_digest(scope: str) -> str:
    value = str(scope).strip()
    if not value or len(value) > 1024:
        raise ValueError("permission observation scope must be 1-1024 non-whitespace characters")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def record_permission_observation(*, session_id: str, capability: str, scope: str, evidence: str,
                                  ttl_seconds: int = PERMISSION_OBSERVATION_DEFAULT_TTL_SECONDS,
                                  now: int | None = None) -> dict[str, Any]:
    """Record a bounded host observation. This is never an authorization grant."""
    if capability not in PERMISSION_PROBE_CAPABILITIES:
        raise ValueError(f"permission observation capability must be one of {sorted(PERMISSION_PROBE_CAPABILITIES)}")
    ttl = int(ttl_seconds)
    if ttl < 1 or ttl > PERMISSION_OBSERVATION_MAX_TTL_SECONDS:
        raise ValueError(f"permission observation ttl must be 1-{PERMISSION_OBSERVATION_MAX_TTL_SECONDS} seconds")
    route = route_show(session_id=session_id)
    evidence_sha = _evidence_digest(evidence)
    if evidence_sha is None:
        raise ValueError("permission observation requires concise host-observed evidence")
    scope_sha = _observation_scope_digest(scope)
    observed_at = int(time.time() if now is None else now)
    key = f"{capability}:{scope_sha}"
    state = _permission_observation_state(route["session_id"])
    state["observations"][key] = {
        "capability": capability,
        "scope_sha256": scope_sha,
        "evidence_sha256": evidence_sha,
        "observed_at": observed_at,
        "expires_at": observed_at + ttl,
        "routing_generation": int(route["generation"]),
        "host_surface": route["host_surface"],
        "workspace_mode": route["workspace_mode"],
    }
    _atomic_json_write(_permission_observation_path(route["session_id"]), state)
    return {**state["observations"][key], "fresh": True, "scope": "sha256:" + scope_sha,
            "authority": "host_observation_only_not_authorization"}


def permission_observation_status(*, session_id: str, capability: str, scope: str,
                                  now: int | None = None) -> dict[str, Any]:
    if capability not in PERMISSION_PROBE_CAPABILITIES:
        raise ValueError(f"permission observation capability must be one of {sorted(PERMISSION_PROBE_CAPABILITIES)}")
    route = route_show(session_id=session_id)
    scope_sha = _observation_scope_digest(scope)
    key = f"{capability}:{scope_sha}"
    item = _permission_observation_state(route["session_id"])["observations"].get(key)
    if not isinstance(item, dict):
        return {"capability": capability, "scope": "sha256:" + scope_sha, "fresh": False,
                "reason": "no_current_session_observation", "authority": "host_observation_only_not_authorization"}
    current_time = int(time.time() if now is None else now)
    reasons=[]
    if int(item.get("routing_generation", -1)) != int(route["generation"]): reasons.append("routing_generation_changed")
    if item.get("host_surface") != route["host_surface"]: reasons.append("host_surface_changed")
    if item.get("workspace_mode") != route["workspace_mode"]: reasons.append("workspace_mode_changed")
    if current_time >= int(item.get("expires_at", 0)): reasons.append("observation_expired")
    return {**item, "scope": "sha256:" + scope_sha, "fresh": not reasons,
            "reason": None if not reasons else ",".join(reasons), "authority": "host_observation_only_not_authorization"}

def permission_preflight_plan(
    *,
    capabilities: list[str] | tuple[str, ...],
    session_id: str | None = None,
    observation_scopes: dict[str, str] | None = None,
    reuse_fresh_observations: bool = False,
) -> dict[str, Any]:
    """Return only live probes still needed after scoped current-session observation reuse."""
    requested: list[str] = []
    for raw in capabilities:
        capability = str(raw).strip()
        if capability not in PERMISSION_PROBE_CAPABILITIES:
            raise ValueError(f"permission probe capability must be one of {sorted(PERMISSION_PROBE_CAPABILITIES)}")
        if capability not in requested:
            requested.append(capability)
    if not requested:
        raise ValueError("at least one permission probe capability is required")
    if "github_push" in requested and session_id is None:
        raise ValueError("github_push permission probing requires a routing session so Web versus Local publication is not guessed")

    route = route_show(session_id=session_id) if session_id is not None else None
    workspace_mode = route.get("workspace_mode") if route else None
    probes: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    scopes = observation_scopes or {}

    for capability in requested:
        scope = str(scopes.get(capability) or "").strip()
        if reuse_fresh_observations and session_id is not None and scope:
            status = permission_observation_status(session_id=session_id, capability=capability, scope=scope)
            if status.get("fresh"):
                reused.append(status)
                continue
        if capability == "github_push":
            if workspace_mode == "local":
                preferred = (
                    "From the canonical authorized worktree, run host-visible native Git `git push --dry-run` "
                    "to the intended remote/ref. The dry run must not create or move a ref."
                )
                evidence = "host-visible dry-run reaches the remote and reports a push-capable result without ref mutation"
                side_effect_budget = "none"
            else:
                preferred = (
                    "Read live permissions for the exact target repository and require push-capable access, then invoke a "
                    "GitHub Git-database blob/write-object primitive with fixed empty content. The probe object must remain "
                    "unreferenced: do not create a tree, commit, tag, branch, or ref. This reaches repository contents-write "
                    "scope without moving refs or changing source. If the host exposes no isolated unreferenced object-write "
                    "primitive, do not manufacture a source/ref mutation; report the safe probe as unavailable."
                )
                evidence = "push-capable repository access is observed and the host accepts an unreferenced empty-blob write without any tree/commit/ref mutation"
                side_effect_budget = "one unreferenced empty Git blob object; no tree/commit/ref or source mutation"
            probes.append({
                "capability": capability,
                "probe_kind": "live_host_permission_probe",
                "preferred_probe": preferred,
                "success_evidence": evidence,
                "cleanup_required": False,
                "side_effect_budget": side_effect_budget,
                "failure_classification": "GITHUB_PUSH_PERMISSION_NOT_PROVEN",
            })
        elif capability == "github_actions":
            probes.append({
                "capability": capability,
                "probe_kind": "live_host_write_scope_probe",
                "preferred_probe": (
                    "Invoke a write-scoped GitHub Actions operation only against an audited workflow/job that cannot "
                    "mutate repository source or refs (dispatch/rerun is acceptable when the workflow is source-read-only). "
                    "For Codex Loop, Workspace Download is an acceptable probe; Workspace Import is not."
                ),
                "success_evidence": "host accepts the Actions write-scoped call and the audited no-source-write run is observable",
                "cleanup_required": False,
                "side_effect_budget": "one bounded workflow run; no source/ref mutation",
                "failure_classification": "GITHUB_ACTIONS_PERMISSION_NOT_PROVEN",
            })
        elif capability == "google_drive_read":
            probes.append({
                "capability": capability,
                "probe_kind": "live_host_read_probe",
                "preferred_probe": "List/search metadata in the exact Drive scope needed by the workflow; do not open unrelated user files.",
                "success_evidence": "the intended Drive scope is readable through the live connector",
                "cleanup_required": False,
                "side_effect_budget": "none",
                "failure_classification": "GOOGLE_DRIVE_READ_PERMISSION_NOT_PROVEN",
            })
        elif capability == "google_drive_write":
            probes.append({
                "capability": capability,
                "probe_kind": "live_host_write_cleanup_probe",
                "preferred_probe": (
                    "Create one uniquely named, non-sensitive Drive sentinel owned by this preflight, read back its ID/metadata, "
                    "then delete that exact sentinel immediately. Never use a pre-existing user file as the write probe."
                ),
                "success_evidence": "sentinel creation/readback succeeds and the exact sentinel is deleted",
                "cleanup_required": True,
                "side_effect_budget": "one temporary owned sentinel only",
                "failure_classification": "GOOGLE_DRIVE_WRITE_PERMISSION_NOT_PROVEN",
            })

    return {
        "phase": "post_task_review_pre_execution",
        "required_capabilities": requested,
        "reused_capabilities": [item["capability"] for item in reused],
        "reused_observations": reused,
        "probe_capabilities": [item["capability"] for item in probes],
        "routing_generation": route.get("generation") if route else None,
        "workspace_mode": workspace_mode,
        "probes": probes,
        "completion_rule": (
            "A permission smoke test is complete only after each required capability has a current live host observation. "
            "Tool/schema discovery, connector-listed status, cached prose, or a capability boolean alone is not probe evidence."
        ),
        "authority_rule": (
            "Probe results are host observations, not grants. Reuse them only while still live in the current task/session; "
            "never persist OAuth tokens, approvals, or a claim of permanent authorization, and never bypass per-action host approval."
        ),
        "runtime_state_written": False,
        "session_observation_state_read": bool(reuse_fresh_observations and session_id is not None),
    }
