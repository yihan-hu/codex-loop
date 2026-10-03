"""Select host-exposed connectors; credentials and tool dispatch stay with the host."""
from __future__ import annotations

import re
from typing import Any

from .host_config import execution_config, environment_locations, validate_absolute_locator


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
    selected["locations"] = environment_locations(selected["computer"])
    return {"workspace_mode": "local", "computer": selected["computer"],
            "local_connection": selected,
            "basis": "explicit_user_target" if explicit else "saved_default",
            "status": "needs_observation" if available_connections is None else "resolved"}


def resolve_local_root(selected: dict[str, Any], *, local_root: str | None = None,
                       project: str | None = None, workspace_granted: bool = False) -> dict[str, Any]:
    """Resolve locators only. The caller observes authorization and the remote directory."""
    if local_root is not None and project is not None:
        raise ValueError("choose a task directory or a project alias, not both")
    locations = selected["locations"]
    if local_root is not None:
        root = validate_absolute_locator(local_root, "task local_root")
        basis = "current_task_directory"
    elif project is not None:
        if project not in locations["projects"]:
            raise ValueError(f"unknown project {project!r} on environment {selected['computer']!r}")
        root = locations["projects"][project]
        basis = "saved_project"
    else:
        root = locations["default_root"]
        basis = "saved_environment_default"
    requirements = []
    if root is None:
        requirements.append("specify_task_directory_or_save_environment_default_workspace")
    if not workspace_granted:
        requirements.append("current_task_path_authorization_and_connector_directory_verification")
    return {"local_root": root, "local_root_basis": basis, "requirements": requirements,
            "path_authorization_persisted": False}
