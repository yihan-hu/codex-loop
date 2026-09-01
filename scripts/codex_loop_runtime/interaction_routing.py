from __future__ import annotations

from typing import Any, Iterable

from .host_config import effective_host_profile

VALID_TARGETS = {"none", "cloud_browser", "local_chrome", "local_mac_gui"}


def resolve_interaction_target(
    *,
    requires_web_interaction: bool,
    explicit_target: str | None = None,
    task_requires_local_session: bool = False,
    available_targets: Iterable[str] = (),
    local_computer_authorized: bool = False,
) -> dict[str, Any]:
    available = {str(x) for x in available_targets if str(x) in VALID_TARGETS}
    if not requires_web_interaction:
        return {
            "target": "none",
            "status": "resolved",
            "source": "task_requirement",
            "authorization_required": False,
            "available_targets": sorted(available),
        }
    profile = effective_host_profile()
    preferred = str(profile["browser"]["preferred_target"])
    if explicit_target is not None:
        target = str(explicit_target)
        source = "explicit_user_target"
    elif task_requires_local_session:
        target = "local_chrome"
        source = "task_hard_requirement"
    else:
        target = preferred or "cloud_browser"
        source = "host_profile_preference" if preferred else "built_in_default"
    if target not in {"cloud_browser", "local_chrome"}:
        raise ValueError("browser interaction target must be cloud_browser or local_chrome")

    if target == "local_chrome":
        if "local_chrome" not in available:
            return {
                "target": "local_chrome",
                "status": "capability_missing",
                "source": source,
                "authorization_required": True,
                "available_targets": sorted(available),
                "rule": "local Chrome is a user-session adapter and cannot be fabricated from host preference",
            }
        if not local_computer_authorized:
            return {
                "target": "local_chrome",
                "status": "authorization_required",
                "source": source,
                "authorization_required": True,
                "available_targets": sorted(available),
                "rule": "current-task explicit computer-use authorization is required before local Chrome interaction",
            }
        return {
            "target": "local_chrome",
            "status": "resolved",
            "source": source,
            "authorization_required": False,
            "available_targets": sorted(available),
        }

    if "cloud_browser" in available:
        return {
            "target": "cloud_browser",
            "status": "resolved",
            "source": source,
            "authorization_required": False,
            "available_targets": sorted(available),
        }

    fallback_offer = bool(
        task_requires_local_session
        and profile["browser"]["allow_local_chrome_fallback"]
        and "local_chrome" in available
    )
    return {
        "target": "cloud_browser",
        "status": "capability_missing",
        "source": source,
        "authorization_required": False,
        "available_targets": sorted(available),
        "local_chrome_option_available": fallback_offer,
        "local_chrome_auto_activated": False,
        "rule": "cloud failure never silently activates the user's local Chrome session",
    }
