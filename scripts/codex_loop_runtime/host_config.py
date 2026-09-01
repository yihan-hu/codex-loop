from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

from .workspace_registry import host_config_path

HOST_CONFIG_SCHEMA_VERSION = 1
PROGRESS_MODES = frozenset({"quiet", "standard", "enhanced"})
DEFAULT_PROGRESS_CONFIG: dict[str, Any] = {
    "mode": "enhanced",
    "interval_seconds": 15,
    "tool_call_interval": 3,
    "upfront_plan": True,
    "material_event_updates": True,
}
_PROGRESS_KEYS = frozenset(DEFAULT_PROGRESS_CONFIG)


def _check_private_regular_file(path: Path) -> None:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"host-local Codex Loop config is not a regular file: {path}")
    if hasattr(os, "geteuid") and info.st_uid != os.geteuid():
        raise PermissionError(f"host-local Codex Loop config is not owned by current user: {path}")


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


def _load_raw_host_config(*, strict: bool) -> tuple[dict[str, Any], list[str], bool]:
    path = host_config_path()
    try:
        _check_private_regular_file(path)
    except FileNotFoundError:
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, [], False
    except (OSError, RuntimeError, PermissionError) as exc:
        if strict:
            raise
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, ["unsafe_host_config_ignored_for_progress"], True
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if strict:
            raise RuntimeError(f"host config is invalid and was not overwritten: {path}") from exc
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, ["invalid_host_config_json_using_progress_defaults"], True
    except OSError:
        if strict:
            raise
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, ["unreadable_host_config_using_progress_defaults"], True
    if not isinstance(raw, dict):
        if strict:
            raise ValueError("host config must be a JSON object")
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, ["invalid_host_config_object_using_progress_defaults"], True
    version = raw.get("schema_version", HOST_CONFIG_SCHEMA_VERSION)
    if version != HOST_CONFIG_SCHEMA_VERSION:
        if strict:
            raise ValueError(f"unsupported host config schema_version: {version!r}")
        return {"schema_version": HOST_CONFIG_SCHEMA_VERSION}, ["unsupported_host_config_version_using_progress_defaults"], True
    normalized = dict(raw)
    normalized["schema_version"] = HOST_CONFIG_SCHEMA_VERSION
    return normalized, [], True


def _validate_progress(raw: Any) -> dict[str, Any]:
    if raw is None:
        return dict(DEFAULT_PROGRESS_CONFIG)
    if not isinstance(raw, dict):
        raise ValueError("progress_visibility must be a JSON object")
    unexpected = set(raw) - _PROGRESS_KEYS
    if unexpected:
        raise ValueError(f"progress_visibility has unsupported keys: {sorted(unexpected)}")
    result = dict(DEFAULT_PROGRESS_CONFIG)
    result.update(raw)
    mode = result["mode"]
    if mode not in PROGRESS_MODES:
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


def effective_progress_config() -> dict[str, Any]:
    raw, warnings, file_exists = _load_raw_host_config(strict=False)
    try:
        config = _validate_progress(raw.get("progress_visibility"))
        source = "host_file" if "progress_visibility" in raw and not warnings else "default"
    except ValueError:
        config = dict(DEFAULT_PROGRESS_CONFIG)
        warnings = [*warnings, "invalid_progress_visibility_using_defaults"]
        source = "default"
    return {
        **config,
        "config_path": str(host_config_path()),
        "config_file_exists": file_exists,
        "source": source,
        "warnings": warnings,
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
    raw["schema_version"] = HOST_CONFIG_SCHEMA_VERSION
    _atomic_json_write(host_config_path(), raw)
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
