"""Select host-exposed connectors; credentials and tool dispatch stay with the host."""
from __future__ import annotations

import re
from typing import Any

from .host_config import execution_config


def resolve_execution(
    *, target: str | None = None, connection: str | None = None,
    available_connections: list[str] | None = None,
) -> dict[str, Any]:
    config = execution_config()
    for label, value in (("target", target), ("connection", connection)):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", value)):
            raise ValueError(f"{label} must be a bounded lowercase identifier")
    if available_connections is not None and (
        not isinstance(available_connections, list)
        or any(not isinstance(name, str) or not name for name in available_connections)
    ):
        raise ValueError("available_connections must be an array of host-observed connection names")
    explicit = target is not None or connection is not None
    chosen_target = target if target is not None else ("local" if connection else config["default_target"])
    if chosen_target == "web":
        if connection:
            raise ValueError("a local connection conflicts with an explicit Web target")
        return {"workspace_mode": "web", "computer": None, "local_connection": None,
                "basis": "explicit_user_target" if explicit else "saved_default", "status": "resolved"}

    configured = config["connections"]
    # No registration is needed for the traditional single-machine RDC path.
    candidates = list(configured)
    if not any(item["kind"] == "rdc" for item in candidates):
        candidates.append({"name": "rdc", "computer": None,
                           "connector": "Remote Desktop Commander", "kind": "rdc"})
    if chosen_target != "local":
        candidates = [item for item in candidates if item["computer"] == chosen_target]
        if not candidates:
            raise ValueError(f"unknown or unconfigured computer: {chosen_target}")
    if connection:
        candidates = [item for item in candidates if item["name"] == connection]
        if not candidates:
            raise ValueError(f"connection {connection!r} does not belong to target {chosen_target!r}")
    else:
        # Python's stable sort preserves the user's array order within each kind.
        candidates = sorted(candidates, key=lambda item: item["kind"] == "rdc")

    if available_connections is not None:
        candidates = [item for item in candidates if item["name"] in available_connections]
    if not candidates:
        raise RuntimeError("selected local target has no available connection; do not switch computers or Web/Local mode")
    selected = dict(candidates[0])
    return {"workspace_mode": "local", "computer": selected["computer"],
            "local_connection": selected,
            "basis": "explicit_user_target" if explicit else "saved_default",
            "status": "needs_observation" if available_connections is None else "resolved"}
