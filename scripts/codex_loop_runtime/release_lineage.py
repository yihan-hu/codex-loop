from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from .workspace import git_branch, git_head, git_state, is_git_repo, run_git

_SHA_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")

CONNECTOR_INLINE_MAX_ENTRY_BYTES = 128 * 1024
CONNECTOR_INLINE_MAX_TOTAL_BYTES = 512 * 1024
CONNECTOR_INLINE_MAX_ENTRIES = 128
MODEL_DISPATCH_BATCH_MAX_ITEMS = 8
MODEL_DISPATCH_BATCH_MAX_RAW_BYTES = 96 * 1024
PORTABLE_STABLE_RECEIPT_SCHEMA_VERSION = 2
PORTABLE_STABLE_RECEIPT_MAX_RAW_BYTES = 64 * 1024 * 1024


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
            "required_transport": "git",
            "host_executor": "remote_desktop_commander",
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
        "transport_order": ["git"],
        "host_executor": "remote_desktop_commander",
        "fallback_transport": None,
        "git": {
            "required": True,
            "configured_remote": configured,
            "requires_host_visible_execution": True,
            "cwd": str(root.resolve()),
            "argv": ["git", "push", "--porcelain", remote_name, f"{target_commit}:refs/heads/{branch_name}"],
            "success_requirement": "read back the remote ref and tree with native Git and require remote commit/tree == audited local release commit/tree",
            "failure_rule": "fail closed and report the native Git/network/authentication blocker; do not switch publish transport",
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



def _stable_publish_manifest(root: Path, base_commit: str, target_commit: str) -> tuple[list[dict[str, Any]], str]:
    manifest = diff_object_manifest(root, base_commit, target_commit)
    items: list[dict[str, Any]] = []
    digest_items: list[dict[str, Any]] = []
    for source in manifest:
        path = str(source["path"])
        delete = bool(source.get("delete"))
        if not delete and source.get("object_type") != "blob":
            raise RuntimeError(f"stable connector publish does not support Git object type {source.get('object_type')}: {path}")
        expected_sha = None if delete else _validate_sha(str(source["new_sha"]), field="blob")
        item = {
            "index": len(items),
            "path": path,
            "delete": delete,
            "mode": str(source["tree_mode"]),
            "type": str(source["tree_type"]),
            "expected_sha": expected_sha,
            "size": 0 if delete else int(source.get("size") or 0),
        }
        items.append(item)
        digest_items.append(dict(item))
    payload = {
        "base_commit": _validate_sha(base_commit, field="base commit"),
        "target_commit": _validate_sha(target_commit, field="target commit"),
        "items": digest_items,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return items, digest


def _stable_branch_name(action: dict[str, Any], source_commit: str) -> str:
    identity = str(action.get("identity") or source_commit)
    suffix = hashlib.sha256(identity.encode("utf-8", errors="surrogateescape")).hexdigest()[:8]
    return f"codex-loop-stable/{source_commit[:12]}-{suffix}"


def _stable_ref_url(repository: str, branch: str) -> str:
    encoded = quote(branch, safe="/")
    return f"https://api.github.com/repos/{repository}/git/ref/heads/{encoded}"


def _stable_branch_url(repository: str, branch: str) -> str:
    encoded = quote(branch, safe="")
    return f"https://api.github.com/repos/{repository}/branches/{encoded}"


def _require_stable_publish_action(
    root: Path,
    store: Any,
    action_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]], str]:
    action = store.external_action(action_id)
    if action.get("kind") != "repository_publish":
        raise ValueError("action is not a Codex Loop repository publish")
    if action.get("state") != "dispatched":
        raise RuntimeError("stable connector publish requires a dispatched publish action")
    details = _action_details(action)
    if details.get("transport") != "github_object_api":
        raise RuntimeError("stable connector publish requires github_object_api transport")
    release_id = details.get("release_id")
    if not release_id:
        raise RuntimeError("publish action does not reference a release receipt")
    receipt = current_release_receipt(root, store, str(release_id))
    if not receipt.get("current"):
        raise RuntimeError("release receipt became stale during stable connector publish")
    if receipt["source_commit"] != details.get("source_commit") or receipt["source_tree"] != details.get("source_tree"):
        raise RuntimeError("publish action source no longer matches its release receipt")
    base_commit = _validate_sha(str(details.get("expected_remote_head") or ""), field="expected remote head")
    items, digest = _stable_publish_manifest(root, base_commit, str(receipt["source_commit"]))
    return action, details, receipt, items, digest


def _persist_stable_state(store: Any, action: dict[str, Any], details: dict[str, Any], action_id: str, state: dict[str, Any]) -> None:
    details = dict(details)
    details["stable_publish"] = state
    store.record_external(
        "repository_publish", "dispatched", action.get("identity"), details,
        action_class="external_non_idempotent", action_id=action_id,
    )


def _stable_first_path_phase(items: list[dict[str, Any]], cursor: int) -> str:
    if cursor >= len(items):
        return "staging_verify"
    return "path_tree" if items[cursor]["delete"] else "path_blob"


def _stable_result_sha(result: dict[str, Any], *, field: str = "sha") -> str:
    value = result.get(field)
    if not isinstance(value, str):
        raise ValueError(f"stable publish acknowledgement requires result.{field}")
    return _validate_sha(value, field=f"stable publish result {field}")


def _stable_result_parent(result: dict[str, Any]) -> str:
    direct = result.get("parent")
    if isinstance(direct, str):
        return _validate_sha(direct, field="stable publish result parent")
    parents = result.get("parents")
    if isinstance(parents, list) and len(parents) == 1 and isinstance(parents[0], str):
        return _validate_sha(parents[0], field="stable publish result parent")
    raise ValueError("stable publish final commit readback requires result.parent or one result.parents entry")




def _portable_canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def _portable_blob_oid(data: bytes, hex_length: int) -> str:
    payload = f"blob {len(data)}\0".encode("ascii") + data
    if hex_length == 40:
        return hashlib.sha1(payload).hexdigest()
    if hex_length == 64:
        return hashlib.sha256(payload).hexdigest()
    raise ValueError("portable receipt blob ids must use 40- or 64-hex Git object ids")


def _portable_receipt_digest(receipt_without_digest: dict[str, Any]) -> str:
    return hashlib.sha256(_portable_canonical_json_bytes(receipt_without_digest)).hexdigest()


def _portable_receipt_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_portable_receipt_payload(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("portable stable publish receipt must be a JSON object")
    if int(value.get("schema_version", 0)) != PORTABLE_STABLE_RECEIPT_SCHEMA_VERSION:
        raise RuntimeError("unsupported portable stable publish receipt schema")
    supplied_digest = str(value.get("receipt_digest") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", supplied_digest):
        raise ValueError("portable stable publish receipt is missing a valid receipt_digest")
    body = dict(value)
    body.pop("receipt_digest", None)
    expected_digest = _portable_receipt_digest(body)
    if supplied_digest != expected_digest:
        raise RuntimeError("portable stable publish receipt digest mismatch")

    for key in ("repository", "target_branch", "staging_branch"):
        if not isinstance(value.get(key), str) or not str(value.get(key)).strip():
            raise ValueError(f"portable stable publish receipt requires {key}")
    if not isinstance(value.get("source_message"), str):
        raise ValueError("portable stable publish receipt requires source_message")
    base_commit = _validate_sha(str(value.get("base_remote_head") or ""), field="portable base remote head")
    base_tree = _validate_sha(str(value.get("base_remote_tree") or ""), field="portable base remote tree")
    source_commit = _validate_sha(str(value.get("source_commit") or ""), field="portable source commit")
    target_tree = _validate_sha(str(value.get("target_tree") or ""), field="portable target tree")
    items = value.get("items")
    if not isinstance(items, list):
        raise ValueError("portable stable publish receipt items must be a JSON array")
    raw_total = 0
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise ValueError(f"portable stable publish receipt item {index} must be an object")
        if int(raw.get("index", -1)) != index:
            raise RuntimeError("portable stable publish receipt item indexes are not contiguous")
        path = raw.get("path")
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
            raise ValueError(f"portable stable publish receipt has unsafe path at index {index}")
        delete = bool(raw.get("delete"))
        if not isinstance(raw.get("mode"), str) or not isinstance(raw.get("type"), str):
            raise ValueError(f"portable stable publish receipt item {index} is missing Git tree metadata")
        if delete:
            if raw.get("expected_sha") is not None or raw.get("content_base64") not in (None, ""):
                raise RuntimeError("portable stable publish deletion unexpectedly carries blob payload")
            continue
        expected_sha = _validate_sha(str(raw.get("expected_sha") or ""), field=f"portable item {index} blob")
        encoded = raw.get("content_base64")
        if not isinstance(encoded, str):
            raise ValueError(f"portable stable publish item {index} is missing content_base64")
        try:
            data = base64.b64decode(encoded.encode("ascii"), validate=True)
        except Exception as exc:
            raise ValueError(f"portable stable publish item {index} has invalid base64 payload") from exc
        size = int(raw.get("size", -1))
        if size != len(data):
            raise RuntimeError(f"portable stable publish item {index} payload size mismatch")
        actual_sha = _portable_blob_oid(data, len(expected_sha))
        if actual_sha != expected_sha:
            raise RuntimeError(f"portable stable publish item {index} payload does not match its Git blob id")
        raw_total += len(data)
    declared_raw = int(value.get("raw_payload_bytes", -1))
    if declared_raw != raw_total:
        raise RuntimeError("portable stable publish receipt raw payload byte count mismatch")
    if raw_total > PORTABLE_STABLE_RECEIPT_MAX_RAW_BYTES:
        raise RuntimeError("portable stable publish receipt exceeds the reliability-first payload limit")
    manifest_digest = str(value.get("manifest_digest") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_digest):
        raise ValueError("portable stable publish receipt requires a manifest_digest")
    manifest_items = [
        {
            "index": int(item["index"]),
            "path": str(item["path"]),
            "delete": bool(item["delete"]),
            "mode": str(item["mode"]),
            "type": str(item["type"]),
            "expected_sha": item.get("expected_sha"),
            "size": int(item.get("size") or 0),
        }
        for item in items
    ]
    manifest_payload = {"base_commit": base_commit, "target_commit": source_commit, "items": manifest_items}
    computed_manifest_digest = hashlib.sha256(_portable_canonical_json_bytes(manifest_payload)).hexdigest()
    if manifest_digest != computed_manifest_digest:
        raise RuntimeError("portable stable publish receipt manifest digest mismatch")
    artifact = value.get("artifact")
    if not isinstance(artifact, dict) or not isinstance(artifact.get("name"), str):
        raise ValueError("portable stable publish receipt requires artifact metadata")
    artifact_sha = str(artifact.get("sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", artifact_sha):
        raise ValueError("portable stable publish receipt requires artifact sha256")
    return {
        **value,
        "base_remote_head": base_commit,
        "base_remote_tree": base_tree,
        "source_commit": source_commit,
        "target_tree": target_tree,
        "receipt_digest": supplied_digest,
    }


def load_publish_stable_portable_receipt(receipt_file: str | Path) -> dict[str, Any]:
    path = Path(receipt_file).expanduser().resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"portable stable publish receipt does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("portable stable publish receipt is not valid JSON") from exc
    return _validate_portable_receipt_payload(value)


def export_publish_stable_portable_receipt(
    root: Path,
    store: Any,
    *,
    action_id: str,
    output_file: str | Path,
) -> dict[str, Any]:
    action, details, release_receipt, items, manifest_digest = _require_stable_publish_action(root, store, action_id)
    output = Path(output_file).expanduser().resolve()
    canonical_root = root.resolve()
    try:
        output.relative_to(canonical_root)
    except ValueError:
        pass
    else:
        raise ValueError("portable stable publish receipt must be written outside the canonical worktree")
    base_commit = _validate_sha(str(details.get("expected_remote_head") or ""), field="expected remote head")
    base_tree = _commit_tree(root, base_commit)
    source_commit = _validate_sha(str(release_receipt["source_commit"]), field="source commit")
    target_tree = _validate_sha(str(release_receipt["source_tree"]), field="target tree")
    raw_total = 0
    portable_items: list[dict[str, Any]] = []
    for source in items:
        item = dict(source)
        if item["delete"]:
            item["content_base64"] = None
        else:
            data = _git_blob_bytes(root, str(item["expected_sha"]))
            if len(data) != int(item["size"]):
                raise RuntimeError(f"Git blob size changed while exporting portable receipt: {item['path']}")
            raw_total += len(data)
            if raw_total > PORTABLE_STABLE_RECEIPT_MAX_RAW_BYTES:
                raise RuntimeError(
                    "portable stable publish payload exceeds 64 MiB; use ordinary Git or a host file-backed/bulk transport instead"
                )
            item["content_base64"] = base64.b64encode(data).decode("ascii")
        portable_items.append(item)
    body: dict[str, Any] = {
        "schema_version": PORTABLE_STABLE_RECEIPT_SCHEMA_VERSION,
        "strategy": "stable_portable_remote_resume",
        "repository": str(details.get("repository") or ""),
        "target_branch": str(details.get("branch") or ""),
        "staging_branch": _stable_branch_name(action, source_commit),
        "base_remote_head": base_commit,
        "base_remote_tree": base_tree,
        "source_commit": source_commit,
        "target_tree": target_tree,
        "source_message": _commit_metadata(root, source_commit)["message"],
        "manifest_digest": manifest_digest,
        "raw_payload_bytes": raw_total,
        "artifact": {
            "name": str(release_receipt.get("artifact_name") or ""),
            "sha256": str(release_receipt.get("artifact_sha256") or "").lower(),
        },
        "items": portable_items,
    }
    body["receipt_digest"] = _portable_receipt_digest(body)
    validated = _validate_portable_receipt_payload(body)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(validated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, output)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return {
        "ready": True,
        "strategy": "stable_portable_remote_resume",
        "receipt_file": str(output),
        "receipt_digest": validated["receipt_digest"],
        "receipt_file_sha256": _portable_receipt_file_sha256(output),
        "repository": validated["repository"],
        "target_branch": validated["target_branch"],
        "staging_branch": validated["staging_branch"],
        "base_remote_head": validated["base_remote_head"],
        "target_tree": validated["target_tree"],
        "path_count": len(portable_items),
        "raw_payload_bytes": raw_total,
        "resume_contract": "the receipt is self-contained for changed blob payloads and may be used after the original Git worktree and Codex Loop task state are gone",
    }


def _portable_token_encode(receipt: dict[str, Any], state: dict[str, Any]) -> str:
    payload = {
        "version": 1,
        "receipt_digest": receipt["receipt_digest"],
        "state": state,
    }
    raw = _portable_canonical_json_bytes(payload)
    checksum = hashlib.sha256(receipt["receipt_digest"].encode("ascii") + b"\0" + raw).hexdigest()
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{encoded}.{checksum}"


def _portable_token_decode(receipt: dict[str, Any], token: str) -> dict[str, Any]:
    try:
        encoded, checksum = token.rsplit(".", 1)
    except ValueError as exc:
        raise ValueError("portable stable publish token is malformed") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("portable stable publish token checksum is malformed")
    padded = encoded + "=" * ((4 - len(encoded) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("ascii"))
    except Exception as exc:
        raise ValueError("portable stable publish token cannot be decoded") from exc
    expected = hashlib.sha256(receipt["receipt_digest"].encode("ascii") + b"\0" + raw).hexdigest()
    if checksum != expected:
        raise RuntimeError("portable stable publish token checksum mismatch")
    if not isinstance(payload, dict) or payload.get("receipt_digest") != receipt["receipt_digest"]:
        raise RuntimeError("portable stable publish token belongs to a different receipt")
    state = payload.get("state")
    if not isinstance(state, dict):
        raise RuntimeError("portable stable publish token has no state")
    return dict(state)


def _portable_checkpoint_message(receipt: dict[str, Any], cursor: int, path: str) -> str:
    total = len(receipt["items"])
    return (
        f"codex-loop portable checkpoint {cursor}/{total}: {path}\n\n"
        f"Codex-Loop-Receipt: {receipt['receipt_digest']}\n"
        f"Codex-Loop-Cursor: {cursor}\n"
        f"Codex-Loop-Target-Tree: {receipt['target_tree']}"
    )


def _portable_checkpoint_cursor(receipt: dict[str, Any], message: str) -> int:
    if not isinstance(message, str):
        raise ValueError("portable staging checkpoint readback requires a commit message")
    digest_match = re.search(r"(?m)^Codex-Loop-Receipt: ([0-9a-f]{64})$", message)
    cursor_match = re.search(r"(?m)^Codex-Loop-Cursor: ([0-9]+)$", message)
    tree_match = re.search(r"(?m)^Codex-Loop-Target-Tree: ([0-9a-fA-F]{40,64})$", message)
    if not digest_match or not cursor_match or not tree_match:
        raise RuntimeError("staging head is not a portable Codex Loop checkpoint")
    if digest_match.group(1) != receipt["receipt_digest"]:
        raise RuntimeError("staging checkpoint belongs to a different portable receipt")
    if _validate_sha(tree_match.group(1), field="checkpoint target tree") != receipt["target_tree"]:
        raise RuntimeError("staging checkpoint target tree does not match the portable receipt")
    cursor = int(cursor_match.group(1))
    if cursor < 1 or cursor > len(receipt["items"]):
        raise RuntimeError("staging checkpoint cursor is outside the portable receipt manifest")
    return cursor


def _portable_result_sha(result: dict[str, Any], field: str = "sha") -> str:
    value = result.get(field)
    if not isinstance(value, str):
        raise ValueError(f"portable stable publish acknowledgement requires result.{field}")
    return _validate_sha(value, field=f"portable stable publish result {field}")


def _portable_result_parent(result: dict[str, Any]) -> str:
    direct = result.get("parent")
    if isinstance(direct, str):
        return _validate_sha(direct, field="portable stable publish result parent")
    parents = result.get("parents")
    if isinstance(parents, list) and len(parents) == 1 and isinstance(parents[0], str):
        return _validate_sha(parents[0], field="portable stable publish result parent")
    raise ValueError("portable final commit readback requires result.parent or one result.parents entry")


def _portable_view(
    receipt: dict[str, Any],
    state: dict[str, Any],
    *,
    connector_action: str | None = None,
    connector_args: dict[str, Any] | None = None,
    ack_result: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    phase = str(state.get("phase") or "")
    common = {
        "control": "CONTINUE",
        "strategy": "stable_portable_remote_resume",
        "phase": phase,
        "receipt_digest": receipt["receipt_digest"],
        "staging_branch": receipt["staging_branch"],
        "target_branch": receipt["target_branch"],
        "target_tree": receipt["target_tree"],
        "cursor": int(state.get("cursor", 0)),
        "total_paths": len(receipt["items"]),
        "token": _portable_token_encode(receipt, state),
        "llm_contract": {
            "preflight_complete": True,
            "normal_path": "dispatch exactly one returned connector action and pass only the observed fixed-shape fields to publish-stable-portable-ack",
            "session_loss": "discard the token, remount the immutable receipt, and call publish-stable-portable-start; remote target/staging readback recovers progress",
            "local_git_required_after_export": False,
            "local_task_state_required_after_export": False,
        },
    }
    if connector_action:
        common["connector_action"] = connector_action
        common["connector_args"] = connector_args or {}
    if ack_result is not None:
        common["ack_result"] = ack_result
    common.update(extra)
    return common


def _portable_target_fetch(receipt: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return _portable_view(
        receipt,
        state,
        connector_action="fetch",
        connector_args={"url": _stable_branch_url(receipt["repository"], receipt["target_branch"])},
        ack_result={"sha": "observed target head"},
    )


def _portable_staging_fetch(receipt: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return _portable_view(
        receipt,
        state,
        connector_action="fetch",
        connector_args={"url": _stable_branch_url(receipt["repository"], receipt["staging_branch"])},
        ack_result={"sha": "head", "tree": "head tree", "message": "head commit message"},
        not_found_ack={"not_found": True},
    )


def _portable_path_start(receipt: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    cursor = int(state.get("cursor", 0))
    if cursor >= len(receipt["items"]):
        state = dict(state)
        state["phase"] = "target_recheck"
        return _portable_target_fetch(receipt, state)
    item = receipt["items"][cursor]
    state = dict(state)
    if item["delete"]:
        state["phase"] = "path_tree"
        tree_element = {"path": item["path"], "mode": item["mode"], "type": item["type"], "sha": None}
        return _portable_view(
            receipt,
            state,
            connector_action="create_tree",
            connector_args={
                "repository_full_name": receipt["repository"],
                "base_tree_sha": _validate_sha(str(state.get("current_tree") or ""), field="portable current tree"),
                "tree_elements": [tree_element],
            },
            ack_result={"sha": "returned tree SHA"},
            path=item["path"],
            retry_rule="create_tree is content-addressed; after session loss restart from remote staging and replay the current path",
        )
    state["phase"] = "path_blob"
    return _portable_view(
        receipt,
        state,
        connector_action="create_blob",
        connector_args={
            "repository_full_name": receipt["repository"],
            "content": item["content_base64"],
            "encoding": "base64",
        },
        ack_result={"sha": item["expected_sha"]},
        path=item["path"],
        retry_rule="create_blob is content-addressed; after session loss restart from remote staging and replay the current path",
    )


def start_publish_stable_portable(*, receipt_file: str | Path) -> dict[str, Any]:
    receipt = load_publish_stable_portable_receipt(receipt_file)
    return _portable_target_fetch(receipt, {"phase": "target_observe", "cursor": 0})


def acknowledge_publish_stable_portable(
    *,
    receipt_file: str | Path,
    token: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("portable stable publish acknowledgement result must be a JSON object")
    receipt = load_publish_stable_portable_receipt(receipt_file)
    state = _portable_token_decode(receipt, token)
    phase = str(state.get("phase") or "")
    base_commit = receipt["base_remote_head"]
    base_tree = receipt["base_remote_tree"]
    target_tree = receipt["target_tree"]
    repository = receipt["repository"]
    items = receipt["items"]

    if phase in {"target_observe", "target_recheck"}:
        observed = _portable_result_sha(result)
        if observed == base_commit:
            if phase == "target_observe":
                return _portable_staging_fetch(receipt, {"phase": "staging_observe", "cursor": 0})
            state = dict(state)
            state["phase"] = "final_commit"
            return _portable_view(
                receipt,
                state,
                connector_action="create_commit",
                connector_args={
                    "repository_full_name": repository,
                    "message": receipt["source_message"],
                    "tree_sha": target_tree,
                    "parent_sha": base_commit,
                },
                ack_result={"sha": "returned clean transport commit SHA"},
                retry_rule="if this result is lost, restart from the receipt; target readback decides whether to recreate or verify completion",
            )
        return _portable_view(
            receipt,
            {"phase": "target_existing_verify", "cursor": int(state.get("cursor", 0)), "observed_target": observed},
            connector_action="fetch_commit",
            connector_args={"repo_full_name": repository, "commit_sha": observed},
            ack_result={"sha": observed, "tree": target_tree, "parent": base_commit},
            verification_reason="the target moved from the preflight base; only an already-completed publish with exact tree+parent may be accepted",
        )

    if phase == "target_existing_verify":
        observed_commit = _portable_result_sha(result)
        expected_commit = _validate_sha(str(state.get("observed_target") or ""), field="observed target commit")
        observed_tree = _portable_result_sha(result, "tree")
        observed_parent = _portable_result_parent(result)
        if observed_commit == expected_commit and observed_tree == target_tree and observed_parent == base_commit:
            return {
                "control": "COMPLETE",
                "strategy": "stable_portable_remote_resume",
                "phase": "complete",
                "already_published": True,
                "remote_commit": observed_commit,
                "remote_tree": observed_tree,
                "remote_parent": observed_parent,
                "receipt_digest": receipt["receipt_digest"],
            }
        raise RuntimeError(
            f"target branch moved concurrently to {expected_commit}; observed commit does not match the portable receipt target tree and planned parent"
        )

    if phase in {"staging_observe", "staging_confirm"}:
        if result.get("not_found") is True:
            if phase == "staging_confirm":
                raise RuntimeError("staging branch was not found after create_branch reported success")
            return _portable_view(
                receipt,
                {"phase": "create_staging", "cursor": 0},
                connector_action="create_branch",
                connector_args={
                    "repository_full_name": repository,
                    "branch_name": receipt["staging_branch"],
                    "sha": base_commit,
                },
                ack_result={"ok": True},
                retry_rule="if branch creation outcome is lost, restart from the receipt and observe the deterministic staging branch",
            )
        observed_head = _portable_result_sha(result)
        observed_tree = _portable_result_sha(result, "tree")
        if observed_head == base_commit:
            if observed_tree != base_tree:
                raise RuntimeError("portable staging base tree does not match the receipt base tree")
            return _portable_path_start(
                receipt,
                {"phase": "path_start", "cursor": 0, "current_head": base_commit, "current_tree": base_tree},
            )
        cursor = _portable_checkpoint_cursor(receipt, str(result.get("message") or ""))
        if cursor == len(items) and observed_tree != target_tree:
            raise RuntimeError("completed portable staging checkpoint does not equal the audited target tree")
        return _portable_path_start(
            receipt,
            {"phase": "path_start", "cursor": cursor, "current_head": observed_head, "current_tree": observed_tree},
        )

    if phase == "create_staging":
        if result.get("ok") is not True:
            raise ValueError("portable create_staging acknowledgement requires result.ok=true")
        return _portable_staging_fetch(receipt, {"phase": "staging_confirm", "cursor": 0})

    if phase == "path_blob":
        cursor = int(state.get("cursor", 0))
        item = items[cursor]
        observed = _portable_result_sha(result)
        expected = _validate_sha(str(item["expected_sha"]), field="portable expected blob")
        if observed != expected:
            raise RuntimeError(f"portable stable blob SHA mismatch at {item['path']}: expected {expected} but observed {observed}")
        state = dict(state)
        state["phase"] = "path_tree"
        tree_element = {"path": item["path"], "mode": item["mode"], "type": item["type"], "sha": expected}
        return _portable_view(
            receipt,
            state,
            connector_action="create_tree",
            connector_args={
                "repository_full_name": repository,
                "base_tree_sha": _validate_sha(str(state.get("current_tree") or ""), field="portable current tree"),
                "tree_elements": [tree_element],
            },
            ack_result={"sha": "returned tree SHA"},
            path=item["path"],
        )

    if phase == "path_tree":
        cursor = int(state.get("cursor", 0))
        item = items[cursor]
        observed_tree = _portable_result_sha(result)
        if cursor == len(items) - 1 and observed_tree != target_tree:
            raise RuntimeError(
                f"final portable checkpoint tree does not equal the audited target tree: expected {target_tree} but observed {observed_tree}"
            )
        next_cursor = cursor + 1
        message = _portable_checkpoint_message(receipt, next_cursor, item["path"])
        state = dict(state)
        state["phase"] = "path_commit"
        state["pending_tree"] = observed_tree
        return _portable_view(
            receipt,
            state,
            connector_action="create_commit",
            connector_args={
                "repository_full_name": repository,
                "message": message,
                "tree_sha": observed_tree,
                "parent_sha": _validate_sha(str(state.get("current_head") or ""), field="portable current staging head"),
            },
            ack_result={"sha": "returned checkpoint commit SHA"},
            path=item["path"],
            retry_rule="an orphan checkpoint commit may be recreated after session loss because remote staging ref readback, not the create_commit response, defines durable progress",
        )

    if phase == "path_commit":
        pending_commit = _portable_result_sha(result)
        state = dict(state)
        state["phase"] = "path_ref_update"
        state["pending_commit"] = pending_commit
        return _portable_view(
            receipt,
            state,
            connector_action="update_ref",
            connector_args={
                "repository_full_name": repository,
                "branch_name": receipt["staging_branch"],
                "sha": pending_commit,
                "force": False,
            },
            ack_result={"ok": True},
        )

    if phase == "path_ref_update":
        if result.get("ok") is not True:
            raise ValueError("portable checkpoint ref update acknowledgement requires result.ok=true")
        state = dict(state)
        state["phase"] = "path_ref_readback"
        return _portable_staging_fetch(receipt, state)

    if phase == "path_ref_readback":
        observed_head = _portable_result_sha(result)
        observed_tree = _portable_result_sha(result, "tree")
        pending_commit = _validate_sha(str(state.get("pending_commit") or ""), field="portable pending checkpoint commit")
        pending_tree = _validate_sha(str(state.get("pending_tree") or ""), field="portable pending checkpoint tree")
        if observed_head != pending_commit or observed_tree != pending_tree:
            raise RuntimeError("portable staging checkpoint ref readback does not match the pending commit/tree")
        expected_cursor = int(state.get("cursor", 0)) + 1
        observed_cursor = _portable_checkpoint_cursor(receipt, str(result.get("message") or ""))
        if observed_cursor != expected_cursor:
            raise RuntimeError(f"portable staging checkpoint cursor mismatch: expected {expected_cursor} but observed {observed_cursor}")
        return _portable_path_start(
            receipt,
            {
                "phase": "path_start",
                "cursor": expected_cursor,
                "current_head": observed_head,
                "current_tree": observed_tree,
            },
        )

    if phase == "final_commit":
        final_commit = _portable_result_sha(result)
        state = dict(state)
        state["phase"] = "target_ref_update"
        state["final_commit"] = final_commit
        return _portable_view(
            receipt,
            state,
            connector_action="update_ref",
            connector_args={
                "repository_full_name": repository,
                "branch_name": receipt["target_branch"],
                "sha": final_commit,
                "force": False,
            },
            ack_result={"ok": True},
        )

    if phase == "target_ref_update":
        if result.get("ok") is not True:
            raise ValueError("portable target ref update acknowledgement requires result.ok=true")
        state = dict(state)
        state["phase"] = "target_ref_readback"
        return _portable_target_fetch(receipt, state)

    if phase == "target_ref_readback":
        observed = _portable_result_sha(result)
        expected = _validate_sha(str(state.get("final_commit") or ""), field="portable final transport commit")
        if observed != expected:
            raise RuntimeError(f"portable target ref readback mismatch: expected {expected} but observed {observed}; restart from the receipt")
        state = dict(state)
        state["phase"] = "final_commit_readback"
        return _portable_view(
            receipt,
            state,
            connector_action="fetch_commit",
            connector_args={"repo_full_name": repository, "commit_sha": expected},
            ack_result={"sha": expected, "tree": target_tree, "parent": base_commit},
        )

    if phase == "final_commit_readback":
        observed_commit = _portable_result_sha(result)
        expected = _validate_sha(str(state.get("final_commit") or ""), field="portable final transport commit")
        observed_tree = _portable_result_sha(result, "tree")
        observed_parent = _portable_result_parent(result)
        if observed_commit != expected or observed_tree != target_tree or observed_parent != base_commit:
            raise RuntimeError("portable final commit/tree/parent readback does not match the immutable receipt")
        return {
            "control": "COMPLETE",
            "strategy": "stable_portable_remote_resume",
            "phase": "complete",
            "remote_commit": observed_commit,
            "remote_tree": observed_tree,
            "remote_parent": observed_parent,
            "receipt_digest": receipt["receipt_digest"],
            "local_reconciliation_note": "the connector transport commit may differ from source_commit; reconcile it into a future canonical Git workspace before planning another publish",
        }

    raise RuntimeError(f"unknown portable stable publish phase: {phase}")

def _stable_common_view(
    *,
    state: dict[str, Any],
    items: list[dict[str, Any]],
    receipt: dict[str, Any],
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "control": "CONTINUE",
        "strategy": "stable_checkpoint_dispatch",
        "phase": str(state.get("phase") or ""),
        "cursor": int(state.get("cursor", 0)),
        "total_paths": len(items),
        "staging_branch": str(state.get("staging_branch") or ""),
        "target_branch": str(details.get("branch") or ""),
        "source_commit": str(receipt["source_commit"]),
        "target_tree": str(receipt["source_tree"]),
        "llm_contract": {
            "preflight_complete": True,
            "normal_path": "dispatch exactly the connector_action/connector_args returned here, pass only the observed result fields to publish-stable-ack, then continue while control=CONTINUE",
            "normal_control_values": ["CONTINUE", "COMPLETE"],
            "exception_path": "connector ambiguity, acknowledgement failure, SHA/tree mismatch, or concurrent target movement exits fixed-control dispatch and requires publish-stable-reconcile or fresh reasoning",
        },
    }


def _stable_publish_view(
    root: Path,
    *,
    details: dict[str, Any],
    receipt: dict[str, Any],
    items: list[dict[str, Any]],
    digest: str,
) -> dict[str, Any]:
    state = details.get("stable_publish")
    if not isinstance(state, dict):
        raise RuntimeError("stable connector publish has not been started")
    if state.get("manifest_digest") != digest:
        raise RuntimeError("stable connector publish manifest no longer matches the audited Git diff")
    phase = str(state.get("phase") or "")
    cursor = int(state.get("cursor", 0))
    if cursor < 0 or cursor > len(items):
        raise RuntimeError("stable connector publish cursor is outside the current Git-derived manifest")
    repository = str(details.get("repository") or "")
    branch = str(details.get("branch") or "")
    staging_branch = str(state.get("staging_branch") or "")
    if not repository or not branch or not staging_branch:
        raise RuntimeError("stable connector publish is missing repository or branch identity")
    base_commit = _validate_sha(str(details.get("expected_remote_head") or ""), field="expected remote head")
    target_tree = _validate_sha(str(receipt["source_tree"]), field="target tree")
    common = _stable_common_view(state=state, items=items, receipt=receipt, details=details)

    if phase == "create_staging_branch":
        return {
            **common,
            "connector_action": "create_branch",
            "connector_args": {"repository_full_name": repository, "branch_name": staging_branch, "sha": base_commit},
            "ack_result": {"ok": True},
            "retry_rule": "if create_branch outcome is unknown or a retry reports that the branch already exists, read the staging ref and use publish-stable-reconcile instead of guessing",
        }
    if phase == "staging_branch_readback":
        return {
            **common,
            "connector_action": "fetch",
            "connector_args": {"url": _stable_ref_url(repository, staging_branch)},
            "ack_result": {"sha": base_commit},
            "next": "the staging branch must read back exactly at the planned remote head before any path transfer begins",
        }
    if phase == "path_blob":
        item = items[cursor]
        if item["delete"]:
            raise RuntimeError("stable publish entered blob phase for a deletion")
        data = _git_blob_bytes(root, str(item["expected_sha"]))
        if len(data) != int(item["size"]):
            raise RuntimeError(f"Git blob size changed while rendering stable publish path: {item['path']}")
        return {
            **common,
            "path": item["path"],
            "connector_action": "create_blob",
            "connector_args": {
                "repository_full_name": repository,
                "content": base64.b64encode(data).decode("ascii"),
                "encoding": "base64",
            },
            "ack_result": {"sha": item["expected_sha"]},
            "retry_rule": "create_blob is content-addressed and may be replayed when its acknowledgement is lost",
        }
    if phase == "path_tree":
        item = items[cursor]
        current_tree = _validate_sha(str(state.get("current_staging_tree") or ""), field="current staging tree")
        tree_element = {"path": item["path"], "mode": item["mode"], "type": item["type"], "sha": item["expected_sha"]}
        out = {
            **common,
            "path": item["path"],
            "connector_action": "create_tree",
            "connector_args": {
                "repository_full_name": repository,
                "base_tree_sha": current_tree,
                "tree_elements": [tree_element],
            },
            "ack_result": {"sha": "returned tree SHA"},
            "retry_rule": "create_tree is content-addressed and may be replayed when its acknowledgement is lost",
        }
        if cursor == len(items) - 1:
            out["required_returned_tree"] = target_tree
        return out
    if phase == "path_commit":
        item = items[cursor]
        pending_tree = _validate_sha(str(state.get("pending_tree") or ""), field="pending checkpoint tree")
        parent = _validate_sha(str(state.get("current_staging_head") or ""), field="current staging head")
        return {
            **common,
            "path": item["path"],
            "connector_action": "create_commit",
            "connector_args": {
                "repository_full_name": repository,
                "message": f"codex-loop stable checkpoint {cursor + 1}/{len(items)}: {item['path']}",
                "tree_sha": pending_tree,
                "parent_sha": parent,
            },
            "ack_result": {"sha": "returned checkpoint commit SHA"},
            "retry_rule": "create_commit is not blindly replay-safe after an unknown outcome; use reconciliation/fresh reasoning instead of assuming failure",
        }
    if phase == "path_ref_update":
        pending_commit = _validate_sha(str(state.get("pending_commit") or ""), field="pending checkpoint commit")
        return {
            **common,
            "connector_action": "update_ref",
            "connector_args": {
                "repository_full_name": repository,
                "branch_name": staging_branch,
                "sha": pending_commit,
                "force": False,
            },
            "ack_result": {"ok": True},
            "next": "after the write returns, read the staging ref back before advancing the cursor",
        }
    if phase == "path_ref_readback":
        pending_commit = _validate_sha(str(state.get("pending_commit") or ""), field="pending checkpoint commit")
        return {
            **common,
            "connector_action": "fetch",
            "connector_args": {"url": _stable_ref_url(repository, staging_branch)},
            "ack_result": {"sha": pending_commit},
            "next": "cursor advances only after the staging branch reads back the exact checkpoint commit",
        }
    if phase == "staging_verify":
        head = _validate_sha(str(state.get("current_staging_head") or ""), field="current staging head")
        return {
            **common,
            "connector_action": "fetch_commit",
            "connector_args": {"repo_full_name": repository, "commit_sha": head},
            "ack_result": {"sha": head, "tree": target_tree},
            "next": "the final staging checkpoint must read back with the exact audited target tree before the target branch can move",
        }
    if phase == "final_commit":
        metadata = _commit_metadata(root, str(receipt["source_commit"]))
        return {
            **common,
            "connector_action": "create_commit",
            "connector_args": {
                "repository_full_name": repository,
                "message": metadata["message"],
                "tree_sha": target_tree,
                "parent_sha": base_commit,
            },
            "ack_result": {"sha": "returned clean transport commit SHA"},
            "next": "after staging verification, synthesize one clean target commit whose parent is the originally observed remote head",
            "retry_rule": "do not blindly replay this create_commit after an unknown outcome; reconcile from real external observations",
        }
    if phase == "target_ref_precondition":
        return {
            **common,
            "connector_action": "fetch",
            "connector_args": {"url": _stable_ref_url(repository, branch)},
            "ack_result": {"sha": base_commit},
            "next": "the target branch must still equal the preflight remote head; any movement fails closed without force-pushing",
        }
    if phase == "target_ref_update":
        final_commit = _validate_sha(str(state.get("final_commit") or ""), field="final transport commit")
        return {
            **common,
            "connector_action": "update_ref",
            "connector_args": {
                "repository_full_name": repository,
                "branch_name": branch,
                "sha": final_commit,
                "force": False,
            },
            "ack_result": {"ok": True},
            "next": "read the target ref back after the non-force update; success is never inferred from the write call alone",
        }
    if phase == "target_ref_readback":
        final_commit = _validate_sha(str(state.get("final_commit") or ""), field="final transport commit")
        return {
            **common,
            "connector_action": "fetch",
            "connector_args": {"url": _stable_ref_url(repository, branch)},
            "ack_result": {"sha": final_commit},
        }
    if phase == "final_commit_readback":
        final_commit = _validate_sha(str(state.get("final_commit") or ""), field="final transport commit")
        return {
            **common,
            "connector_action": "fetch_commit",
            "connector_args": {"repo_full_name": repository, "commit_sha": final_commit},
            "ack_result": {"sha": final_commit, "tree": target_tree, "parent": base_commit},
            "next": "terminal success is recorded only after this commit/tree/parent readback matches the audited release and preflight parent",
        }
    raise RuntimeError(f"unknown stable connector publish phase: {phase}")


def start_publish_stable(root: Path, store: Any, *, action_id: str) -> dict[str, Any]:
    action, details, receipt, items, digest = _require_stable_publish_action(root, store, action_id)
    state = details.get("stable_publish")
    if state is None:
        base_commit = _validate_sha(str(details.get("expected_remote_head") or ""), field="expected remote head")
        state = {
            "version": 1,
            "manifest_digest": digest,
            "staging_branch": _stable_branch_name(action, str(receipt["source_commit"])),
            "cursor": 0,
            "total_paths": len(items),
            "phase": "create_staging_branch",
            "current_staging_head": base_commit,
            "current_staging_tree": _commit_tree(root, base_commit),
        }
        _persist_stable_state(store, action, details, action_id, state)
        details = _action_details(store.external_action(action_id))
    elif not isinstance(state, dict) or state.get("manifest_digest") != digest:
        raise RuntimeError("existing stable connector publish state does not match the current audited Git diff")
    return _stable_publish_view(root, details=details, receipt=receipt, items=items, digest=digest)


def publish_stable_status(root: Path, store: Any, *, action_id: str) -> dict[str, Any]:
    action = store.external_action(action_id)
    if action.get("kind") != "repository_publish":
        raise ValueError("action is not a Codex Loop repository publish")
    if action.get("state") == "terminal_success":
        details = _action_details(action)
        return {
            "control": "COMPLETE",
            "strategy": "stable_checkpoint_dispatch",
            "phase": "complete",
            "action_id": action_id,
            "remote_commit": details.get("remote_commit"),
            "remote_tree": details.get("remote_tree"),
            "requires_local_reconciliation": bool(details.get("requires_local_reconciliation")),
        }
    _action, details, receipt, items, digest = _require_stable_publish_action(root, store, action_id)
    if details.get("stable_publish") is None:
        raise RuntimeError("stable connector publish has not been started")
    return _stable_publish_view(root, details=details, receipt=receipt, items=items, digest=digest)


def publish_stable_next(root: Path, store: Any, *, action_id: str) -> dict[str, Any]:
    return publish_stable_status(root, store, action_id=action_id)


def acknowledge_publish_stable(
    root: Path,
    store: Any,
    *,
    action_id: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("stable publish acknowledgement result must be a JSON object")
    action, details, receipt, items, digest = _require_stable_publish_action(root, store, action_id)
    state_raw = details.get("stable_publish")
    if not isinstance(state_raw, dict) or state_raw.get("manifest_digest") != digest:
        raise RuntimeError("stable connector publish has not been started or no longer matches")
    state = dict(state_raw)
    phase = str(state.get("phase") or "")
    cursor = int(state.get("cursor", 0))
    base_commit = _validate_sha(str(details.get("expected_remote_head") or ""), field="expected remote head")
    target_tree = _validate_sha(str(receipt["source_tree"]), field="target tree")

    if phase in {"create_staging_branch", "path_ref_update", "target_ref_update"}:
        if result.get("ok") is not True:
            raise ValueError(f"stable publish phase {phase} requires result.ok=true")
        state["phase"] = {
            "create_staging_branch": "staging_branch_readback",
            "path_ref_update": "path_ref_readback",
            "target_ref_update": "target_ref_readback",
        }[phase]
    elif phase == "staging_branch_readback":
        observed = _stable_result_sha(result)
        if observed != base_commit:
            raise RuntimeError(f"stable staging branch readback mismatch: expected {base_commit} but observed {observed}")
        state["phase"] = _stable_first_path_phase(items, cursor)
    elif phase == "path_blob":
        item = items[cursor]
        observed = _stable_result_sha(result)
        expected = _validate_sha(str(item["expected_sha"]), field="expected path blob")
        if observed != expected:
            raise RuntimeError(
                f"stable connector blob SHA mismatch at path index {cursor} ({item['path']}): expected {expected} but observed {observed}"
            )
        state["verified_blob"] = observed
        state["phase"] = "path_tree"
    elif phase == "path_tree":
        observed = _stable_result_sha(result)
        if cursor == len(items) - 1 and observed != target_tree:
            raise RuntimeError(
                f"final stable checkpoint tree does not equal the audited target tree: expected {target_tree} but observed {observed}"
            )
        state["pending_tree"] = observed
        state["phase"] = "path_commit"
    elif phase == "path_commit":
        state["pending_commit"] = _stable_result_sha(result)
        state["phase"] = "path_ref_update"
    elif phase == "path_ref_readback":
        observed = _stable_result_sha(result)
        pending_commit = _validate_sha(str(state.get("pending_commit") or ""), field="pending checkpoint commit")
        if observed != pending_commit:
            raise RuntimeError(f"stable staging ref readback mismatch: expected {pending_commit} but observed {observed}")
        pending_tree = _validate_sha(str(state.get("pending_tree") or ""), field="pending checkpoint tree")
        state["current_staging_head"] = pending_commit
        state["current_staging_tree"] = pending_tree
        state["cursor"] = cursor + 1
        state.pop("pending_commit", None)
        state.pop("pending_tree", None)
        state.pop("verified_blob", None)
        state["phase"] = _stable_first_path_phase(items, cursor + 1)
    elif phase == "staging_verify":
        observed_commit = _stable_result_sha(result)
        expected_commit = _validate_sha(str(state.get("current_staging_head") or ""), field="current staging head")
        observed_tree = _stable_result_sha(result, field="tree")
        if observed_commit != expected_commit:
            raise RuntimeError(f"final staging commit readback mismatch: expected {expected_commit} but observed {observed_commit}")
        if observed_tree != target_tree:
            raise RuntimeError(f"final staging tree mismatch: expected {target_tree} but observed {observed_tree}")
        state["phase"] = "final_commit"
    elif phase == "final_commit":
        state["final_commit"] = _stable_result_sha(result)
        state["phase"] = "target_ref_precondition"
    elif phase == "target_ref_precondition":
        observed = _stable_result_sha(result)
        if observed != base_commit:
            raise RuntimeError(
                f"target branch moved since stable publish preflight: expected {base_commit} but observed {observed}; do not force-update"
            )
        state["target_head_verified"] = observed
        state["phase"] = "target_ref_update"
    elif phase == "target_ref_readback":
        observed = _stable_result_sha(result)
        expected = _validate_sha(str(state.get("final_commit") or ""), field="final transport commit")
        if observed != expected:
            raise RuntimeError(f"target ref readback mismatch: expected {expected} but observed {observed}")
        state["phase"] = "final_commit_readback"
    elif phase == "final_commit_readback":
        observed_commit = _stable_result_sha(result)
        expected_commit = _validate_sha(str(state.get("final_commit") or ""), field="final transport commit")
        observed_tree = _stable_result_sha(result, field="tree")
        observed_parent = _stable_result_parent(result)
        if observed_commit != expected_commit:
            raise RuntimeError(f"final transport commit readback mismatch: expected {expected_commit} but observed {observed_commit}")
        if observed_tree != target_tree:
            raise RuntimeError(f"final transport tree mismatch: expected {target_tree} but observed {observed_tree}")
        if observed_parent != base_commit:
            raise RuntimeError(f"final transport parent mismatch: expected {base_commit} but observed {observed_parent}")
        state["phase"] = "complete"
        _persist_stable_state(store, action, details, action_id, state)
        publish = record_publish_outcome(
            root,
            store,
            action_id=action_id,
            state="terminal_success",
            transport="github_object_api",
            remote_commit=observed_commit,
            remote_tree=observed_tree,
            remote_parent=observed_parent,
            evidence="stable connector publish read back target ref plus final commit/tree/parent after one-path staging checkpoints",
        )
        return {
            "control": "COMPLETE",
            "strategy": "stable_checkpoint_dispatch",
            "phase": "complete",
            "staging_branch": state.get("staging_branch"),
            "publish": publish,
        }
    else:
        raise RuntimeError(f"unknown stable connector publish phase: {phase}")

    _persist_stable_state(store, action, details, action_id, state)
    return publish_stable_status(root, store, action_id=action_id)


def reconcile_publish_stable(
    root: Path,
    store: Any,
    *,
    action_id: str,
    observed_staging_head: str | None = None,
    observed_staging_tree: str | None = None,
    observed_target_head: str | None = None,
) -> dict[str, Any]:
    action, details, receipt, items, digest = _require_stable_publish_action(root, store, action_id)
    state_raw = details.get("stable_publish")
    if not isinstance(state_raw, dict) or state_raw.get("manifest_digest") != digest:
        raise RuntimeError("stable connector publish has not been started or no longer matches")
    state = dict(state_raw)
    phase = str(state.get("phase") or "")
    base_commit = _validate_sha(str(details.get("expected_remote_head") or ""), field="expected remote head")

    if phase in {"create_staging_branch", "staging_branch_readback"}:
        if not observed_staging_head:
            raise ValueError("reconciling staging branch creation requires --observed-staging-head")
        observed = _validate_sha(observed_staging_head, field="observed staging head")
        if observed != base_commit:
            raise RuntimeError(f"staging branch reconciliation mismatch: expected {base_commit} but observed {observed}")
        if observed_staging_tree:
            tree = _validate_sha(observed_staging_tree, field="observed staging tree")
            expected_tree = _commit_tree(root, base_commit)
            if tree != expected_tree:
                raise RuntimeError(f"staging branch tree mismatch: expected {expected_tree} but observed {tree}")
        state["phase"] = _stable_first_path_phase(items, int(state.get("cursor", 0)))
    elif phase in {"path_ref_update", "path_ref_readback"}:
        if not observed_staging_head:
            raise ValueError("reconciling a checkpoint ref update requires --observed-staging-head")
        observed = _validate_sha(observed_staging_head, field="observed staging head")
        current = _validate_sha(str(state.get("current_staging_head") or ""), field="current staging head")
        pending = _validate_sha(str(state.get("pending_commit") or ""), field="pending checkpoint commit")
        pending_tree = _validate_sha(str(state.get("pending_tree") or ""), field="pending checkpoint tree")
        if observed_staging_tree:
            tree = _validate_sha(observed_staging_tree, field="observed staging tree")
            expected_tree = pending_tree if observed == pending else _validate_sha(str(state.get("current_staging_tree") or ""), field="current staging tree")
            if tree != expected_tree:
                raise RuntimeError(f"staging ref reconciliation tree mismatch: expected {expected_tree} but observed {tree}")
        if observed == pending:
            cursor = int(state.get("cursor", 0))
            state["current_staging_head"] = pending
            state["current_staging_tree"] = pending_tree
            state["cursor"] = cursor + 1
            state.pop("pending_commit", None)
            state.pop("pending_tree", None)
            state.pop("verified_blob", None)
            state["phase"] = _stable_first_path_phase(items, cursor + 1)
        elif observed == current:
            state["phase"] = "path_ref_update"
        else:
            raise RuntimeError(
                f"staging ref reconciliation found an unexpected head {observed}; expected current {current} or pending {pending}"
            )
    elif phase in {"target_ref_update", "target_ref_readback"}:
        if not observed_target_head:
            raise ValueError("reconciling the target ref update requires --observed-target-head")
        observed = _validate_sha(observed_target_head, field="observed target head")
        final_commit = _validate_sha(str(state.get("final_commit") or ""), field="final transport commit")
        if observed == final_commit:
            state["phase"] = "final_commit_readback"
        elif observed == base_commit:
            state["phase"] = "target_ref_update"
        else:
            raise RuntimeError(
                f"target ref reconciliation found concurrent movement to {observed}; expected base {base_commit} or final {final_commit}"
            )
    elif phase in {"path_blob", "path_tree"}:
        return {
            **_stable_publish_view(root, details=details, receipt=receipt, items=items, digest=digest),
            "reconciliation": "current operation is content-addressed and replay-safe; dispatch the exact same connector action again",
        }
    else:
        raise RuntimeError(
            f"stable publish phase {phase} cannot be reconciled from branch observations alone; inspect the external outcome before continuing"
        )

    _persist_stable_state(store, action, details, action_id, state)
    return publish_stable_status(root, store, action_id=action_id)

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
    if transport != "git":
        raise ValueError("repository publishing supports native git only through Remote Desktop Commander")
    details = _action_details(action)
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
    if transport != "git":
        raise ValueError("repository publishing supports native git only through Remote Desktop Commander")
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
        if observed_commit != receipt["source_commit"]:
            raise RuntimeError("native git push did not publish the audited local commit")
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
