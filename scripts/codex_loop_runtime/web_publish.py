from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Any

from .change_tracker import sync_generation
from .release_lineage import require_workspace_binding
from .routing_state import permission_observation_status, route_check, route_show
from .workspace import git_head, git_status_porcelain_z, run_git

WEB_PUBLISH_CAPABILITIES = ("github_push", "google_drive_write")
_PUBLISH_CONTINUATION_META = "web_publish_continuation"
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


def _is_local_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    if ancestor == descendant:
        return True
    probe = run_git(root, ["merge-base", "--is-ancestor", ancestor, descendant])
    return probe.returncode == 0


def _commit_has_path(root: Path, commit: str, path: str) -> bool:
    probe = run_git(root, ["cat-file", "-e", f"{commit}:{path}"])
    return probe.returncode == 0


def _workflow_control_plane_updates(root: Path, base: str, head: str) -> list[dict[str, str]]:
    probe = run_git(
        root,
        [
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            f"{base}..{head}",
            "--",
            ".github/workflows",
        ],
    )
    if probe.returncode != 0:
        raise RuntimeError(
            "cannot inspect workflow control-plane delta: "
            + probe.stderr.decode("utf-8", errors="replace").strip()
        )
    paths = sorted(
        path.decode("utf-8", errors="strict")
        for path in probe.stdout.split(b"\0")
        if path
    )
    updates: list[dict[str, str]] = []
    for path in paths:
        remote_exists = _commit_has_path(root, base, path)
        local_exists = _commit_has_path(root, head, path)
        if remote_exists and local_exists:
            action = "update"
        elif local_exists:
            action = "create"
        else:
            action = "delete"
        updates.append({"path": path, "action": action})
    return updates


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


def publish_continuation_state(store: Any) -> dict[str, Any]:
    generation = store.generation()
    raw = store.get_meta(_PUBLISH_CONTINUATION_META)
    if not isinstance(raw, dict):
        return {
            "active": False,
            "generation": generation,
            "reason": "not_started",
            "revalidation_forbidden": False,
        }
    recorded_generation = int(raw.get("generation", -1))
    ready = bool(raw.get("ready", False))
    active = ready and recorded_generation == generation
    return {
        **raw,
        "active": active,
        "generation": generation,
        "recorded_generation": recorded_generation,
        "reason": "fresh_publish_only_continuation" if active else "stale_or_not_ready",
        "revalidation_forbidden": bool(active and raw.get("revalidation_forbidden", False)),
    }


def begin_web_publish_continuation(
    root: Path, store: Any, *, repository: str, branch: str
) -> dict[str, Any]:
    """Freeze a publish-only continuation onto fresh content evidence.

    A terse push/publish request after source work is delivery intent, not a semantic
    objective steer. If the workspace is clean and validation/review are already fresh,
    later validation planning is rejected until content changes.
    """
    root = root.resolve()
    store.ensure_active()
    sync_generation(root, store)
    clean = _workspace_clean(root)
    validation_ok, validation = _validation_fresh(store)
    review_ok, review = _review_fresh(store)
    generation = store.generation()
    ready = bool(clean and validation_ok and review_ok)
    state = {
        "version": 1,
        "kind": "publish_only",
        "repository": str(repository).strip(),
        "branch": str(branch).strip(),
        "generation": generation,
        "ready": ready,
        "workspace_clean": clean,
        "validation_reused": bool(validation_ok and clean),
        "review_reused": bool(review_ok and clean),
        "revalidation_forbidden": ready,
        "semantic_plan_change": False,
    }
    store.set_meta(_PUBLISH_CONTINUATION_META, state)
    return {
        **state,
        "active": ready,
        "validation": validation,
        "review": review,
        "next": (
            "observe the exact remote head/tree and scoped capability freshness, then run web-publish-plan; do not run validation again"
            if ready
            else "refresh only the stale publish gate(s), then begin the publish-only continuation again"
        ),
    }


def _current_bundle_receipt(
    root: Path, store: Any, *, prerequisite_commit: str | None = None
) -> dict[str, Any] | None:
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
        or (receipt.get("prerequisite_commit") or None) != (prerequisite_commit or None)
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
    require_workspace_binding(root, store)
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
        cursor = head
        first_parent_match = False
        for _ in range(256):
            parent_probe = run_git(root, ["rev-parse", f"{cursor}^"])
            if parent_probe.returncode != 0:
                break
            parent_sha = parent_probe.stdout.decode("utf-8", errors="replace").strip()
            if parent_sha == prerequisite:
                first_parent_match = True
                break
            cursor = parent_sha
        if not first_parent_match:
            ancestor = run_git(root, ["merge-base", "--is-ancestor", prerequisite, head])
            if ancestor.returncode != 0:
                raise RuntimeError("Web publish bundle prerequisite must be a locally provable ancestor of audited HEAD")
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
    verified_tree_fast_path: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    store.ensure_active()
    sync_generation(root, store)
    require_workspace_binding(root, store)
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
    continuation = publish_continuation_state(store)
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
    remote_head_normalized = str(remote_head).lower()
    remote_tree_normalized = str(remote_tree).lower()
    already = remote_head_normalized == head.lower() and remote_tree_normalized == tree.lower()
    remote_is_local_ancestor = _is_local_ancestor(root, remote_head_normalized, head)
    fast_workflow_path = ".github/workflows/workspace-import-fast.yml"
    standard_workflow_path = ".github/workflows/workspace-import.yml"
    remote_has_fast_workflow = _commit_has_path(root, remote_head_normalized, fast_workflow_path)
    remote_has_standard_workflow = _commit_has_path(root, remote_head_normalized, standard_workflow_path)
    local_has_fast_workflow = _commit_has_path(root, head, fast_workflow_path)
    workflow_updates = (
        _workflow_control_plane_updates(root, remote_head_normalized, head)
        if remote_is_local_ancestor and not already
        else []
    )
    workflow_update_paths = {entry["path"] for entry in workflow_updates}
    desired_prerequisite = None if already else (remote_head_normalized if remote_is_local_ancestor else None)
    if not already and not remote_is_local_ancestor:
        reasons.append("remote_head_not_local_ancestor")
    if (
        not already
        and not remote_has_fast_workflow
        and not (local_has_fast_workflow and fast_workflow_path in workflow_update_paths)
    ):
        reasons.append("fast_import_workflow_not_in_remote_base")
    control_plane_refresh_required = bool(
        verified_tree_fast_path
        and workflow_updates
        and clean
        and validation_ok
        and review_ok
        and all_fresh
        and remote_is_local_ancestor
        and not reasons
    )
    fast = not reasons and not control_plane_refresh_required
    refreshable_reasons = {
        "validation_not_fresh",
        "change_review_not_fresh",
        "capability_observations_not_fresh",
    }
    surprise_reasons = [
        reason
        for reason in reasons
        if reason not in refreshable_reasons
        and reason != "verified_tree_fast_path_not_requested"
    ]
    refresh_required = bool(
        verified_tree_fast_path
        and reasons
        and not surprise_reasons
        and clean
        and not already
    )
    fail_closed = bool(
        verified_tree_fast_path
        and reasons
        and not refresh_required
        and (not already or not clean)
    )
    design_repair_required = bool(fail_closed and surprise_reasons)
    bundle = _current_bundle_receipt(root, store, prerequisite_commit=desired_prerequisite)
    bundle_strategy = (
        "reuse_exact_bundle" if bundle else
        "thin_from_remote_head" if desired_prerequisite else
        "full_verified_bundle"
    )
    if refresh_required:
        mode = "FAST_PUBLISH_REFRESH_REQUIRED"
    elif fail_closed:
        mode = "FAIL_CLOSED"
    elif already:
        mode = "ALREADY_PUBLISHED"
    elif control_plane_refresh_required:
        mode = "FAST_PUBLISH_CONTROL_PLANE_REFRESH_REQUIRED"
    elif fast:
        mode = "FAST_PUBLISH"
    else:
        mode = "FULL_VERIFIED_PUBLISH"
    transport_ready = mode in {"FAST_PUBLISH", "FULL_VERIFIED_PUBLISH"}
    workflow_path = (
        fast_workflow_path
        if mode == "FAST_PUBLISH"
        else ".github/workflows/workspace-import.yml"
        if mode == "FULL_VERIFIED_PUBLISH"
        else None
    )
    request_directory = (
        ".github/fast-import-requests"
        if mode == "FAST_PUBLISH"
        else ".github/import-requests"
        if mode == "FULL_VERIFIED_PUBLISH"
        else None
    )
    receipt_mode = (
        "structured_log_with_published_source_artifact"
        if mode == "FAST_PUBLISH"
        else "artifact"
        if mode == "FULL_VERIFIED_PUBLISH"
        else None
    )
    stale_capabilities = [
        capability
        for capability, status in cap_status.items()
        if not status.get("fresh")
    ]
    required_refresh_actions: list[str] = []
    if "validation_not_fresh" in reasons:
        required_refresh_actions.append("refresh_validation_only")
    if "change_review_not_fresh" in reasons:
        required_refresh_actions.append("refresh_change_review_only")
    if "capability_observations_not_fresh" in reasons:
        required_refresh_actions.extend(
            f"refresh_capability:{capability}" for capability in stale_capabilities
        )

    recovery_options: list[dict[str, Any]] = []
    recommended_recovery = "retry_fast" if refresh_required else None
    if fail_closed:
        standard_ready_now = bool(clean and validation_ok and review_ok and all_fresh and remote_has_standard_workflow)
        recovery_options = [
            {
                "id": "retry_fast",
                "keeps_workspace_mode": "web",
                "requires_explicit_user_selection": False,
                "ready_now": not bool(surprise_reasons),
                "requirements": ["refresh stale gates" if not surprise_reasons else "repair fast-path structural blocker before retry"],
                "next": "re-run web-publish-plan; FAST_PUBLISH is the default",
            },
            {
                "id": "standard_web",
                "keeps_workspace_mode": "web",
                "requires_explicit_user_selection": True,
                "ready_now": standard_ready_now,
                "requirements": (["remote audited .github/workflows/workspace-import.yml"] if not remote_has_standard_workflow else [])
                + ([] if clean and validation_ok and review_ok and all_fresh else ["clean workspace and fresh validation/review/capability gates"]),
                "next": "re-run web-publish-plan with --standard-web after explicit user selection",
                "transport": "full_verified_git_bundle_via_google_drive",
            },
            {
                "id": "local_handoff",
                "keeps_workspace_mode": "local_after_explicit_transition",
                "requires_explicit_user_selection": True,
                "ready_now": False,
                "requirements": ["explicit Local selection", "RDC-authorized LOCAL_ROOT", "verified binary Git-bundle handoff"],
                "next": "follow references/web-to-local-handoff.md, then publish with native Git",
                "transport": "verified_binary_git_bundle; never model source regeneration",
            },
        ]
        if not surprise_reasons:
            recommended_recovery = "retry_fast"
        else:
            recommended_recovery = "standard_web"
        next_action = (
            "stop before transport; present the modeled recovery options and require explicit user selection for any fallback; "
            f"recommended={recommended_recovery}"
        )
    elif refresh_required:
        next_action = (
            "refresh only required_refresh_actions, then re-run the default FAST_PUBLISH planner; "
            "do not run FULL_VERIFIED_PUBLISH, standard importer, production packaging, or already-fresh gates before retry"
        )
    elif already:
        next_action = "skip transport; continue post-push reconciliation"
    elif mode == "FAST_PUBLISH_CONTROL_PLANE_REFRESH_REQUIRED":
        next_action = (
            "stop before bundle staging/request creation; update only control_plane_workflow_updates through the GitHub Connector "
            "against the exact observed branch head, then observe the resulting remote commit/tree and reacquire that exact "
            "control-plane revision through Workspace Download (or another approved exact acquisition path). Reapply only the "
            "remaining non-workflow source delta in the fresh Web workspace, prove the resulting complete source tree equals the "
            "previously audited source tree before any new semantic edit, then rerun the default FAST_PUBLISH planner"
        )
    elif mode == "FAST_PUBLISH":
        next_action = (
            "build exactly one thin Git bundle from expected_base, stage it, and run audited Workspace Import Fast"
            if desired_prerequisite and not bundle
            else "stage the exact reusable Git bundle and run audited Workspace Import Fast"
        )
    else:
        next_action = "build the explicitly selected standard verified Git bundle and run audited Workspace Import"
    return {
        "mode": mode,
        "planner_default": "FAST_PUBLISH",
        "fast_path_ready": fast,
        "fast_path_refresh_required": refresh_required,
        "control_plane_refresh_required": control_plane_refresh_required,
        "control_plane_workflow_updates": workflow_updates,
        "control_plane_refresh_reason": (
            "github_actions_token_cannot_publish_workflow_file_changes"
            if control_plane_refresh_required
            else None
        ),
        "control_plane_reacquisition_required": control_plane_refresh_required,
        "required_refresh_actions": required_refresh_actions,
        "stale_capabilities": stale_capabilities,
        "forbidden_before_fast_retry": (
            [
                "FULL_VERIFIED_PUBLISH",
                "workspace-import.yml",
                "production_skill_packaging",
                "repeat_fresh_validation",
                "repeat_fresh_change_review",
                "repeat_fresh_permission_probe",
            ]
            if refresh_required
            else []
        ),
        "fail_closed": fail_closed,
        "design_repair_required": design_repair_required,
        "surprise_reasons": surprise_reasons,
        "fallback_allowed": bool(fail_closed),
        "fallback_requires_explicit_user_selection": bool(fail_closed),
        "fallback_options": recovery_options,
        "recommended_recovery": recommended_recovery,
        "standard_publish_explicitly_selected": not bool(verified_tree_fast_path),
        "fallback_reasons": reasons,
        "blocking_reasons": reasons,
        "repository": repository,
        "branch": branch,
        "expected_base": remote_head_normalized,
        "source_commit": head,
        "source_tree": tree,
        "validated_tree": tree if validation_ok and clean else None,
        "validation_reused": bool(validation_ok and clean),
        "review_reused": bool(review_ok and clean),
        "publish_continuation": continuation,
        "redundant_validation_forbidden": bool(continuation.get("revalidation_forbidden", False)),
        "workspace_clean": clean,
        "capability_observations": cap_status,
        "capability_observations_reused": sorted(fresh),
        "host_permission_capabilities_required": list(WEB_PUBLISH_CAPABILITIES),
        "github_actions_runtime_proof": {
            "required": not already,
            "mode": "matching_push_triggered_import_run",
            "rule": (
                "GitHub Actions is not a host write-permission preflight for Web publication because the importer is "
                "triggered by the request push. After the request commit, require the matching import workflow run, "
                "its verified receipt/log evidence, and exact remote commit/tree readback before SOURCE_PUSHED."
            ),
        },
        "bundle": bundle,
        "bundle_action": ("reuse" if bundle else "build") if transport_ready else None,
        "bundle_strategy": bundle_strategy if transport_ready else None,
        "bundle_build_prerequisite_commit": desired_prerequisite if transport_ready else None,
        "remote_head_is_local_ancestor": remote_is_local_ancestor,
        "remote_has_fast_import_workflow": remote_has_fast_workflow,
        "local_has_fast_import_workflow": local_has_fast_workflow,
        "remote_has_standard_import_workflow": remote_has_standard_workflow,
        "already_published_exactly": already,
        "fast_path_budget": {
            "permission_smoke_probes": 0 if fast else None,
            "validation_commands": 0 if fast else None,
            "change_review_repeats": 0 if fast else None,
            "full_bundle_attempts": 0 if fast and desired_prerequisite else None,
            "production_packaging_steps": 0 if fast else None,
            "bundle_build_attempts": 0 if bundle else (1 if fast else None),
            "workflow_artifact_uploads": 1 if fast else None,
        },
        "workflow_path": workflow_path,
        "request_directory": request_directory,
        "receipt_mode": receipt_mode,
        "post_push_success_requirement": "read back target branch and require remote commit == audited source commit and remote tree == audited source tree",
        "remote_source_object_presence_required": False,
        "remote_source_object_absence_is_blocker": False,
        "source_object_introduction": "the verified Git bundle carries the audited source commit object into the importer; GitHub need not already contain that object",
        "transport": "google_drive_git_bundle_to_audited_workspace_import",
        "trigger_rewrite_policy": "the import workflow may use force-with-lease only to replace its own single request trigger commit with the audited source commit",
        "next": next_action,
    }


def web_local_sync_plan(
    root: Path,
    store: Any,
    *,
    session_id: str,
    destination_path: str,
    workspace_granted: bool = False,
    local_computer_authorized: bool = False,
) -> dict[str, Any]:
    """Plan the only supported Web -> local/Mac binary synchronization path.

    This is a downstream transfer while Web remains authoritative. It deliberately does
    not route through GitHub artifacts and does not transition workspace_mode to local.
    """
    root = root.resolve()
    store.ensure_active()
    sync_generation(root, store)
    require_workspace_binding(root, store)
    route = route_show(session_id=session_id)
    if route.get("workspace_mode") != "web":
        return {
            "mode": "WEB_LOCAL_SYNC_BLOCKED",
            "code": "WEB_LOCAL_SYNC_REQUIRES_WEB_MODE",
            "workspace_mode": route.get("workspace_mode"),
            "workspace_authority_unchanged": True,
            "next": "use the ordinary Local repository contract; do not reinterpret a Local task as Web-to-Local synchronization",
        }

    destination = str(destination_path).strip()
    if not destination:
        raise ValueError("destination_path is required")

    clean = _workspace_clean(root)
    validation_ok, validation = _validation_fresh(store)
    review_ok, review = _review_fresh(store)
    head, tree = _head_tree(root)
    reasons: list[str] = []
    if not clean:
        reasons.append("workspace_not_clean")
    if not validation_ok:
        reasons.append("validation_not_fresh")
    if not review_ok:
        reasons.append("change_review_not_fresh")

    transfer_gate = route_check(
        action="rdc_transfer",
        session_id=session_id,
        workspace_granted=workspace_granted,
        local_computer_authorized=local_computer_authorized,
    )
    if not transfer_gate.get("allowed"):
        reasons.extend(str(item) for item in transfer_gate.get("requirements") or [])

    bundle = _current_bundle_receipt(root, store, prerequisite_commit=None)
    ready = not reasons
    return {
        "mode": "WEB_LOCAL_SYNC_READY" if ready else "WEB_LOCAL_SYNC_BLOCKED",
        "code": "WEB_LOCAL_SYNC_PLAN_READY" if ready else "WEB_LOCAL_SYNC_REQUIREMENTS_UNMET",
        "workspace_mode": "web",
        "workspace_authority_unchanged": True,
        "source_commit": head,
        "source_tree": tree,
        "workspace_clean": clean,
        "validation": validation,
        "review": review,
        "destination_path": destination,
        "requirements": reasons,
        "bundle": bundle,
        "bundle_action": ("reuse" if bundle else "build_self_contained") if ready else None,
        "bundle_build_prerequisite_commit": None,
        "transport": {
            "id": "google_drive_then_rdc_download",
            "ordered_steps": [
                "build_or_reuse_exact_self_contained_git_bundle",
                "upload_binary_bundle_to_dedicated_google_drive_staging_via_file_uri",
                "verify_drive_object_id_size_and_sha256",
                "expose_only_the_minimum_temporary_download_access_needed_by_the_authorized_host",
                "rdc_download_exact_binary_to_authorized_destination_path",
                "verify_local_size_sha256_and_git_bundle_verify",
                "delete_exact_drive_staging_object_after_verified_local_consumption",
            ],
            "fixed": True,
        },
        "rdc_route": transfer_gate,
        "forbidden_fallbacks": [
            "github_actions_artifact",
            "github_repository_archive",
            "github_contents_or_object_source_relay",
            "direct_unmodeled_binary_bridge",
            "model_carried_base64_or_chunk_relay",
            "source_regeneration_or_retyping",
        ],
        "next": (
            "execute the fixed Drive -> RDC binary transfer exactly as planned; keep workspace_mode=web after the copy. "
            "Only a separate explicit user request to continue development from the local repository may trigger a later route-transition to Local mode."
            if ready
            else "satisfy only the listed transfer/audit requirements, then rerun web-local-sync-plan; do not choose another transfer path"
        ),
    }
