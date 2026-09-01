from __future__ import annotations

import copy
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from .workspace_registry import host_config_path

HOST_CONFIG_SCHEMA_VERSION = 2
HOST_CONFIG_MAX_BYTES = 64 * 1024
PROGRESS_MODES = frozenset({"quiet", "standard", "enhanced"})
BROWSER_TARGETS = frozenset({"cloud_browser", "local_chrome"})
TASK_PERSISTENCE_BACKENDS = frozenset({"off", "google_drive"})
PROFILE_PERSISTENCE_BACKENDS = frozenset({"local_only", "google_drive"})

DEFAULT_PROGRESS_CONFIG: dict[str, Any] = {
    "mode": "enhanced",
    "interval_seconds": 15,
    "tool_call_interval": 3,
    "upfront_plan": True,
    "material_event_updates": True,
}
DEFAULT_HOST_PROFILE: dict[str, Any] = {
    "schema_version": HOST_CONFIG_SCHEMA_VERSION,
    "progress_visibility": dict(DEFAULT_PROGRESS_CONFIG),
    "browser": {
        "preferred_target": "cloud_browser",
        "allow_local_chrome_fallback": False,
    },
    "web_publish": {
        "provider": "google_drive",
        "staging_folder_id": None,
    },
    "workspace": {
        "default_local_workspace": None,
    },
    "persistence": {
        "task_backend": "off",
        "host_profile_backend": "local_only",
    },
}
_TOP_LEVEL_KEYS = frozenset(DEFAULT_HOST_PROFILE) | {"default_local_root"}
_SECTION_KEYS = {
    "progress_visibility": frozenset(DEFAULT_PROGRESS_CONFIG),
    "browser": frozenset(DEFAULT_HOST_PROFILE["browser"]),
    "web_publish": frozenset(DEFAULT_HOST_PROFILE["web_publish"]),
    "workspace": frozenset(DEFAULT_HOST_PROFILE["workspace"]),
    "persistence": frozenset(DEFAULT_HOST_PROFILE["persistence"]),
}
_LEAF_PATHS = {
    f"{section}.{key}"
    for section, keys in _SECTION_KEYS.items()
    for key in keys
}


def _check_private_regular_file(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"host-local Codex Loop config is not a regular file: {path}")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError(f"host-local Codex Loop config is not owned by current user: {path}")
    if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
        raise PermissionError(f"host-local Codex Loop config permissions must not grant group/other access: {path}")
    if info.st_size > HOST_CONFIG_MAX_BYTES:
        raise ValueError(f"host-local Codex Loop config exceeds {HOST_CONFIG_MAX_BYTES} bytes: {path}")


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


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    parent = _ensure_private_dir(path.parent)
    if path.exists() or path.is_symlink():
        _check_private_regular_file(path)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if len(encoded) > HOST_CONFIG_MAX_BYTES:
        raise ValueError("host config write exceeds size bound")
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
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


def _validate_progress(raw: Any) -> dict[str, Any]:
    if raw is None:
        return dict(DEFAULT_PROGRESS_CONFIG)
    if not isinstance(raw, dict):
        raise ValueError("progress_visibility must be a JSON object")
    unexpected = set(raw) - _SECTION_KEYS["progress_visibility"]
    if unexpected:
        raise ValueError(f"progress_visibility has unsupported keys: {sorted(unexpected)}")
    result = dict(DEFAULT_PROGRESS_CONFIG)
    result.update(raw)
    if result["mode"] not in PROGRESS_MODES:
        raise ValueError(f"progress_visibility.mode must be one of {sorted(PROGRESS_MODES)}")
    interval = result["interval_seconds"]
    if isinstance(interval, bool) or not isinstance(interval, int) or not 5 <= interval <= 120:
        raise ValueError("progress_visibility.interval_seconds must be an integer from 5 to 120")
    tool_calls = result["tool_call_interval"]
    if isinstance(tool_calls, bool) or not isinstance(tool_calls, int) or not 1 <= tool_calls <= 20:
        raise ValueError("progress_visibility.tool_call_interval must be an integer from 1 to 20")
    for key in ("upfront_plan", "material_event_updates"):
        if not isinstance(result[key], bool):
            raise ValueError(f"progress_visibility.{key} must be boolean")
    return result


def _validate_section(section: str, raw: Any) -> dict[str, Any]:
    default = DEFAULT_HOST_PROFILE[section]
    if raw is None:
        return copy.deepcopy(default)
    if not isinstance(raw, dict):
        raise ValueError(f"{section} must be a JSON object")
    unexpected = set(raw) - _SECTION_KEYS[section]
    if unexpected:
        raise ValueError(f"{section} has unsupported keys: {sorted(unexpected)}")
    result = copy.deepcopy(default)
    result.update(raw)
    if section == "browser":
        if result["preferred_target"] not in BROWSER_TARGETS:
            raise ValueError(f"browser.preferred_target must be one of {sorted(BROWSER_TARGETS)}")
        if not isinstance(result["allow_local_chrome_fallback"], bool):
            raise ValueError("browser.allow_local_chrome_fallback must be boolean")
    elif section == "web_publish":
        if result["provider"] != "google_drive":
            raise ValueError("web_publish.provider currently supports only google_drive")
        folder = result["staging_folder_id"]
        if folder is not None and (not isinstance(folder, str) or not folder.strip() or len(folder) > 512):
            raise ValueError("web_publish.staging_folder_id must be null or a bounded non-empty string")
    elif section == "workspace":
        alias = result["default_local_workspace"]
        if alias is not None and (not isinstance(alias, str) or not alias.strip() or len(alias) > 128):
            raise ValueError("workspace.default_local_workspace must be null or a bounded non-empty alias")
    elif section == "persistence":
        if result["task_backend"] not in TASK_PERSISTENCE_BACKENDS:
            raise ValueError(f"persistence.task_backend must be one of {sorted(TASK_PERSISTENCE_BACKENDS)}")
        if result["host_profile_backend"] not in PROFILE_PERSISTENCE_BACKENDS:
            raise ValueError(f"persistence.host_profile_backend must be one of {sorted(PROFILE_PERSISTENCE_BACKENDS)}")
    return result


def _migrate_v1(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    allowed = {"schema_version", "default_local_workspace", "default_local_root", "progress_visibility"}
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ValueError(f"legacy host config contains unsupported keys: {extra}")
    migrated: dict[str, Any] = {"schema_version": HOST_CONFIG_SCHEMA_VERSION}
    if "progress_visibility" in raw:
        migrated["progress_visibility"] = raw["progress_visibility"]
    if "default_local_workspace" in raw:
        migrated["workspace"] = {"default_local_workspace": raw.get("default_local_workspace")}
    if "default_local_root" in raw:
        root = raw.get("default_local_root")
        if root is not None and not isinstance(root, str):
            raise ValueError("legacy default_local_root must be a string or null")
        migrated["default_local_root"] = root
    return migrated, ["host_config_schema_v1_migrated_in_memory"]


def _validate_raw_v2(raw: dict[str, Any]) -> dict[str, Any]:
    extra = sorted(set(raw) - _TOP_LEVEL_KEYS)
    if extra:
        raise ValueError(f"host config contains unsupported top-level keys: {extra}")
    if raw.get("schema_version") != HOST_CONFIG_SCHEMA_VERSION:
        raise ValueError(f"unsupported host config schema_version: {raw.get('schema_version')!r}")
    for section in _SECTION_KEYS:
        if section in raw:
            if section == "progress_visibility":
                _validate_progress(raw[section])
            else:
                _validate_section(section, raw[section])
    legacy_root = raw.get("default_local_root")
    if legacy_root is not None and not isinstance(legacy_root, str):
        raise ValueError("default_local_root compatibility input must be a string or null")
    return raw


def _load_raw_host_config(*, strict: bool) -> tuple[dict[str, Any], list[str], bool]:
    path = host_config_path()
    try:
        _check_private_regular_file(path)
    except FileNotFoundError:
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, [], False
    except (OSError, RuntimeError, PermissionError, ValueError) as exc:
        if strict:
            raise
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, [f"unsafe_host_config_using_defaults:{type(exc).__name__}"], True
    try:
        payload = path.read_bytes()
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if strict:
            raise RuntimeError(f"host config is invalid and was not overwritten: {path}") from exc
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, ["invalid_host_config_json_using_defaults"], True
    except OSError:
        if strict:
            raise
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, ["unreadable_host_config_using_defaults"], True
    if not isinstance(raw, dict):
        if strict:
            raise ValueError("host config must be a JSON object")
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, ["invalid_host_config_object_using_defaults"], True
    try:
        version = raw.get("schema_version", 1)
        if version == 1:
            migrated, warnings = _migrate_v1(raw)
            _validate_raw_v2(migrated)
            return migrated, warnings, True
        _validate_raw_v2(raw)
        return dict(raw), [], True
    except (ValueError, TypeError) as exc:
        if strict:
            raise
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, [f"invalid_host_config_using_defaults:{exc}"], True


def effective_host_profile() -> dict[str, Any]:
    raw, warnings, file_exists = _load_raw_host_config(strict=False)
    profile = copy.deepcopy(DEFAULT_HOST_PROFILE)
    try:
        profile["progress_visibility"] = _validate_progress(raw.get("progress_visibility"))
        for section in ("browser", "web_publish", "workspace", "persistence"):
            profile[section] = _validate_section(section, raw.get(section))
    except ValueError as exc:
        profile = copy.deepcopy(DEFAULT_HOST_PROFILE)
        warnings = [*warnings, f"invalid_host_profile_using_defaults:{exc}"]
    return {
        **profile,
        "config_path": str(host_config_path()),
        "config_file_exists": file_exists,
        "source": "host_file" if file_exists and not warnings else "default",
        "warnings": warnings,
        "repository_persisted": False,
        "authorization_persisted": False,
        "capability_state_persisted": False,
    }


def _write_raw_profile(raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(raw)
    raw["schema_version"] = HOST_CONFIG_SCHEMA_VERSION
    _validate_raw_v2(raw)
    _atomic_json_write(host_config_path(), raw)


def host_config_show() -> dict[str, Any]:
    return effective_host_profile()


def _leaf_parts(path: str) -> tuple[str, str]:
    if path not in _LEAF_PATHS:
        raise ValueError(f"unsupported host config path: {path}")
    section, key = path.split(".", 1)
    return section, key


def host_config_get(path: str) -> Any:
    section, key = _leaf_parts(path)
    return effective_host_profile()[section][key]


def host_config_set(path: str, value: Any) -> dict[str, Any]:
    section, key = _leaf_parts(path)
    raw, _warnings, _exists = _load_raw_host_config(strict=True)
    current = raw.get(section)
    if current is None:
        current = {}
    if not isinstance(current, dict):
        raise ValueError(f"{section} must be an object")
    updated = dict(current)
    updated[key] = value
    if section == "progress_visibility":
        validated = _validate_progress(updated)
    else:
        validated = _validate_section(section, updated)
    raw[section] = {k: validated[k] for k in _SECTION_KEYS[section]}
    _write_raw_profile(raw)
    result = effective_host_profile()
    result["saved"] = True
    result["updated_path"] = path
    return result


def host_config_unset(path: str) -> dict[str, Any]:
    section, key = _leaf_parts(path)
    raw, _warnings, _exists = _load_raw_host_config(strict=True)
    current = raw.get(section)
    if isinstance(current, dict):
        updated = dict(current)
        updated.pop(key, None)
        if updated:
            raw[section] = updated
        else:
            raw.pop(section, None)
    _write_raw_profile(raw)
    result = effective_host_profile()
    result["saved"] = True
    result["unset_path"] = path
    return result


def host_config_reset(section: str) -> dict[str, Any]:
    if section not in _SECTION_KEYS:
        raise ValueError(f"unsupported host config section: {section}")
    raw, _warnings, _exists = _load_raw_host_config(strict=True)
    raw.pop(section, None)
    _write_raw_profile(raw)
    result = effective_host_profile()
    result["saved"] = True
    result["reset_section"] = section
    return result


def effective_progress_config() -> dict[str, Any]:
    profile = effective_host_profile()
    return {
        **profile["progress_visibility"],
        "config_path": profile["config_path"],
        "config_file_exists": profile["config_file_exists"],
        "source": profile["source"],
        "warnings": profile["warnings"],
        "repository_persisted": False,
    }


def set_progress_config(
    *,
    mode: str | None = None,
    interval_seconds: int | None = None,
    tool_call_interval: int | None = None,
    upfront_plan: bool | None = None,
    material_event_updates: bool | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    raw, _warnings, _file_exists = _load_raw_host_config(strict=True)
    if reset:
        raw.pop("progress_visibility", None)
    else:
        current = _validate_progress(raw.get("progress_visibility"))
        updates = {
            "mode": mode,
            "interval_seconds": interval_seconds,
            "tool_call_interval": tool_call_interval,
            "upfront_plan": upfront_plan,
            "material_event_updates": material_event_updates,
        }
        for key, value in updates.items():
            if value is not None:
                current[key] = value
        raw["progress_visibility"] = _validate_progress(current)
    _write_raw_profile(raw)
    result = effective_progress_config()
    result["saved"] = True
    result["reset_to_defaults"] = bool(reset)
    return result


def progress_policy(lifecycle_mode: str) -> dict[str, Any]:
    if lifecycle_mode not in {"direct", "durable"}:
        raise ValueError("lifecycle_mode must be direct or durable")
    config = effective_progress_config()
    if lifecycle_mode == "direct":
        return {
            "lifecycle_mode": "direct",
            "visibility_mode": "low_noise",
            "periodic_updates": False,
            "emit_upfront_plan": False,
            "material_event_updates": bool(config["material_event_updates"]),
            "config": config,
            "instruction": "Keep trivial/direct work concise; do not add periodic progress messages.",
        }
    mode = str(config["mode"])
    if mode == "quiet":
        return {
            "lifecycle_mode": "durable",
            "visibility_mode": "quiet",
            "periodic_updates": False,
            "emit_upfront_plan": False,
            "material_event_updates": bool(config["material_event_updates"]),
            "config": config,
            "instruction": "Suppress routine progress messages; still surface material findings or blockers when configured or required.",
        }
    if mode == "standard":
        return {
            "lifecycle_mode": "durable",
            "visibility_mode": "standard",
            "periodic_updates": "host_default",
            "emit_upfront_plan": bool(config["upfront_plan"]),
            "material_event_updates": bool(config["material_event_updates"]),
            "config": config,
            "instruction": "Use the host's normal progress cadence while keeping updates concise and material.",
        }
    return {
        "lifecycle_mode": "durable",
        "visibility_mode": "enhanced",
        "periodic_updates": True,
        "interval_seconds": int(config["interval_seconds"]),
        "tool_call_interval": int(config["tool_call_interval"]),
        "emit_upfront_plan": bool(config["upfront_plan"]),
        "material_event_updates": bool(config["material_event_updates"]),
        "config": config,
        "instruction": (
            "Emit concise progress updates during substantive work after whichever occurs first: approximately "
            f"{config['interval_seconds']} seconds or {config['tool_call_interval']} substantive tool calls; "
            "surface material findings/blockers immediately when enabled."
        ),
    }
