from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DURABLE_SIGNAL_KEYS = (
    "workspace_observation",
    "workspace_mutation",
    "executable_validation",
    "multiple_dependent_steps",
    "durable_evidence",
    "delegation",
    "external_actions",
    "managed_processes",
)

BINDING_LIFECYCLE_REQUIREMENTS = {"user_explicit", "composed_skill"}


def assess_runtime_need(
    signals: Mapping[str, bool] | None = None,
    *,
    binding_lifecycle_requirement: str | None = None,
    **overrides: bool,
) -> dict[str, Any]:
    """Derive direct-vs-durable execution from concrete needs plus binding contracts."""
    values = {key: False for key in DURABLE_SIGNAL_KEYS}
    for source in (signals or {}, overrides):
        unknown = sorted(set(source) - set(DURABLE_SIGNAL_KEYS))
        if unknown:
            raise ValueError("unknown lifecycle signal(s): " + ", ".join(unknown))
        values.update({key: bool(value) for key, value in source.items()})
    binding = None
    if binding_lifecycle_requirement is not None:
        binding = str(binding_lifecycle_requirement).strip().lower()
        if binding not in BINDING_LIFECYCLE_REQUIREMENTS:
            raise ValueError(
                "binding lifecycle requirement must be one of "
                + ", ".join(sorted(BINDING_LIFECYCLE_REQUIREMENTS))
            )
    capability_reasons = [key for key in DURABLE_SIGNAL_KEYS if values[key]]
    activation_reasons = list(capability_reasons)
    if binding is not None:
        activation_reasons.append(f"binding_lifecycle_requirement:{binding}")
    requires_durable = bool(capability_reasons) or binding is not None
    return {
        "mode": "durable" if requires_durable else "direct",
        "requires_durable_runtime": requires_durable,
        "activation_reasons": activation_reasons,
        "capability_activation_reasons": capability_reasons,
        "binding_lifecycle_requirement": binding,
    }


def derive_capability_state(
    *,
    generation: int,
    validation_status: str,
    review_status: str,
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
    if review_status != "not-required":
        active.append("change_review")
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
    review_requirement = {
        "not-required": "not_required",
        "fresh": "satisfied",
        "stale": "required",
    }.get(review_status, "required")

    requirements = {
        "completion_audit": "satisfied" if completion_status == "PASS" else "required"
    }
    if validation_status != "waived":
        requirements["validation"] = validation_requirement
    if review_status != "not-required":
        requirements["change_review"] = review_requirement
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
