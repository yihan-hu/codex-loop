"""Choose non-secret host Git credentials without probing them before push."""
from __future__ import annotations

from typing import Any


def local_git_auth_command(route: dict[str, Any], argv: list[str]) -> list[str]:
    """Override stale repo-local helpers using the selected host preference."""
    provider = ((route.get("local_connection") or {}).get("locations") or {}).get("git_auth")
    helpers = {
        "gh_cli": "!gh auth git-credential",
        "osxkeychain": "osxkeychain",
        "windows_gcm": "manager",
    }
    if provider is None:
        return argv
    if not argv or argv[0] != "git":
        raise ValueError("local native Git command required")
    return ["git", "-c", "credential.helper=", "-c", f"credential.helper={helpers[provider]}", *argv[1:]]
