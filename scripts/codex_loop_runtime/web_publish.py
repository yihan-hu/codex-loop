from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from .change_tracker import sync_generation
from .routing_state import permission_observation_status, route_show
from .workspace import git_head, git_status_porcelain_z, run_git

WEB_PUBLISH_CAPABILITIES = ("github_push", "github_actions", "google_drive_write")
_BUNDLE_REF_RE = re.compile(r"^refs/heads/codex-loop-publish-[0-9a-f]{32}$")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_text(root: Path, args: list[str]) -> str:
    proc = run_git(root, args)
    if proc.returncode != 0:
        raise RuntimeError("Git probe failed: " + proc.stderr.decode("utf-8", errors="replace").strip())
    return proc.stdout.decode("utf-8", errors="replace").strip()


def _head_tree(root: Path) -> tuple[str, str]:
    head = git_head(root)
    if not head:
        raise RuntimeError("Web publish requires a Git HEAD")
    return head, _git_text(root, ["rev-parse", f"{head}^{{tree}}"])


def _workspace_clean(root: Path) -> bool:
    status = git_status_porcelain_z(root)
    if status is None:
        raise RuntimeError("cannot prove Web publish workspace cleanliness")
    return status == b""


def _validation_fresh(store: Any) -> tuple[bool, dict[str, Any]]:
    generation = store.generation()
    if not bool(store.get_meta("requires_validation", True)):
        return True, {"generation": generation, "reason": "task explicitly does not require validation"}
    state = store.validation_state_for_generation(generation)
    ok = (
        int(state.get("passed_count", 0)) >= 1
        and int(state.get("failed_count", 0)) == 0
        and int(state.get("uncertain_count", 0)) == 0
        and int(state.get("cleanup_failed_count", 0)) == 0
        and int(state.get("orphaned_count", 0)) == 0
    )
    return ok, {"generation": generation, **state}


def _review_fresh(store: Any) -> tuple[bool, dict[str, Any]]:
    generation = store.generation()
    if generation == 0:
        return True, {"generation": generation, "required": False}
    reviewed = int(store.get_meta("changes_reviewed_generation", -1)) == generation
    return reviewed, {
        "generation": generation,
        "required": True,
        "reviewed_generation": store.get_meta("changes_reviewed_generation", -1),
    }


def _current_bundle_receipt(root: Path, store: Any) -> dict[str, Any] | None:
    receipt = store.get_meta("web_publish_bundle_receipt")
    if not isinstance(receipt, dict):
        return None
    try:
        path = Path(str(receipt["path"])).resolve()
        head, tree = _head_tree(root)
        size = int(receipt["size"])
        sha = str(receipt["sha256"])
        bundle_ref = str(receipt["bundle_ref"])
    except Exception:
        return None
    if not _BUNDLE_REF_RE.fullmatch(bundle_ref):
        return None
    if (
        str(receipt.get("source_commit")) != head
        or str(receipt.get("source_tree")) != tree
        or int(receipt.get("generation", -1)) != store.generation()
    ):
        return None
    if not path.is_file() or path.stat().st_size != size or _sha256_file(path) != sha:
        return None
    return dict(receipt)


def build_web_publish_bundle(
    root: Path, store: Any, *, output: Path, prerequisite_commit: str | None = None
) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    store.ensure_active()
    sync_generation(root, store)
    if not _workspace_clean(root):
        raise RuntimeError("publish-ready Git bundle requires a clean workspace")
    validation_ok, validation = _validation_fresh(store)
    review_ok, review = _review_fresh(store)
    if not validation_ok:
        raise RuntimeError("publish-ready Git bundle requires fresh current-generation validation")
    if not review_ok:
        raise RuntimeError("publish-ready Git bundle requires current-generation final change review")
    head, tree = _head_tree(root)
    prerequisite = None
    if prerequisite_commit is not None:
        prerequisite = str(prerequisite_commit).strip().lower()
        if len(prerequisite) != 40 or any(c not in "0123456789abcdef" for c in prerequisite):
            raise ValueError("Web publish bundle prerequisite must be full 40-hex")
        ancestor = run_git(root, ["merge-base", "--is-ancestor", prerequisite, head])
        if ancestor.returncode != 0:
            raise RuntimeError("Web publish bundle prerequisite must be an ancestor of audited HEAD")
    bundle_ref = f"refs/heads/codex-loop-publish-{uuid.uuid4().hex}"
    output.parent.mkdir(parents=True, exist_ok=True)
    update = run_git(root, ["update-ref", bundle_ref, head])
    if update.returncode != 0:
        raise RuntimeError("cannot create temporary Web publish ref")
    try:
        create_args = ["bundle", "create", str(output), bundle_ref]
        if prerequisite:
            create_args.append(f"^{prerequisite}")
        create = run_git(root, create_args)
        if create.returncode != 0:
            raise RuntimeError(
                "git bundle create failed: " + create.stderr.decode("utf-8", errors="replace").strip()
            )
    finally:
        run_git(root, ["update-ref", "-d", bundle_ref])
    verify = run_git(root, ["bundle", "verify", str(output)])
    if verify.returncode != 0:
        output.unlink(missing_ok=True)
        raise RuntimeError(
            "git bundle verify failed: " + verify.stderr.decode("utf-8", errors="replace").strip()
        )
    receipt = {
        "version": 2,
        "artifact_kind": "git_bundle",
        "generation": store.generation(),
        "source_commit": head,
        "source_tree": tree,
        "bundle_ref": bundle_ref,
        "prerequisite_commit": prerequisite,
        "path": str(output),
        "size": output.stat().st_size,
        "sha256": _sha256_file(output),
        "validation_generation": int(validation["generation"]),
        "review_generation": int(review["generation"]),
    }
    store.set_meta("web_publish_bundle_receipt", receipt)
    return receipt


def build_web_publish_archive(
    root: Path, store: Any, *, output: Path, top_level: str | None = None, prerequisite_commit: str | None = None
) -> dict[str, Any]:
    """Compatibility alias. Web publication now transports an exact Git bundle, not a source tarball."""
    if top_level is not None:
        raise ValueError("top_level is no longer supported; Web publication preserves Git identity with a bundle")
    return build_web_publish_bundle(root, store, output=output, prerequisite_commit=prerequisite_commit)


def web_publish_plan(
    root: Path,
    store: Any,
    *,
    session_id: str,
    repository: str,
    branch: str,
    remote_head: str,
    remote_tree: str,
    capability_scopes: dict[str, str],
    verified_tree_fast_path: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    store.ensure_active()
    sync_generation(root, store)
    route = route_show(session_id=session_id)
    if route.get("workspace_mode") != "web":
        raise RuntimeError("Web publish planner requires workspace_mode=web")
    for label, value in (("remote head", remote_head), ("remote tree", remote_tree)):
        normalized = str(value).strip().lower()
        if len(normalized) != 40 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError(f"{label} must be full 40-hex")
    clean = _workspace_clean(root)
    head, tree = _head_tree(root)
    validation_ok, validation = _validation_fresh(store)
    review_ok, review = _review_fresh(store)
    cap_status: dict[str, Any] = {}
    fresh: list[str] = []
    all_fresh = True
    for capability in WEB_PUBLISH_CAPABILITIES:
        scope = str(capability_scopes.get(capability) or "").strip()
        if not scope:
            cap_status[capability] = {"fresh": False, "reason": "missing_scope"}
            all_fresh = False
            continue
        status = permission_observation_status(
            session_id=session_id, capability=capability, scope=scope
        )
        cap_status[capability] = status
        if status.get("fresh"):
            fresh.append(capability)
        else:
            all_fresh = False
    reasons: list[str] = []
    if not verified_tree_fast_path:
        reasons.append("verified_tree_fast_path_not_requested")
    if not clean:
        reasons.append("workspace_not_clean")
    if not validation_ok:
        reasons.append("validation_not_fresh")
    if not review_ok:
        reasons.append("change_review_not_fresh")
    if not all_fresh:
        reasons.append("capability_observations_not_fresh")
    fast = not reasons
    bundle = _current_bundle_receipt(root, store)
    already = str(remote_head).lower() == head.lower() and str(remote_tree).lower() == tree.lower()
    return {
        "mode": "FAST_PUBLISH" if fast else "FULL_VERIFIED_PUBLISH",
        "fast_path_ready": fast,
        "fallback_reasons": reasons,
        "repository": repository,
        "branch": branch,
        "expected_base": str(remote_head).lower(),
        "source_commit": head,
        "source_tree": tree,
        "validated_tree": tree if validation_ok and clean else None,
        "validation_reused": bool(validation_ok and clean),
        "review_reused": bool(review_ok and clean),
        "workspace_clean": clean,
        "capability_observations": cap_status,
        "capability_observations_reused": sorted(fresh),
        "bundle": bundle,
        "bundle_action": "reuse" if bundle else "build",
        "already_published_exactly": already,
        "post_push_success_requirement": "read back target branch and require remote commit == audited source commit and remote tree == audited source tree",
        "transport": "google_drive_git_bundle_to_audited_workspace_import",
        "trigger_rewrite_policy": "the import workflow may use force-with-lease only to replace its own single request trigger commit with the audited source commit",
        "next": (
            "skip transport; continue post-push reconciliation"
            if already
            else (
                "stage reusable Git bundle and run audited Workspace Import"
                if fast
                else "refresh only stale gates, then publish"
            )
        ),
    }
