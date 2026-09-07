from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .release_lineage import capture_workspace_binding
from .workspace import run_git

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
_CACHE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

HOT_REUSE = "HOT_REUSE"
WARM_RESTORE_PUBLISHED_SOURCE = "WARM_RESTORE_PUBLISHED_SOURCE"
WARM_RESTORE_WORKSPACE_CACHE = "WARM_RESTORE_WORKSPACE_CACHE"
COLD_ACQUIRE_REQUIRED = "COLD_ACQUIRE_REQUIRED"


def _full_sha(value: str | None, *, field: str) -> str:
    clean = str(value or "").strip().lower()
    if not _SHA40_RE.fullmatch(clean):
        raise ValueError(f"{field} must be full 40-hex")
    return clean


def _sha256(value: str | None, *, field: str) -> str:
    clean = str(value or "").strip().lower()
    if not _SHA64_RE.fullmatch(clean):
        raise ValueError(f"{field} must be full 64-hex")
    return clean


def _repository(value: str) -> str:
    clean = str(value).strip().strip("/")
    if clean.endswith(".git"):
        clean = clean[:-4]
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", clean):
        raise ValueError("repository must use owner/name")
    return clean


def _origin_hint(repository: str) -> str:
    return f"github.com/{_repository(repository)}"


def _git_text(root: Path, *args: str) -> str | None:
    proc = run_git(root, list(args))
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="replace").strip()


def _commit_exists(root: Path, commit: str) -> bool:
    return run_git(root, ["cat-file", "-e", f"{commit}^{{commit}}"]).returncode == 0


def _ancestor(root: Path, older: str, newer: str) -> bool:
    return run_git(root, ["merge-base", "--is-ancestor", older, newer]).returncode == 0


def _merge_base(root: Path, left: str, right: str) -> str | None:
    value = _git_text(root, "merge-base", left, right)
    if value is None or not _SHA40_RE.fullmatch(value.lower()):
        return None
    return value.lower()


def _source_provenance_from_hot(
    binding: dict[str, Any], *, repository: str, branch: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "codex_loop_source_provenance",
        "repository": _repository(repository),
        "origin_hint": _origin_hint(repository),
        "branch": branch,
        "base_commit": binding.get("base_commit"),
        "base_tree": binding.get("base_tree"),
        "verified": True,
        "path_bound": False,
        "verification_basis": "live_hot_git_workspace",
    }


def _validate_source_provenance(
    root: Path,
    provenance: dict[str, Any],
    *,
    repository: str,
    branch: str,
    current_head: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    if not isinstance(provenance, dict):
        return None, ["source provenance is not an object"]
    if provenance.get("kind") != "codex_loop_source_provenance" or provenance.get("schema_version") != 1:
        reasons.append("source provenance schema/kind mismatch")
    if provenance.get("verified") is not True:
        reasons.append("source provenance is not verified")
    if provenance.get("path_bound") is not False:
        reasons.append("source provenance must be path-independent")
    if str(provenance.get("repository") or "") != _repository(repository):
        reasons.append("source provenance repository mismatch")
    if str(provenance.get("origin_hint") or "") != _origin_hint(repository):
        reasons.append("source provenance origin mismatch")
    if str(provenance.get("branch") or "") != branch:
        reasons.append("source provenance branch mismatch")
    try:
        base_commit = _full_sha(provenance.get("base_commit"), field="source provenance base_commit")
        base_tree = _full_sha(provenance.get("base_tree"), field="source provenance base_tree")
    except ValueError as exc:
        reasons.append(str(exc))
        return None, reasons
    if not _commit_exists(root, base_commit):
        reasons.append("source provenance base commit is absent from Git object database")
    else:
        observed_tree = _git_text(root, "rev-parse", f"{base_commit}^{{tree}}")
        if observed_tree != base_tree:
            reasons.append("source provenance base tree mismatch")
        if not _ancestor(root, base_commit, current_head):
            reasons.append("current Git history does not descend from source provenance base commit")
    normalized = dict(provenance)
    normalized["base_commit"] = base_commit
    normalized["base_tree"] = base_tree
    return normalized, reasons


def _remote_sync_state(
    root: Path,
    *,
    local_head: str,
    local_tree: str,
    remote_head: str | None,
    remote_tree: str | None,
) -> dict[str, Any]:
    if remote_head is None and remote_tree is None:
        return {
            "state": "REMOTE_UNOBSERVED",
            "source_identity_valid": True,
            "requires_incremental_fetch": False,
            "next_action": "observe remote HEAD/tree only when synchronization or publication needs it",
        }
    if remote_head is None or remote_tree is None:
        raise ValueError("remote_head and remote_tree must be provided together")
    remote_head = _full_sha(remote_head, field="remote_head")
    remote_tree = _full_sha(remote_tree, field="remote_tree")
    if remote_head == local_head:
        if remote_tree != local_tree:
            return {
                "state": "REMOTE_OBSERVATION_MISMATCH",
                "source_identity_valid": True,
                "requires_incremental_fetch": False,
                "blocked": True,
                "next_action": "re-observe remote commit/tree; do not reacquire source",
            }
        return {
            "state": "IN_SYNC",
            "source_identity_valid": True,
            "remote_head": remote_head,
            "remote_tree": remote_tree,
            "requires_incremental_fetch": False,
            "next_action": "continue editing/commit or thin-bundle publish from the existing workspace",
        }
    if not _commit_exists(root, remote_head):
        return {
            "state": "REMOTE_HEAD_UNSEEN",
            "source_identity_valid": True,
            "requires_incremental_fetch": True,
            "remote_head": remote_head,
            "remote_tree": remote_tree,
            "next_action": "fetch only the missing remote Git objects, then classify fast-forward/divergence; do not run full source acquisition",
        }
    observed_remote_tree = _git_text(root, "rev-parse", f"{remote_head}^{{tree}}")
    if observed_remote_tree != remote_tree:
        return {
            "state": "REMOTE_OBSERVATION_MISMATCH",
            "source_identity_valid": True,
            "requires_incremental_fetch": False,
            "blocked": True,
            "next_action": "re-observe remote commit/tree; do not reacquire source",
        }
    if _ancestor(root, remote_head, local_head):
        return {
            "state": "LOCAL_AHEAD",
            "source_identity_valid": True,
            "remote_head": remote_head,
            "remote_tree": remote_tree,
            "requires_incremental_fetch": False,
            "next_action": "continue with incremental publication from the existing workspace",
        }
    if _ancestor(root, local_head, remote_head):
        return {
            "state": "REMOTE_AHEAD",
            "source_identity_valid": True,
            "remote_head": remote_head,
            "remote_tree": remote_tree,
            "requires_incremental_fetch": False,
            "next_action": "fast-forward/rebase the existing workspace using the already-present remote objects; do not reacquire source",
        }
    merge_base = _merge_base(root, local_head, remote_head)
    if merge_base is None:
        return {
            "state": "UNRELATED_HISTORY",
            "source_identity_valid": False,
            "remote_head": remote_head,
            "remote_tree": remote_tree,
            "requires_incremental_fetch": False,
            "blocked": True,
            "next_action": "reject this HOT workspace as canonical source; use verified WARM recovery or COLD acquisition",
        }
    merge_base_tree = _git_text(root, "rev-parse", f"{merge_base}^{{tree}}")
    return {
        "state": "DIVERGED",
        "source_identity_valid": True,
        "remote_head": remote_head,
        "remote_tree": remote_tree,
        "merge_base": merge_base,
        "merge_base_tree": merge_base_tree,
        "requires_incremental_fetch": False,
        "next_action": "merge/rebase in the existing Git workspace; divergence is synchronization state, not source identity failure",
    }


def _hot_workspace(
    root: Path,
    *,
    repository: str,
    branch: str,
    source_provenance: dict[str, Any] | None,
    remote_head: str | None,
    remote_tree: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    try:
        if not root.exists() or not root.is_dir():
            return None, ["workspace path is absent"]
        binding = capture_workspace_binding(root)
    except (OSError, RuntimeError) as exc:
        return None, [f"workspace probe failed: {exc}"]
    if not binding.get("is_git"):
        return None, ["workspace is not a real Git working tree"]
    if binding.get("origin_hint") != _origin_hint(repository):
        reasons.append("Git origin does not identify the expected repository")
    if str(binding.get("initial_branch") or "") != branch:
        reasons.append("Git branch does not equal the intended branch")
    head = str(binding.get("base_commit") or "").lower()
    tree = str(binding.get("base_tree") or "").lower()
    if not _SHA40_RE.fullmatch(head) or not _SHA40_RE.fullmatch(tree):
        reasons.append("workspace HEAD/tree identity is incomplete")
    shallow = run_git(root, ["rev-parse", "--is-shallow-repository"])
    if shallow.returncode != 0:
        reasons.append("could not prove Git history completeness")
    elif shallow.stdout.decode("utf-8", errors="replace").strip().lower() != "false":
        reasons.append("Git history is shallow")
    if reasons:
        return None, reasons

    remote_sync = _remote_sync_state(
        root,
        local_head=head,
        local_tree=tree,
        remote_head=remote_head,
        remote_tree=remote_tree,
    )
    if remote_sync.get("state") == "UNRELATED_HISTORY":
        return None, ["Git history is unrelated to the observed canonical remote branch"]

    ready_for_mutation = True
    if source_provenance is not None:
        provenance, provenance_reasons = _validate_source_provenance(
            root,
            source_provenance,
            repository=repository,
            branch=branch,
            current_head=head,
        )
        reasons.extend(provenance_reasons)
        if provenance is None or reasons:
            return None, reasons
    else:
        sync_state = str(remote_sync.get("state"))
        if sync_state == "IN_SYNC":
            provenance = {
                **_source_provenance_from_hot(binding, repository=repository, branch=branch),
                "verification_basis": "fresh_remote_exact_commit_tree",
            }
        elif sync_state == "LOCAL_AHEAD":
            provenance = {
                "schema_version": 1,
                "kind": "codex_loop_source_provenance",
                "repository": _repository(repository),
                "origin_hint": _origin_hint(repository),
                "branch": branch,
                "base_commit": remote_sync["remote_head"],
                "base_tree": remote_sync["remote_tree"],
                "verified": True,
                "path_bound": False,
                "verification_basis": "fresh_remote_ancestor_of_hot_head",
            }
        elif sync_state == "REMOTE_AHEAD":
            provenance = {
                **_source_provenance_from_hot(binding, repository=repository, branch=branch),
                "verification_basis": "hot_head_is_ancestor_of_fresh_remote",
            }
        elif sync_state == "DIVERGED":
            provenance = {
                "schema_version": 1,
                "kind": "codex_loop_source_provenance",
                "repository": _repository(repository),
                "origin_hint": _origin_hint(repository),
                "branch": branch,
                "base_commit": remote_sync["merge_base"],
                "base_tree": remote_sync["merge_base_tree"],
                "verified": True,
                "path_bound": False,
                "verification_basis": "fresh_remote_shared_merge_base",
            }
        else:
            ready_for_mutation = False
            provenance = {
                **_source_provenance_from_hot(binding, repository=repository, branch=branch),
                "verified": False,
                "verification_basis": "hot_git_structure_only",
                "verification_pending": (
                    "observe fresh remote commit/tree"
                    if sync_state == "REMOTE_UNOBSERVED"
                    else "fetch missing remote Git objects and rerun repository-enter"
                ),
            }

    lease = {
        "schema_version": 1,
        "kind": "codex_loop_workspace_lease",
        "status": "HOT" if ready_for_mutation else "HOT_PENDING_IDENTITY",
        "path_bound": True,
        "canonical_root": str(root.resolve()),
        "repository_id": binding.get("repository_id"),
        "repository": _repository(repository),
        "origin_hint": binding.get("origin_hint"),
        "branch": binding.get("initial_branch"),
        "head_commit": head,
        "head_tree": tree,
    }
    return {
        "status": HOT_REUSE,
        "repository": _repository(repository),
        "branch": branch,
        "source_reacquisition_required": False,
        "full_source_acquisition_required": False,
        "workspace_restore_required": False,
        "ready_for_mutation": ready_for_mutation,
        "source_provenance": provenance,
        "workspace_lease": lease,
        "remote_sync": remote_sync,
        "next_action": (
            "reuse this exact Git workspace; do not invoke source acquisition while the HOT lease remains valid"
            if ready_for_mutation
            else str(remote_sync.get("next_action") or provenance.get("verification_pending"))
        ),
    }, []


def _valid_workspace_cache(
    value: dict[str, Any] | None, *, repository: str, branch: str
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    try:
        cache_id = str(value.get("cache_id") or "").strip().lower()
        if not _CACHE_ID_RE.fullmatch(cache_id):
            return None
        sha = _sha256(value.get("capsule_sha256"), field="workspace cache sha256")
        commit = _full_sha(value.get("head_commit"), field="workspace cache head_commit")
        tree = _full_sha(value.get("head_tree"), field="workspace cache head_tree")
    except ValueError:
        return None
    if str(value.get("branch") or "") != branch:
        return None
    if str(value.get("repository") or "").strip().strip("/") != _repository(repository):
        return None
    if bool(value.get("consumed", False)) or bool(value.get("expired", False)):
        return None
    expires_at = value.get("expires_at")
    if not expires_at:
        return None
    try:
        expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= expires:
            return None
    except ValueError:
        return None
    return {
        "cache_id": cache_id,
        "capsule_sha256": sha,
        "head_commit": commit,
        "head_tree": tree,
        "branch": branch,
        "expires_at": expires_at,
    }


def _valid_published_source(
    value: dict[str, Any] | None,
    *,
    remote_head: str | None,
    remote_tree: str | None,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or str(value.get("fresh_restore") or "") != "PASS":
        return None
    try:
        commit = _full_sha(value.get("published_commit"), field="published source commit")
        tree = _full_sha(value.get("published_tree"), field="published source tree")
        sha = _sha256(value.get("published_source_sha256"), field="published source sha256")
        size = int(value.get("published_source_size"))
    except (ValueError, TypeError):
        return None
    artifact_id = str(value.get("published_source_artifact_id") or "").strip()
    artifact_name = str(value.get("published_source_artifact") or "").strip()
    if size <= 0 or not artifact_id or not artifact_name:
        return None
    remote_match: bool | None = None
    if remote_head is not None or remote_tree is not None:
        if remote_head is None or remote_tree is None:
            raise ValueError("remote_head and remote_tree must be provided together")
        remote_match = (
            commit == _full_sha(remote_head, field="remote_head")
            and tree == _full_sha(remote_tree, field="remote_tree")
        )
    return {
        "published_commit": commit,
        "published_tree": tree,
        "published_source_sha256": sha,
        "published_source_size": size,
        "published_source_artifact_id": artifact_id,
        "published_source_artifact": artifact_name,
        "fresh_restore": "PASS",
        "remote_match": remote_match,
        "incremental_sync_required": remote_match is False,
    }


def repository_enter(
    root: Path,
    *,
    repository: str,
    branch: str,
    remote_head: str | None = None,
    remote_tree: str | None = None,
    source_provenance: dict[str, Any] | None = None,
    published_source: dict[str, Any] | None = None,
    workspace_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Choose the cheapest safe repository-continuity path.

    HOT is the normal path. WARM restores a previously verified Git artifact when the
    host workspace was lost. COLD acquisition is a last resort, never the default
    response to a missing path or a moved remote HEAD.
    """
    repository = _repository(repository)
    branch = str(branch).strip()
    if not branch:
        raise ValueError("branch must be non-empty")
    root = Path(root).resolve(strict=False)

    hot, hot_reasons = _hot_workspace(
        root,
        repository=repository,
        branch=branch,
        source_provenance=source_provenance,
        remote_head=remote_head,
        remote_tree=remote_tree,
    )
    if hot is not None:
        return hot

    cache = _valid_workspace_cache(workspace_cache, repository=repository, branch=branch)
    if cache is not None:
        provenance = {
            "schema_version": 1,
            "kind": "codex_loop_source_provenance",
            "repository": repository,
            "origin_hint": _origin_hint(repository),
            "branch": branch,
            "base_commit": cache["head_commit"],
            "base_tree": cache["head_tree"],
            "verified": False,
            "path_bound": False,
            "verification_basis": "workspace_cache_manifest_pending_capsule_validation",
            "verification_pending": "workspace-cache-validate + workspace-cache-restore + repository-enter",
        }
        return {
            "status": WARM_RESTORE_WORKSPACE_CACHE,
            "repository": repository,
            "branch": branch,
            "hot_rejection_reasons": hot_reasons,
            "source_reacquisition_required": False,
            "full_source_acquisition_required": False,
            "workspace_restore_required": True,
            "source_provenance": provenance,
            "restore": cache,
            "next_action": "download the exact Workspace Capsule, run workspace-cache-validate, restore into a fresh path, set/verify canonical origin, then rerun repository-enter; do not cold-acquire source",
        }

    published = _valid_published_source(
        published_source,
        remote_head=remote_head,
        remote_tree=remote_tree,
    )
    if published is not None:
        provenance = {
            "schema_version": 1,
            "kind": "codex_loop_source_provenance",
            "repository": repository,
            "origin_hint": _origin_hint(repository),
            "branch": branch,
            "base_commit": published["published_commit"],
            "base_tree": published["published_tree"],
            "verified": True,
            "path_bound": False,
            "verification_basis": "published_source_receipt_fresh_restore_pass",
        }
        return {
            "status": WARM_RESTORE_PUBLISHED_SOURCE,
            "repository": repository,
            "branch": branch,
            "hot_rejection_reasons": hot_reasons,
            "source_reacquisition_required": False,
            "full_source_acquisition_required": False,
            "workspace_restore_required": True,
            "source_provenance": provenance,
            "restore": published,
            "next_action": (
                "download the exact published-source Git bundle, restore into a fresh Git workspace, set canonical origin/branch, verify exact commit/tree, then fetch only missing remote objects and rerun repository-enter; do not run Workspace Download"
                if published.get("incremental_sync_required")
                else "download the exact published-source Git bundle, restore into a fresh Git workspace, set canonical origin/branch, verify exact commit/tree, then rerun repository-enter; do not run Workspace Download"
            ),
        }

    return {
        "status": COLD_ACQUIRE_REQUIRED,
        "repository": repository,
        "branch": branch,
        "hot_rejection_reasons": hot_reasons,
        "source_reacquisition_required": True,
        "full_source_acquisition_required": True,
        "workspace_restore_required": False,
        "next_action": "no HOT or verified WARM Git state is available; run the canonical exact Git source-acquisition path",
    }
