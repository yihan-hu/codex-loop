"""Private profile serialization; Drive authentication/transport stays host-owned."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .host_config import (
    DEFAULT_HOST_PROFILE, HOST_CONFIG_MAX_BYTES, _atomic_json_write,
    _check_private_regular_file, _load_raw_host_config, _validate_raw_v2,
    _write_raw_profile,
)

PROFILE_DRIVE_PATH = "codex-loop/settings/host-profile.json"
# Cache cleanup registrations and legacy roots are never portable preferences.
PROFILE_KEYS = frozenset(DEFAULT_HOST_PROFILE) - {"drive"}


def _account(root_id: str) -> str:
    if not isinstance(root_id, str) or root_id in {"root", "me"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", root_id):
        raise ValueError("current connected user's My Drive root ID is required")
    return hashlib.sha256(root_id.encode()).hexdigest()


def _digest(profile: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _profile(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) - PROFILE_KEYS:
        raise ValueError("portable Host Profile contains unsupported fields")
    _validate_raw_v2(raw)
    # Preferences are data, never scripts, tokens, or authentication material.
    if re.search(r"sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+|-----BEGIN .*PRIVATE KEY", json.dumps(raw), re.IGNORECASE):
        raise ValueError("credentials must remain in the connected app's private authentication store")
    return copy.deepcopy(raw)


def export_profile(*, drive_root_id: str, output: str) -> dict[str, Any]:
    raw, _, _ = _load_raw_host_config(strict=True)
    profile = _profile({k: v for k, v in raw.items() if k in PROFILE_KEYS})
    payload = {"format": "codex-loop-host-profile", "version": 1,
               "account_sha256": _account(drive_root_id), "profile": profile,
               "profile_sha256": _digest(profile)}
    path = Path(output).expanduser().absolute()
    from .workspace_registry import host_config_path
    if path.resolve() == host_config_path().resolve():
        raise ValueError("export must not replace host.json with a transport envelope")
    _atomic_json_write(path, payload)
    return {"export_path": str(path), "drive_path": PROFILE_DRIVE_PATH,
            "profile_sha256": payload["profile_sha256"], "cross_chat_saved": False,
            "next_action": "host_upload_or_update_private_drive_file_then_fetch_and_verify"}


def import_profile(*, drive_root_id: str, input_path: str) -> dict[str, Any]:
    path = Path(input_path).expanduser()
    _check_private_regular_file(path)
    encoded = path.read_bytes()
    if len(encoded) > HOST_CONFIG_MAX_BYTES:
        raise ValueError("profile import exceeds size bound")
    payload = json.loads(encoded.decode("utf-8"))
    required = {"format", "version", "account_sha256", "profile", "profile_sha256"}
    if not isinstance(payload, dict) or set(payload) != required or payload["format"] != "codex-loop-host-profile" or type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("unsupported portable Host Profile envelope")
    if payload["account_sha256"] != _account(drive_root_id):
        raise ValueError("Host Profile belongs to a different Drive account")
    profile = _profile(payload["profile"])
    if payload["profile_sha256"] != _digest(profile):
        raise ValueError("Host Profile digest mismatch")
    # Keep the receiving native computer's cleanup registry; Web uses a fresh home.
    existing, _, _ = _load_raw_host_config(strict=True)
    if "drive" in existing:
        profile["drive"] = existing["drive"]
    _write_raw_profile(profile)
    return {"restored": True, "profile_sha256": payload["profile_sha256"],
            "authorization_restored": False, "tasks_restored": False}
