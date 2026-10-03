from __future__ import annotations

import copy
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any

from .workspace_registry import host_config_path

HOST_CONFIG_SCHEMA_VERSION = 4
HOST_CONFIG_MAX_BYTES = 64 * 1024
PROGRESS_MODES = frozenset({"quiet", "standard", "enhanced"})
BROWSER_TARGETS = frozenset({"cloud_browser", "local_chrome"})
TASK_PERSISTENCE_BACKENDS = frozenset({"off", "google_drive"})
PROFILE_PERSISTENCE_BACKENDS = frozenset({"auto", "local_only", "google_drive"})
DRIVE_CACHE_MAX_FOLDERS = 64

DEFAULT_PROGRESS_CONFIG: dict[str, Any] = {
    "mode": "standard",
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
        "environments": {},
    },
    "execution": {
        "default_target": "web",
        "connections": [],
    },
    "interaction": {"language": "follow_user"},
    "drive": {
        "cache_folder_paths": [],
    },
    "persistence": {
        "task_backend": "off",
        "host_profile_backend": "auto",
    },
}
_TOP_LEVEL_KEYS = frozenset(DEFAULT_HOST_PROFILE)
_SECTION_KEYS = {
    "progress_visibility": frozenset(DEFAULT_PROGRESS_CONFIG),
    "browser": frozenset(DEFAULT_HOST_PROFILE["browser"]),
    "web_publish": frozenset(DEFAULT_HOST_PROFILE["web_publish"]),
    "workspace": frozenset(DEFAULT_HOST_PROFILE["workspace"]),
    "execution": frozenset(DEFAULT_HOST_PROFILE["execution"]),
    "interaction": frozenset(DEFAULT_HOST_PROFILE["interaction"]),
    "drive": frozenset(DEFAULT_HOST_PROFILE["drive"]),
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
        environments = result["environments"]
        if not isinstance(environments, dict) or len(environments) > 64:
            raise ValueError("workspace.environments must be an object of at most 64 execution environments")
        result["environments"] = {}
        for name, locations in environments.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", name) or name in {"web", "local"}:
                raise ValueError("workspace environment must be a non-reserved lowercase identifier")
            result["environments"][name] = validate_environment_locations(locations)
    elif section == "interaction":
        language = result["language"]
        if not isinstance(language, str) or not language.strip() or len(language) > 128 or any(ord(c) < 32 for c in language):
            raise ValueError("interaction.language must be follow_user or a bounded printable language name")
    elif section == "execution":
        target = result["default_target"]
        identifier = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
        if not isinstance(target, str) or not identifier.fullmatch(target):
            raise ValueError("execution.default_target must be web, local, or a computer identifier")
        connections = result["connections"]
        if not isinstance(connections, list) or len(connections) > 64:
            raise ValueError("execution.connections must be an ordered array of at most 64 connections")
        names = set()
        computers = set()
        for item in connections:
            required = {"name", "computer", "connector", "kind"}
            if not isinstance(item, dict) or not required <= set(item) or set(item) != required:
                raise ValueError("each execution connection supports only name, computer, connector, kind; paths belong to workspace.environments")
            for key in ("name", "computer"):
                if not isinstance(item[key], str) or not identifier.fullmatch(item[key]):
                    raise ValueError(f"execution connection {key} must be a bounded lowercase identifier")
            if item["computer"] in {"web", "local"} or item["name"] in names or item["name"] == "rdc":
                raise ValueError("execution connections require unique names (rdc is reserved) and non-reserved computer identifiers")
            names.add(item["name"])
            computers.add(item["computer"])
            if not isinstance(item["kind"], str) or item["kind"] not in {"mcp", "rdc"}:
                raise ValueError("execution connection kind must be mcp or rdc")
            connector = item["connector"]
            if not isinstance(connector, str) or not connector.strip() or len(connector) > 512 or any(ord(c) < 32 for c in connector):
                raise ValueError("execution connector must be a bounded printable name or connector ID, never a URL or credential")
            if "://" in connector or connector.startswith("sk-"):
                raise ValueError("execution connector must not contain an endpoint URL or API key")
        if target not in {"web", "local"} and target not in computers:
            raise ValueError("execution.default_target must identify a configured computer")
    elif section == "drive":
        paths = result["cache_folder_paths"]
        if not isinstance(paths, list):
            raise ValueError("drive.cache_folder_paths must be a JSON array")
        if len(paths) > DRIVE_CACHE_MAX_FOLDERS:
            raise ValueError(f"drive.cache_folder_paths may contain at most {DRIVE_CACHE_MAX_FOLDERS} entries")
        normalized = []
        seen = set()
        for raw_path in paths:
            if not isinstance(raw_path, str):
                raise ValueError("drive.cache_folder_paths entries must be strings")
            value = raw_path.strip().replace("\\", "/")
            if not value or len(value) > 1024 or any(ord(ch) < 32 for ch in value):
                raise ValueError("drive.cache_folder_paths entries must be bounded non-empty printable strings")
            parts = [part for part in value.split("/") if part]
            if not parts or any(part in {".", ".."} for part in parts):
                raise ValueError("drive.cache_folder_paths entries must be canonical relative Drive paths")
            value = "/".join(parts)
            if value not in seen:
                seen.add(value)
                normalized.append(value)
        result["cache_folder_paths"] = normalized
    elif section == "persistence":
        if result["task_backend"] not in TASK_PERSISTENCE_BACKENDS:
            raise ValueError(f"persistence.task_backend must be one of {sorted(TASK_PERSISTENCE_BACKENDS)}")
        if result["host_profile_backend"] not in PROFILE_PERSISTENCE_BACKENDS:
            raise ValueError(f"persistence.host_profile_backend must be one of {sorted(PROFILE_PERSISTENCE_BACKENDS)}")
    return result


def validate_absolute_locator(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value) or not (value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value)):
        raise ValueError(f"{label} must be an absolute POSIX or Windows path")
    return value


def validate_environment_locations(raw: Any) -> dict[str, Any]:
    defaults = {"default_root": None, "projects": {}, "runtime_directory": None, "state_directory": None}
    if not isinstance(raw, dict) or set(raw) - set(defaults):
        raise ValueError("environment locations support only default_root, projects, runtime_directory, state_directory")
    result = {**defaults, **copy.deepcopy(raw)}
    for key in ("default_root", "runtime_directory", "state_directory"):
        if result[key] is not None:
            validate_absolute_locator(result[key], key)
    projects = result["projects"]
    if not isinstance(projects, dict) or len(projects) > 256:
        raise ValueError("environment projects must be an object of at most 256 aliases")
    for alias, path in projects.items():
        if not isinstance(alias, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", alias):
            raise ValueError("project alias must be a bounded lowercase identifier")
        validate_absolute_locator(path, f"project {alias}")
    return result


def _validate_raw_profile(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return raw
    extra = sorted(set(raw) - _TOP_LEVEL_KEYS)
    if extra:
        raise ValueError(f"host config contains unsupported top-level keys: {extra}")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != HOST_CONFIG_SCHEMA_VERSION:
        raise ValueError(f"unsupported host config schema_version: {raw.get('schema_version')!r}; update the private profile explicitly")
    for section in _SECTION_KEYS:
        if section in raw:
            if section == "progress_visibility":
                _validate_progress(raw[section])
            else:
                _validate_section(section, raw[section])
    return raw


def _load_raw_host_config() -> tuple[dict[str, Any], list[str], bool]:
    # Missing is a default; unsafe, unreadable, corrupt, or unsupported is an error.
    path = host_config_path()
    try:
        _check_private_regular_file(path)
    except FileNotFoundError:
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, [], False
    try:
        raw = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"host config is invalid and was not overwritten: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("host config must be a JSON object")
    _validate_raw_profile(raw)
    return dict(raw), [], True


def effective_host_profile() -> dict[str, Any]:
    raw, warnings, file_exists = _load_raw_host_config()
    profile = copy.deepcopy(DEFAULT_HOST_PROFILE)
    profile["progress_visibility"] = _validate_progress(raw.get("progress_visibility"))
    for section in _SECTION_KEYS:
        if section != "progress_visibility":
            profile[section] = _validate_section(section, raw.get(section))
    return {
        **profile,
        "config_path": str(host_config_path()),
        "config_file_exists": file_exists,
        "source": "host_file" if file_exists else "default",
        "warnings": warnings,
        "repository_persisted": False,
        "authorization_persisted": False,
        "capability_state_persisted": False,
    }


def environment_locations(computer: str | None) -> dict[str, Any]:
    raw, _, _ = _load_raw_host_config()
    environments = _validate_section("workspace", raw.get("workspace"))["environments"]
    return copy.deepcopy(environments.get(computer, validate_environment_locations({})))


def _write_raw_profile(raw: dict[str, Any]) -> None:
    raw = copy.deepcopy(raw)
    raw["schema_version"] = HOST_CONFIG_SCHEMA_VERSION
    _validate_raw_profile(raw)
    _atomic_json_write(host_config_path(), raw)


def host_config_show() -> dict[str, Any]:
    return effective_host_profile()


def execution_config() -> dict[str, Any]:
    # Routing must not silently change machines when a profile is malformed.
    raw, _, _ = _load_raw_host_config()
    return _validate_section("execution", raw.get("execution"))


def _leaf_parts(path: str) -> tuple[str, str]:
    if path not in _LEAF_PATHS:
        raise ValueError(f"unsupported host config path: {path}")
    section, key = path.split(".", 1)
    return section, key


def host_config_get(path: str) -> Any:
    section, key = _leaf_parts(path)
    return effective_host_profile()[section][key]


def _profile_save_status() -> dict[str, Any]:
    backend = effective_host_profile()["persistence"]["host_profile_backend"]
    return {
        "saved": True,
        "cross_chat_saved": False,
        "profile_sync_action": {
            "auto": "sync_if_current_drive_connected",
            "google_drive": "sync_required_or_report_failure",
            "local_only": "local_only_no_upload",
        }[backend],
    }


def host_config_set(path: str, value: Any) -> dict[str, Any]:
    section, key = _leaf_parts(path)
    raw, _warnings, _exists = _load_raw_host_config()
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
    result.update(_profile_save_status())
    result["updated_path"] = path
    return result


def host_config_unset(path: str) -> dict[str, Any]:
    section, key = _leaf_parts(path)
    raw, _warnings, _exists = _load_raw_host_config()
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
    result.update(_profile_save_status())
    result["unset_path"] = path
    return result


def host_config_reset(section: str) -> dict[str, Any]:
    if section not in _SECTION_KEYS:
        raise ValueError(f"unsupported host config section: {section}")
    raw, _warnings, _exists = _load_raw_host_config()
    raw.pop(section, None)
    _write_raw_profile(raw)
    result = effective_host_profile()
    result.update(_profile_save_status())
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
    raw, _warnings, _file_exists = _load_raw_host_config()
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
    result.update(_profile_save_status())
    result["reset_to_defaults"] = bool(reset)
    return result


def progress_policy(work_shape: str) -> dict[str, Any]:
    if work_shape not in {"lightweight", "substantive"}:
        raise ValueError("work_shape must be lightweight or substantive")
    config = effective_progress_config()
    if work_shape == "lightweight":
        return {
            "work_shape": "lightweight",
            "visibility_mode": "low_noise",
            "periodic_updates": False,
            "emit_upfront_plan": False,
            "material_event_updates": bool(config["material_event_updates"]),
            "config": config,
            "instruction": "Keep lightweight work concise; do not add periodic progress messages.",
        }
    mode = str(config["mode"])
    if mode == "quiet":
        return {
            "work_shape": "substantive",
            "visibility_mode": "quiet",
            "periodic_updates": False,
            "emit_upfront_plan": False,
            "material_event_updates": bool(config["material_event_updates"]),
            "config": config,
            "instruction": "Suppress routine progress messages; still surface material findings or blockers when configured or required.",
        }
    if mode == "standard":
        return {
            "work_shape": "substantive",
            "visibility_mode": "standard",
            "periodic_updates": "host_default",
            "emit_upfront_plan": bool(config["upfront_plan"]),
            "material_event_updates": bool(config["material_event_updates"]),
            "config": config,
            "instruction": "Use the host's normal progress cadence while keeping updates concise and material.",
        }
    return {
        "work_shape": "substantive",
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
