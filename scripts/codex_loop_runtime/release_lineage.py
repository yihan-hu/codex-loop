from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .workspace import git_branch, git_head, git_state, is_git_repo, run_git

_SHA_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")

CONNECTOR_INLINE_MAX_ENTRY_BYTES = 128 * 1024
CONNECTOR_INLINE_MAX_TOTAL_BYTES = 512 * 1024
CONNECTOR_INLINE_MAX_ENTRIES = 128
MODEL_DISPATCH_BATCH_MAX_ITEMS = 8
MODEL_DISPATCH_BATCH_MAX_RAW_BYTES = 96 * 1024


def _git_text(root: Path, args: list[str], *, required: bool = True) -> str | None:
    proc = run_git(root, args)
    if proc.returncode != 0:
        if required:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Git probe failed for {' '.join(args)}: {stderr or proc.returncode}")
        return None
    return proc.stdout.decode("utf-8", errors="surrogateescape").strip()


def _resolve_git_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _origin_hint(raw: str | None) -> str | None:
    """Return a credential-free remote hint, never a raw remote URL."""
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if "://" in value:
        parsed = urlsplit(value)
        if not parsed.hostname:
            return None
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return f"{parsed.hostname}/{path}" if path else parsed.hostname
    match = re.match(r"^(?:[^@/]+@)?([^:/]+):(.+)$", value)
    if match:
        host, path = match.groups()
        path = path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return f"{host}/{path}" if path else host
    return None


def _validate_sha(value: str, *, field: str) -> str:
    clean = str(value).strip().lower()
    if not _SHA_RE.fullmatch(clean):
        raise ValueError(f"{field} must be a full hexadecimal Git object id")
    return clean


def _commit_tree(root: Path, commit: str) -> str:
    value = _git_text(root, ["rev-parse", f"{commit}^{{tree}}"])
    assert value is not None
    return _validate_sha(value, field="tree")


def _commit_metadata(root: Path, commit: str) -> dict[str, Any]:
    fmt = "%H%x00%T%x00%P%x00%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI%x00%B"
    raw = _git_text(root, ["show", "-s", f"--format={fmt}", commit]) or ""
    parts = raw.split("\x00", 9)
    if len(parts) != 10:
        raise RuntimeError("could not parse Git commit metadata")
    sha, tree, parents, an, ae, ad, cn, ce, cd, message = parts
    return {
        "commit": _validate_sha(sha, field="commit"),
        "tree": _validate_sha(tree, field="tree"),
        "parents": [x for x in parents.split() if x],
        "author": {"name": an, "email": ae, "date": ad},
        "committer": {"name": cn, "email": ce, "date": cd},
        "message": message.rstrip("\n"),
    }


def capture_workspace_binding(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if not is_git_repo(root):
        return {
            "schema_version": 1,
            "canonical_root": str(root),
            "is_git": False,
            "repository_id": None,
            "base_commit": None,
            "base_tree": None,
            "initial_branch": None,
            "linked_worktree": False,
            "origin_hint": None,
        }
    common_raw = _git_text(root, ["rev-parse", "--git-common-dir"])
    git_dir_raw = _git_text(root, ["rev-parse", "--git-dir"])
    assert common_raw is not None and git_dir_raw is not None
    common_dir = _resolve_git_path(root, common_raw)
    git_dir = _resolve_git_path(root, git_dir_raw)
    head = git_head(root)
    tree = _commit_tree(root, head) if head else None
    branch = git_branch(root)
    origin = _git_text(root, ["config", "--get", "remote.origin.url"], required=False)
    repository_id = hashlib.sha256(str(common_dir).encode("utf-8", errors="surrogateescape")).hexdigest()[:24]
    return {
        "schema_version": 1,
        "canonical_root": str(root),
        "is_git": True,
        "repository_id": repository_id,
        "base_commit": head,
        "base_tree": tree,
        "initial_branch": branch,
        "linked_worktree": git_dir != common_dir,
        "origin_hint": _origin_hint(origin),
    }


def workspace_binding_status(root: Path, binding: dict[str, Any] | None) -> dict[str, Any]:
    root = root.resolve()
    if not binding:
        return {"bound": False, "matches": False, "reason": "task has no canonical workspace binding"}
    current = capture_workspace_binding(root)
    reasons: list[str] = []
    if str(binding.get("canonical_root")) != str(root):
        reasons.append("canonical root changed")
    if bool(binding.get("is_git")) != bool(current.get("is_git")):
        reasons.append("Git repository status changed")
    if binding.get("repository_id") != current.get("repository_id"):
        reasons.append("Git repository identity changed")
    return {
        "bound": True,
        "matches": not reasons,
        "reasons": reasons,
        "binding": binding,
        "current": current,
    }


def require_workspace_binding(root: Path, store: Any) -> dict[str, Any]:
    binding = store.get_meta("workspace_binding")
    status = workspace_binding_status(root, binding)
    if not status.get("bound"):
        raise RuntimeError("task predates canonical workspace binding; bootstrap a new task in the canonical Git working tree")
    if not status.get("matches"):
        raise RuntimeError("canonical workspace binding mismatch: " + "; ".join(status.get("reasons", [])))
    return dict(status["binding"])


def _tracked_dirty(root: Path) -> bool:
    proc = run_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=no"])
    if proc.returncode != 0:
        raise RuntimeError("could not determine tracked Git cleanliness")
    return bool(proc.stdout)


def _untracked_paths(root: Path, limit: int = 24) -> tuple[list[str], int]:
    state = git_state(root)
    paths = [str(item.get("path", "")) for item in state.get("status", []) if item.get("kind") == "untracked"]
    paths = sorted(x for x in paths if x)
    return paths[:limit], max(0, len(paths) - limit)


def release_plan(root: Path, store: Any, *, artifact_name: str, archive_prefix: str | None = None) -> dict[str, Any]:
    from .change_tracker import sync_generation

    root = root.resolve()
    store.ensure_active()
    sync_generation(root, store)
    binding = require_workspace_binding(root, store)
    if not binding.get("is_git"):
        raise RuntimeError("commit-bound release planning requires a Git working tree")
    if _tracked_dirty(root):
        raise RuntimeError("tracked or staged changes are not committed; release source must be the bound Git HEAD")
    head = git_head(root)
    if not head:
        raise RuntimeError("release source has no Git HEAD commit")
    tree = _commit_tree(root, head)
    untracked, truncated = _untracked_paths(root)
    prefix = (archive_prefix or "").strip()
    if prefix:
        if prefix.startswith("/") or ".." in Path(prefix).parts:
            raise ValueError("archive prefix must be a relative safe path")
        if not prefix.endswith("/"):
            prefix += "/"
    archive_argv = ["git", "archive", "--format=tar"]
    if prefix:
        archive_argv.extend(["--prefix", prefix])
    archive_argv.append(head)
    return {
        "ready": True,
        "source": {
            "canonical_root": str(root),
            "repository_id": binding.get("repository_id"),
            "branch": git_branch(root),
            "commit": head,
            "tree": tree,
            "generation": store.generation(),
        },
        "artifact": {"name": artifact_name},
        "archive": {
            "requires_host_visible_execution": True,
            "cwd": str(root),
            "argv": archive_argv,
            "staging_policy": "extract into a disposable directory outside the canonical working tree; never use staging or the artifact as a future development baseline",
        },
        "excluded_untracked": {"paths": untracked, "truncated": truncated},
        "commit_metadata": _commit_metadata(root, head),
    }


def record_release_receipt(
    root: Path,
    store: Any,
    *,
    artifact_name: str,
    artifact_sha256: str,
    evidence: str,
) -> dict[str, Any]:
    plan = release_plan(root, store, artifact_name=artifact_name)
    digest = str(artifact_sha256).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("artifact SHA-256 must be 64 lowercase hexadecimal characters")
    clean_evidence = str(evidence).strip()
    if not clean_evidence:
        raise ValueError("release receipt requires concise artifact verification evidence")
    source = plan["source"]
    receipt = store.record_release_receipt(
        release_id=uuid.uuid4().hex,
        generation=int(source["generation"]),
        source_commit=str(source["commit"]),
        source_tree=str(source["tree"]),
        artifact_name=str(artifact_name),
        artifact_sha256=digest,
        evidence=clean_evidence,
    )
    return receipt


def current_release_receipt(root: Path, store: Any, release_id: str | None = None) -> dict[str, Any]:
    from .change_tracker import sync_generation

    root = root.resolve()
    sync_generation(root, store)
    require_workspace_binding(root, store)
    receipt = store.release_receipt(release_id) if release_id else store.latest_release_receipt()
    if receipt is None:
        raise RuntimeError("no release receipt is recorded for this task")
    current_head = git_head(root)
    current_tree = _commit_tree(root, current_head) if current_head else None
    current = (
        int(receipt["generation"]) == store.generation()
        and receipt["source_commit"] == current_head
        and receipt["source_tree"] == current_tree
        and not _tracked_dirty(root)
    )
    return {**receipt, "current": current, "current_generation": store.generation(), "current_commit": current_head, "current_tree": current_tree}


def _object_type_for_mode(mode: str) -> str:
    if mode == "160000":
        return "commit"
    return "blob"


def diff_object_manifest(root: Path, base_commit: str, target_commit: str) -> list[dict[str, Any]]:
    base = _validate_sha(base_commit, field="base commit")
    target = _validate_sha(target_commit, field="target commit")
    proc = run_git(root, ["diff-tree", "-r", "--raw", "--no-commit-id", "--no-renames", "-z", base, target])
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"cannot derive Git object manifest: {stderr or proc.returncode}")
    parts = proc.stdout.split(b"\0")
    result: list[dict[str, Any]] = []
    i = 0
    while i < len(parts):
        meta = parts[i]
        i += 1
        if not meta:
            continue
        if i >= len(parts):
            raise RuntimeError("malformed git diff-tree output")
        path = parts[i].decode("utf-8", errors="surrogateescape")
        i += 1
        fields = meta.decode("ascii", errors="strict").split()
        if len(fields) != 5 or not fields[0].startswith(":"):
            raise RuntimeError("malformed git diff-tree metadata")
        old_mode = fields[0][1:]
        new_mode, old_sha, new_sha, status = fields[1], fields[2], fields[3], fields[4]
        delete = new_mode == "000000"
        tree_mode = old_mode if delete else new_mode
        item: dict[str, Any] = {
            "path": path,
            "status": status,
            "old_mode": old_mode,
            "new_mode": new_mode,
            "old_sha": old_sha,
            "new_sha": new_sha,
            "object_type": _object_type_for_mode(new_mode),
            "delete": delete,
            "tree_mode": tree_mode,
            "tree_type": _object_type_for_mode(tree_mode),
        }
        if not item["delete"] and item["object_type"] == "blob":
            size_text = _git_text(root, ["cat-file", "-s", new_sha])
            item["size"] = int(size_text or "0")
        result.append(item)
    return result


def _git_blob_bytes(root: Path, object_id: str) -> bytes:
    sha = _validate_sha(object_id, field="blob")
    proc = run_git(root, ["cat-file", "blob", sha])
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"cannot read Git blob {sha}: {stderr or proc.returncode}")
    return bytes(proc.stdout)


def classify_connector_manifest(root: Path, manifest: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Choose the lowest-RPC faithful connector transfer for each Git-determined path."""
    classified: list[dict[str, Any]] = []
    inline_bytes = 0
    inline_count = 0
    create_blob_bytes = 0
    create_blob_count = 0
    delete_count = 0

    for source in manifest:
        item = dict(source)
        if item.get("delete"):
            item["transfer"] = "tree_delete"
            item["transfer_reason"] = "delete_in_create_tree"
            delete_count += 1
            classified.append(item)
            continue
        if item.get("object_type") != "blob":
            item["transfer"] = "unsupported"
            item["transfer_reason"] = "unsupported_git_object_type"
            classified.append(item)
            continue

        size = int(item.get("size") or 0)
        reason: str | None = None
        if size > CONNECTOR_INLINE_MAX_ENTRY_BYTES:
            reason = "entry_too_large"
        elif inline_count >= CONNECTOR_INLINE_MAX_ENTRIES:
            reason = "inline_entry_budget_exceeded"
        elif inline_bytes + size > CONNECTOR_INLINE_MAX_TOTAL_BYTES:
            reason = "inline_byte_budget_exceeded"
        else:
            data = _git_blob_bytes(root, str(item["new_sha"]))
            if len(data) != size:
                raise RuntimeError(f"Git blob size changed while classifying connector transfer: {item['path']}")
            if b"\x00" in data:
                reason = "contains_nul"
            else:
                try:
                    text = data.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    reason = "non_utf8"
                else:
                    if text.encode("utf-8") != data:
                        raise RuntimeError(f"UTF-8 round-trip changed Git blob bytes: {item['path']}")
                    item["transfer"] = "inline_utf8"
                    item["transfer_reason"] = "eligible_for_batched_create_tree_content"
                    item["content_source"] = f"git_blob:{item['new_sha']}"
                    inline_bytes += size
                    inline_count += 1

        if "transfer" not in item:
            item["transfer"] = "create_blob"
            item["transfer_reason"] = reason or "not_inline_eligible"
            item["content_source"] = f"git_blob:{item['new_sha']}"
            create_blob_bytes += size
            create_blob_count += 1
        classified.append(item)

    summary = {
        "inline_utf8": {
            "count": inline_count,
            "bytes": inline_bytes,
            "max_entry_bytes": CONNECTOR_INLINE_MAX_ENTRY_BYTES,
            "max_total_bytes": CONNECTOR_INLINE_MAX_TOTAL_BYTES,
            "max_entries": CONNECTOR_INLINE_MAX_ENTRIES,
        },
        "create_blob": {"count": create_blob_count, "bytes": create_blob_bytes},
        "tree_delete": {"count": delete_count},
        "estimated_connector_writes_before_commit": create_blob_count + 1,
    }
    return classified, summary


def _ancestor_status(root: Path, ancestor: str, descendant: str) -> bool:
    proc = run_git(root, ["merge-base", "--is-ancestor", ancestor, descendant])
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()
    raise RuntimeError(f"cannot determine Git ancestry: {stderr or proc.returncode}")


def _require_publish_audit_readiness(store: Any) -> None:
    generation = store.generation()
    if bool(store.get_meta("requires_validation", True)):
        validation = store.validation_state_for_generation(generation)
        if int(validation.get("passed_count", 0)) < 1 or int(validation.get("failed_count", 0)) > 0:
            raise RuntimeError("publish requires current-generation passing validation with no unresolved blocking validation failure")
    if generation > 0 and int(store.get_meta("changes_reviewed_generation", -1)) != generation:
        raise RuntimeError("publish requires the final change set to be reviewed at the current generation")


def publish_plan(
    root: Path,
    store: Any,
    *,
    repository: str,
    branch: str,
    remote_head: str,
    remote_tree: str | None = None,
    remote: str = "origin",
    release_id: str | None = None,
) -> dict[str, Any]:
    store.ensure_active()
    receipt = current_release_receipt(root, store, release_id)
    _require_publish_audit_readiness(store)
    if not receipt.get("current"):
        raise RuntimeError("release receipt is stale; rebuild/re-record from the current canonical Git HEAD before publishing")
    repo_name = str(repository).strip()
    branch_name = str(branch).strip()
    remote_name = str(remote).strip() or "origin"
    if not repo_name or not branch_name:
        raise ValueError("repository and branch are required")
    observed_head = _validate_sha(remote_head, field="remote head")
    observed_tree = _validate_sha(remote_tree, field="remote tree") if remote_tree else None
    target_commit = str(receipt["source_commit"])
    target_tree = str(receipt["source_tree"])
    if observed_head == target_commit:
        if observed_tree and observed_tree != target_tree:
            raise RuntimeError("observed remote tree conflicts with the audited target commit")
        return {
            "ready": True,
            "already_published": True,
            "repository": repo_name,
            "branch": branch_name,
            "remote_head": observed_head,
            "target_commit": target_commit,
            "target_tree": target_tree,
        }
    if not _ancestor_status(root, observed_head, target_commit):
        return {
            "ready": False,
            "requires_integration": True,
            "reason": "observed remote head is not an ancestor of the audited local release; fetch/integrate remote changes in this canonical worktree before publishing",
            "repository": repo_name,
            "branch": branch_name,
            "remote_head": observed_head,
            "target_commit": target_commit,
            "target_tree": target_tree,
        }
    local_remote_tree = _commit_tree(root, observed_head)
    if observed_tree and observed_tree != local_remote_tree:
        raise RuntimeError("observed remote tree does not match the locally known remote-head commit")
    raw_manifest = diff_object_manifest(root, observed_head, target_commit)
    manifest, transfer_summary = classify_connector_manifest(root, raw_manifest)
    unsupported = [item["path"] for item in manifest if item["transfer"] == "unsupported"]
    configured = _git_text(root, ["remote", "get-url", remote_name], required=False) is not None
    action_identity = f"{repo_name}#{branch_name}@{target_commit}"
    action_id = store.record_external(
        "repository_publish",
        "planned",
        action_identity,
        {
            "repository": repo_name,
            "branch": branch_name,
            "release_id": receipt["release_id"],
            "source_commit": target_commit,
            "source_tree": target_tree,
            "expected_remote_head": observed_head,
            "github_object_api_available": not unsupported,
            "github_object_api_unsupported_paths": unsupported,
        },
        action_class="external_non_idempotent",
    )
    return {
        "ready": True,
        "already_published": False,
        "action_id": action_id,
        "release_id": receipt["release_id"],
        "repository": repo_name,
        "branch": branch_name,
        "precondition": {"remote_head_must_remain": observed_head},
        "target": {"commit": target_commit, "tree": target_tree},
        "transport_order": ["git", "github_object_api"],
        "git": {
            "preferred": True,
            "configured_remote": configured,
            "requires_host_visible_execution": True,
            "cwd": str(root.resolve()),
            "argv": ["git", "push", "--porcelain", remote_name, f"{target_commit}:refs/heads/{branch_name}"],
            "success_requirement": "read back the remote ref and require remote commit == audited local release commit",
        },
        "github_object_api": {
            "fallback": True,
            "available": not unsupported,
            "requires_remote_tree": False,
            "base_tree": observed_tree or local_remote_tree,
            "base_tree_source": "observed_remote" if observed_tree else "local_remote_head_commit",
            "target_tree": target_tree,
            "parent_commit": observed_head,
            "changed_objects": manifest,
            "transfer_summary": transfer_summary,
            "unsupported_paths": unsupported,
            "model_dispatcher": {
                "available": not unsupported,
                "purpose": "short-term host fallback when connector calls are serialized through the model and file-backed/bulk connector actions are unavailable",
                "batch_max_items": MODEL_DISPATCH_BATCH_MAX_ITEMS,
                "batch_max_raw_bytes": MODEL_DISPATCH_BATCH_MAX_RAW_BYTES,
                "start_after_dispatch": ["publish-transfer-start", "publish-transfer-status", "publish-transfer-ack", "publish-transfer-tree-ack"],
                "strategy": "upload every changed blob from exact Git object bytes as base64 in bounded create_blob batches; verify returned SHAs; then create exactly one tree",
            },
            "rule": "materialize inline_utf8 content from the exact target Git blob objects and send all eligible entries in one create_tree request when the host can carry that payload efficiently; otherwise use the bounded model-dispatch queue; always require the resulting tree SHA to equal target_tree before creating one commit and performing one non-force ref update",
            "commit_metadata": _commit_metadata(root, target_commit),
        },
    }


def _model_dispatch_queue_metadata(root: Path, base_commit: str, target_commit: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    manifest = diff_object_manifest(root, base_commit, target_commit)
    blobs: list[dict[str, Any]] = []
    tree_elements: list[dict[str, Any]] = []
    digest_items: list[dict[str, Any]] = []
    for item in manifest:
        path = str(item["path"])
        tree_mode = str(item["tree_mode"])
        tree_type = str(item["tree_type"])
        if item.get("delete"):
            tree_elements.append({"path": path, "mode": tree_mode, "type": tree_type, "sha": None})
            digest_items.append({"path": path, "mode": tree_mode, "type": tree_type, "sha": None})
            continue
        if item.get("object_type") != "blob":
            raise RuntimeError(f"model-dispatch connector queue does not support Git object type {item.get('object_type')}: {path}")
        expected_sha = _validate_sha(str(item["new_sha"]), field="blob")
        size = int(item.get("size") or 0)
        blobs.append({
            "index": len(blobs),
            "path": path,
            "expected_sha": expected_sha,
            "size": size,
            "mode": tree_mode,
            "type": tree_type,
        })
        tree_elements.append({"path": path, "mode": tree_mode, "type": tree_type, "sha": expected_sha})
        digest_items.append({"path": path, "mode": tree_mode, "type": tree_type, "sha": expected_sha, "size": size})
    digest_payload = {
        "base_commit": _validate_sha(base_commit, field="base commit"),
        "target_commit": _validate_sha(target_commit, field="target commit"),
        "items": digest_items,
    }
    queue_digest = hashlib.sha256(
        json.dumps(digest_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return blobs, tree_elements, queue_digest


def _model_dispatch_batch(blobs: list[dict[str, Any]], cursor: int) -> list[dict[str, Any]]:
    if cursor < 0 or cursor > len(blobs):
        raise RuntimeError("model-dispatch queue cursor is outside the current Git-derived queue")
    batch: list[dict[str, Any]] = []
    raw_bytes = 0
    for item in blobs[cursor:]:
        size = int(item["size"])
        if batch and (
            len(batch) >= MODEL_DISPATCH_BATCH_MAX_ITEMS
            or raw_bytes + size > MODEL_DISPATCH_BATCH_MAX_RAW_BYTES
        ):
            break
        batch.append(item)
        raw_bytes += size
        if len(batch) >= MODEL_DISPATCH_BATCH_MAX_ITEMS:
            break
        if raw_bytes >= MODEL_DISPATCH_BATCH_MAX_RAW_BYTES:
            break
    return batch


def _require_model_dispatch_action(root: Path, store: Any, action_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], str]:
    action = store.external_action(action_id)
    if action.get("kind") != "repository_publish":
        raise ValueError("action is not a Codex Loop repository publish")
    if action.get("state") != "dispatched":
        raise RuntimeError("model-dispatch transfer requires a dispatched publish action")
    details = _action_details(action)
    if details.get("transport") != "github_object_api":
        raise RuntimeError("model-dispatch transfer requires github_object_api transport")
    release_id = details.get("release_id")
    if not release_id:
        raise RuntimeError("publish action does not reference a release receipt")
    receipt = current_release_receipt(root, store, str(release_id))
    if not receipt.get("current"):
        raise RuntimeError("release receipt became stale during connector transfer")
    if receipt["source_commit"] != details.get("source_commit") or receipt["source_tree"] != details.get("source_tree"):
        raise RuntimeError("publish action source no longer matches its release receipt")
    base_commit = _validate_sha(str(details.get("expected_remote_head") or ""), field="expected remote head")
    blobs, tree_elements, queue_digest = _model_dispatch_queue_metadata(root, base_commit, str(receipt["source_commit"]))
    return action, details, receipt, blobs, tree_elements, queue_digest


def _model_dispatch_view(
    root: Path,
    *,
    details: dict[str, Any],
    receipt: dict[str, Any],
    blobs: list[dict[str, Any]],
    tree_elements: list[dict[str, Any]],
    queue_digest: str,
) -> dict[str, Any]:
    state = details.get("model_dispatch") or {}
    if not isinstance(state, dict):
        raise RuntimeError("model-dispatch state is malformed")
    if state.get("queue_digest") != queue_digest:
        raise RuntimeError("model-dispatch queue digest no longer matches the audited Git object manifest")
    cursor = int(state.get("cursor", 0))
    repository = str(details.get("repository") or "")
    if not repository:
        raise RuntimeError("publish action is missing repository identity")
    if cursor < len(blobs):
        batch = _model_dispatch_batch(blobs, cursor)
        rendered: list[dict[str, Any]] = []
        for item in batch:
            data = _git_blob_bytes(root, str(item["expected_sha"]))
            if len(data) != int(item["size"]):
                raise RuntimeError(f"Git blob size changed while rendering connector queue: {item['path']}")
            rendered.append({
                **item,
                "connector_action": "create_blob",
                "connector_args": {
                    "repository_full_name": repository,
                    "content": base64.b64encode(data).decode("ascii"),
                    "encoding": "base64",
                },
            })
        return {
            "phase": "blob_batch",
            "strategy": "sequential_model_dispatch",
            "queue_digest": queue_digest,
            "cursor": cursor,
            "total_blobs": len(blobs),
            "batch": {
                "start_index": cursor,
                "count": len(rendered),
                "raw_bytes": sum(int(x["size"]) for x in rendered),
                "items": rendered,
            },
            "next": "dispatch create_blob calls in order without intermediate tree probes; collect returned SHA values and acknowledge the whole batch",
        }
    base_commit = _validate_sha(str(details.get("expected_remote_head") or ""), field="expected remote head")
    target_tree = _validate_sha(str(receipt["source_tree"]), field="target tree")
    if state.get("phase") == "tree_verified":
        metadata = _commit_metadata(root, str(receipt["source_commit"]))
        return {
            "phase": "tree_verified",
            "queue_digest": queue_digest,
            "commit_plan": {
                "repository_full_name": repository,
                "message": metadata["message"],
                "tree_sha": target_tree,
                "parent_sha": base_commit,
            },
            "expected_parent": base_commit,
            "expected_tree": target_tree,
            "next": "leave the replay-safe dispatcher here; create the connector commit exactly once under normal non-idempotent external-action discipline, then recheck the remote head, use one non-force ref update, and read back the result",
            "retry_rule": "blob/tree creation may be replayed because Git objects are content-addressed; do not blindly replay create_commit after an unknown outcome",
        }
    return {
        "phase": "create_tree",
        "strategy": "sequential_model_dispatch",
        "queue_digest": queue_digest,
        "cursor": cursor,
        "total_blobs": len(blobs),
        "connector_action": "create_tree",
        "connector_args": {
            "repository_full_name": repository,
            "base_tree_sha": _commit_tree(root, base_commit),
            "tree_elements": tree_elements,
        },
        "expected_tree": target_tree,
        "next": "create exactly one tree and acknowledge its returned SHA; do not probe per blob",
    }


def start_publish_model_dispatch(root: Path, store: Any, *, action_id: str) -> dict[str, Any]:
    action, details, receipt, blobs, tree_elements, queue_digest = _require_model_dispatch_action(root, store, action_id)
    state = details.get("model_dispatch")
    if state is None:
        details["model_dispatch"] = {
            "version": 1,
            "queue_digest": queue_digest,
            "cursor": 0,
            "total_blobs": len(blobs),
            "phase": "blob_upload" if blobs else "tree_ready",
            "batch_max_items": MODEL_DISPATCH_BATCH_MAX_ITEMS,
            "batch_max_raw_bytes": MODEL_DISPATCH_BATCH_MAX_RAW_BYTES,
        }
        store.record_external(
            "repository_publish", "dispatched", action.get("identity"), details,
            action_class="external_non_idempotent", action_id=action_id,
        )
    elif not isinstance(state, dict) or state.get("queue_digest") != queue_digest:
        raise RuntimeError("existing model-dispatch queue does not match the current audited Git object manifest")
    return _model_dispatch_view(
        root, details=_action_details(store.external_action(action_id)), receipt=receipt,
        blobs=blobs, tree_elements=tree_elements, queue_digest=queue_digest,
    )


def publish_model_dispatch_status(root: Path, store: Any, *, action_id: str) -> dict[str, Any]:
    _action, details, receipt, blobs, tree_elements, queue_digest = _require_model_dispatch_action(root, store, action_id)
    if details.get("model_dispatch") is None:
        raise RuntimeError("model-dispatch queue has not been started")
    return _model_dispatch_view(
        root, details=details, receipt=receipt, blobs=blobs, tree_elements=tree_elements, queue_digest=queue_digest,
    )


def acknowledge_publish_model_dispatch_batch(
    root: Path,
    store: Any,
    *,
    action_id: str,
    returned_shas: list[str],
) -> dict[str, Any]:
    action, details, receipt, blobs, tree_elements, queue_digest = _require_model_dispatch_action(root, store, action_id)
    state = details.get("model_dispatch")
    if not isinstance(state, dict) or state.get("queue_digest") != queue_digest:
        raise RuntimeError("model-dispatch queue has not been started or no longer matches")
    if state.get("phase") == "tree_verified":
        raise RuntimeError("blob queue is already complete and its tree has been verified")
    cursor = int(state.get("cursor", 0))
    batch = _model_dispatch_batch(blobs, cursor)
    if not batch:
        raise RuntimeError("there is no pending blob batch to acknowledge")
    if len(returned_shas) != len(batch):
        raise ValueError(f"expected {len(batch)} returned blob SHA values for the current batch")
    normalized = [_validate_sha(value, field="returned blob") for value in returned_shas]
    for expected, observed in zip(batch, normalized):
        if observed != expected["expected_sha"]:
            raise RuntimeError(
                f"connector blob SHA mismatch at queue index {expected['index']} ({expected['path']}): "
                f"expected {expected['expected_sha']} but observed {observed}"
            )
    new_cursor = cursor + len(batch)
    state = dict(state)
    state["cursor"] = new_cursor
    state["phase"] = "tree_ready" if new_cursor == len(blobs) else "blob_upload"
    state["last_ack_count"] = len(batch)
    details["model_dispatch"] = state
    store.record_external(
        "repository_publish", "dispatched", action.get("identity"), details,
        action_class="external_non_idempotent", action_id=action_id,
    )
    return _model_dispatch_view(
        root, details=_action_details(store.external_action(action_id)), receipt=receipt,
        blobs=blobs, tree_elements=tree_elements, queue_digest=queue_digest,
    )


def acknowledge_publish_model_dispatch_tree(
    root: Path,
    store: Any,
    *,
    action_id: str,
    returned_tree: str,
) -> dict[str, Any]:
    action, details, receipt, blobs, tree_elements, queue_digest = _require_model_dispatch_action(root, store, action_id)
    state = details.get("model_dispatch")
    if not isinstance(state, dict) or state.get("queue_digest") != queue_digest:
        raise RuntimeError("model-dispatch queue has not been started or no longer matches")
    if int(state.get("cursor", 0)) != len(blobs):
        raise RuntimeError("cannot acknowledge a tree before all blob batches are verified")
    observed = _validate_sha(returned_tree, field="returned tree")
    target = _validate_sha(str(receipt["source_tree"]), field="target tree")
    if observed != target:
        raise RuntimeError(f"connector tree SHA does not equal the audited target tree: expected {target} but observed {observed}")
    state = dict(state)
    state["phase"] = "tree_verified"
    state["returned_tree"] = observed
    details["model_dispatch"] = state
    store.record_external(
        "repository_publish", "dispatched", action.get("identity"), details,
        action_class="external_non_idempotent", action_id=action_id,
    )
    return _model_dispatch_view(
        root, details=_action_details(store.external_action(action_id)), receipt=receipt,
        blobs=blobs, tree_elements=tree_elements, queue_digest=queue_digest,
    )


def _action_details(action: dict[str, Any]) -> dict[str, Any]:
    raw = action.get("details_json")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def dispatch_publish(store: Any, *, action_id: str, transport: str) -> dict[str, Any]:
    action = store.external_action(action_id)
    if action.get("kind") != "repository_publish":
        raise ValueError("action is not a Codex Loop repository publish")
    if transport not in {"git", "github_object_api"}:
        raise ValueError("publish transport must be git or github_object_api")
    details = _action_details(action)
    if transport == "github_object_api" and details.get("github_object_api_available") is False:
        paths = list(details.get("github_object_api_unsupported_paths") or [])
        suffix = ": " + ", ".join(str(x) for x in paths[:8]) if paths else ""
        raise RuntimeError("GitHub object API fallback is unavailable for unsupported Git object paths" + suffix)
    details["transport"] = transport
    store.record_external(
        "repository_publish",
        "dispatched",
        action.get("identity"),
        details,
        action_class="external_non_idempotent",
        action_id=action_id,
    )
    return {"action_id": action_id, "state": "dispatched", "transport": transport}


def record_publish_outcome(
    root: Path,
    store: Any,
    *,
    action_id: str,
    state: str,
    transport: str,
    evidence: str,
    remote_commit: str | None = None,
    remote_tree: str | None = None,
    remote_parent: str | None = None,
) -> dict[str, Any]:
    if state not in {"terminal_success", "terminal_failure", "outcome_unknown"}:
        raise ValueError("publish outcome must be terminal_success, terminal_failure, or outcome_unknown")
    if transport not in {"git", "github_object_api"}:
        raise ValueError("publish transport must be git or github_object_api")
    clean_evidence = str(evidence).strip()
    if not clean_evidence:
        raise ValueError("publish outcome requires concise observable evidence")
    action = store.external_action(action_id)
    if action.get("kind") != "repository_publish":
        raise ValueError("action is not a Codex Loop repository publish")
    details = _action_details(action)
    if details.get("transport") and details.get("transport") != transport:
        raise ValueError("publish transport does not match the dispatched transport")
    release_id = details.get("release_id")
    receipt = store.release_receipt(str(release_id)) if release_id else None
    if receipt is None:
        raise RuntimeError("publish action does not reference a valid release receipt")
    result_details: dict[str, Any] = {
        "transport": transport,
        "release_id": receipt["release_id"],
        "source_commit": receipt["source_commit"],
        "source_tree": receipt["source_tree"],
        "evidence": clean_evidence,
    }
    if state == "terminal_success":
        if not remote_commit or not remote_tree:
            raise ValueError("successful publish requires observed remote commit and tree")
        observed_commit = _validate_sha(remote_commit, field="remote commit")
        observed_tree = _validate_sha(remote_tree, field="remote tree")
        if observed_tree != receipt["source_tree"]:
            raise RuntimeError("remote tree does not equal the audited release tree")
        if transport == "git" and observed_commit != receipt["source_commit"]:
            raise RuntimeError("ordinary git push did not publish the audited local commit")
        if transport == "github_object_api":
            if not remote_parent:
                raise ValueError("successful GitHub object API publish requires the observed remote commit parent")
            observed_parent = _validate_sha(remote_parent, field="remote parent")
            expected_parent = str(details.get("expected_remote_head") or "")
            if observed_parent != expected_parent:
                raise RuntimeError("connector publish parent does not equal the planned remote head")
            result_details["remote_parent"] = observed_parent
            if observed_commit != receipt["source_commit"]:
                result_details["requires_local_reconciliation"] = True
                result_details["reconciliation_reason"] = (
                    "connector transport created a different commit for the audited tree; import/integrate the observed remote commit "
                    "into this canonical repository before planning the next publish"
                )
        result_details.update({"remote_commit": observed_commit, "remote_tree": observed_tree})
    else:
        if remote_commit:
            result_details["remote_commit"] = _validate_sha(remote_commit, field="remote commit")
        if remote_tree:
            result_details["remote_tree"] = _validate_sha(remote_tree, field="remote tree")
        if remote_parent:
            result_details["remote_parent"] = _validate_sha(remote_parent, field="remote parent")
    store.record_external(
        "repository_publish",
        state,
        action.get("identity"),
        result_details,
        action_class="external_non_idempotent",
        action_id=action_id,
    )
    return {"action_id": action_id, "state": state, **result_details}
