"""Host-owned Git authentication configuration check; never retrieve credentials."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def local_git_auth_status(root: Path, route: dict[str, Any], remote: str) -> dict[str, Any] | None:
    """Check configured GitHub HTTPS helper, not whether a secret is present."""
    connection = route.get("local_connection") or {}
    expected = (connection.get("locations") or {}).get("git_auth")
    if expected is None:
        return None

    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    remote_url = git("remote", "get-url", "--push", remote)
    if remote_url is None:
        return {"ok": False, "code": "GIT_REMOTE_UNAVAILABLE", "provider": expected}
    parsed = urlsplit(remote_url)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username is not None:
        return {"ok": False, "code": "GIT_AUTH_PROTOCOL_MISMATCH", "provider": expected}

    helper = git("config", "--get-urlmatch", "credential.helper", "https://github.com")
    values = (helper or "").splitlines()
    effective = values[-1].strip().lower() if values else ""
    if expected == "osxkeychain":
        matched = effective == "osxkeychain"
    elif expected == "windows_gcm":
        matched = "git-credential-manager" in effective
    else:
        matched = False
    if not matched:
        return {"ok": False, "code": "GIT_AUTH_HELPER_MISSING_OR_MISMATCHED", "provider": expected}
    return {"ok": True, "provider": expected, "status": "helper_configured", "credentials_verified": False}
