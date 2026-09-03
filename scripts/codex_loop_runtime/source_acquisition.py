from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .release_lineage import capture_workspace_binding
from .workspace import run_git

DIRECT_METHODS = {"github_git_bundle", "receipt_bound_git_bundle"}

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


def _full_sha(value: str, *, field: str) -> str:
    clean = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", clean):
        raise ValueError(f"{field} must be full 40-hex")
    return clean


def _repository_origin_hint(repository: str) -> str:
    clean = str(repository).strip().strip("/")
    if clean.endswith(".git"):
        clean = clean[:-4]
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", clean):
        raise ValueError("repository must use owner/name")
    return f"github.com/{clean}"


def verify_restored_git_workspace(
    root: Path,
    *,
    repository: str,
    expected_commit: str,
    expected_tree: str,
    branch: str | None = None,
    method: str = "github_git_bundle",
) -> dict[str, Any]:
    """Verify that a fresh Web restore is the exact Git-native canonical source.

    This is intentionally a pre-bootstrap attestation: the host restores the audited
    bundle, sets the canonical GitHub origin/branch, then this verifier proves that
    the workspace can safely become the durable task baseline.
    """
    root = Path(root).resolve()
    expected_commit = _full_sha(expected_commit, field="expected commit")
    expected_tree = _full_sha(expected_tree, field="expected tree")
    expected_origin = _repository_origin_hint(repository)
    method = str(method).strip().lower()
    allowed_methods = DIRECT_METHODS | FALLBACK_METHODS
    if method not in allowed_methods:
        raise ValueError("acquisition method must be one of " + ", ".join(sorted(allowed_methods)))

    binding = capture_workspace_binding(root)
    actual_commit = str(binding.get("base_commit") or "").lower()
    actual_tree = str(binding.get("base_tree") or "").lower()
    actual_branch = binding.get("initial_branch")
    actual_origin = binding.get("origin_hint")
    reasons: list[str] = []

    if not binding.get("is_git"):
        reasons.append("restored workspace is not a Git working tree")
    else:
        if actual_commit != expected_commit:
            reasons.append("Git HEAD does not equal expected source commit")
        if actual_tree != expected_tree:
            reasons.append("Git HEAD tree does not equal expected source tree")
        if actual_origin != expected_origin:
            reasons.append("Git origin does not identify the expected canonical repository")
        if branch is not None and str(actual_branch or "") != str(branch):
            reasons.append("Git branch does not equal the intended target branch")
        shallow = run_git(root, ["rev-parse", "--is-shallow-repository"])
        if shallow.returncode != 0:
            reasons.append("could not prove restored Git history completeness")
        elif shallow.stdout.decode("utf-8", errors="replace").strip().lower() != "false":
            reasons.append("restored Git workspace is shallow")
        object_probe = run_git(root, ["cat-file", "-e", f"{expected_commit}^{{commit}}"])
        if object_probe.returncode != 0:
            reasons.append("expected source commit is absent from restored Git object database")

    exact = not reasons
    if not exact:
        return {
            "status": "BLOCKED",
            "exact": False,
            "classification": "WORKSPACE_GIT_IDENTITY_MISMATCH",
            "fallback_allowed": False,
            "method": method,
            "repository": str(repository).strip().strip("/"),
            "expected_commit": expected_commit,
            "expected_tree": expected_tree,
            "actual_commit": actual_commit or None,
            "actual_tree": actual_tree or None,
            "reasons": reasons,
            "next": "stop before bootstrap or mutation; repair the Git-native acquisition path rather than rebinding a source-only snapshot",
        }
    return {
        "status": "PASS",
        "exact": True,
        "fallback_allowed": False,
        "method": method,
        "repository": str(repository).strip().strip("/"),
        "branch": actual_branch,
        "commit": actual_commit,
        "tree": actual_tree,
        "origin_hint": actual_origin,
        "history_complete": True,
        "canonical_root": str(root),
        "workspace_binding": binding,
        "next": "bootstrap the durable task in this exact workspace before any source mutation",
    }
