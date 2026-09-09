from __future__ import annotations

from typing import Any

def derive_capability_state(
    *,
    generation: int,
    validation_status: str,
    active_isolation: bool,
    has_external_actions: bool,
    has_managed_processes: bool,
    has_repository_instructions: bool = False,
    completion_status: str = "CONTINUE",
) -> dict[str, Any]:
    """Project lifecycle capability state from authoritative facts without creating new truth."""
    active = ["workspace_observation", "completion_audit"]
    if has_repository_instructions:
        active.append("repository_instructions")
    if generation > 0:
        active.append("mutation_tracking")
    if validation_status != "waived":
        active.append("validation")
    if active_isolation:
        active.append("delegation")
    if has_external_actions:
        active.append("external_actions")
    if has_managed_processes:
        active.append("managed_processes")

    validation_requirement = {
        "waived": "not_required",
        "fresh-pass": "satisfied",
        "stale": "required",
        "missing": "required",
        "failing": "required",
    }.get(validation_status, "required")

    requirements = {
        "completion_audit": "satisfied" if completion_status == "PASS" else "required"
    }
    if validation_status != "waived":
        requirements["validation"] = validation_requirement
    if active_isolation:
        requirements["delegation"] = "required"
    if has_external_actions:
        requirements["external_actions"] = "required"
    if has_managed_processes:
        requirements["managed_processes"] = "required"
    return {
        "mode": "durable",
        "active_capabilities": active,
        "requirements": requirements,
    }
