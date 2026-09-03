from __future__ import annotations

import hashlib
from typing import Any

FALLBACK_METHODS = {
    "verified_incremental_replay",
    "installed_skill_exception",
    "verified_model_relay",
    "local_mode",
}


def source_acquisition_plan(
    *,
    exact_commit_bundle_available: bool = False,
    receipt_bound_bundle_available: bool = False,
    fallback_method: str | None = None,
    current_user_fallback_authorization_observed: bool = False,
    authorization_evidence: str | None = None,
) -> dict[str, Any]:
    """Choose direct acquisition or fail closed; fallback is explicit-user-only."""
    if exact_commit_bundle_available:
        return {
            "status": "DIRECT",
            "method": "github_git_bundle",
            "fallback_allowed": False,
            "next": "restore exact commit-bound bundle and require exact commit/tree identity",
        }
    if receipt_bound_bundle_available:
        return {
            "status": "DIRECT",
            "method": "receipt_bound_git_bundle",
            "fallback_allowed": False,
            "next": "restore receipt-bound published bundle and require exact commit/tree identity",
        }

    method = None if fallback_method is None else str(fallback_method).strip().lower()
    if method is None:
        return {
            "status": "BLOCKED",
            "classification": "WORKSPACE_DOWNLOAD_ARTIFACT_UNAVAILABLE",
            "method": None,
            "fallback_allowed": False,
            "next": "stop and surface the direct acquisition blocker; do not start slow recovery automatically",
        }
    if method not in FALLBACK_METHODS:
        raise ValueError("fallback method must be one of " + ", ".join(sorted(FALLBACK_METHODS)))
    evidence = str(authorization_evidence or "").strip()
    if not current_user_fallback_authorization_observed or not evidence:
        raise PermissionError(
            "source acquisition fallback requires host-observed explicit current-task user authorization plus audit evidence"
        )
    return {
        "status": "FALLBACK_AUTHORIZED",
        "method": method,
        "fallback_allowed": True,
        "authorization_scope": "current_task_only",
        "authorization_evidence_sha256": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
        "requires_exact_final_commit_tree": True,
        "requires_separate_local_route_transition": method == "local_mode",
        "next": "execute only the explicitly authorized fallback and fail closed on identity mismatch",
    }


def restored_identity_result(
    *, expected_commit: str, expected_tree: str, actual_commit: str, actual_tree: str
) -> dict[str, Any]:
    exact = expected_commit == actual_commit and expected_tree == actual_tree
    if exact:
        return {"status": "PASS", "exact": True, "fallback_allowed": False}
    return {
        "status": "BLOCKED",
        "exact": False,
        "classification": "WORKSPACE_GIT_IDENTITY_MISMATCH",
        "fallback_allowed": False,
        "next": "stop; identity mismatch is an acquisition/control-plane defect, not a trigger for automatic slow recovery",
    }
