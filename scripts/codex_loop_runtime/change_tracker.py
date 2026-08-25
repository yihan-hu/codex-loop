from __future__ import annotations

from pathlib import Path
from typing import Any

from .state import StateStore
from .workspace import FileSnapshot, git_state, ignored_watch_state, snapshot_files, workspace_fingerprint


def capture_baseline(root: Path, store: StateStore) -> int:
    root = root.resolve()
    git = git_state(root)
    if git.get("is_git") and git.get("probe_degraded"):
        raise RuntimeError("cannot establish a safe baseline because Git state could not be fully observed")
    ignored = ignored_watch_state(root) if git.get("is_git") else {"watched": [], "opaque_paths": []}
    protected = set(str(x) for x in git.get("protected_paths", []))
    protected.update(item.path for item in ignored.get("watched", []))
    files = snapshot_files(root)
    store.replace_baseline([
        (item.path, item.sha256, item.size, item.mode, item.path in protected)
        for item in files
    ])
    store.set_meta("baseline_git", git)
    store.set_meta("protected_paths", sorted(protected))
    store.set_meta("workspace_fingerprint", workspace_fingerprint(root))
    store.set_meta("baseline_file_count", len(files))
    store.set_meta("ignored_watch", {"watched_paths": sorted(item.path for item in ignored.get("watched", [])), "opaque_paths": list(ignored.get("opaque_paths", []))})
    return len(files)


def sync_generation(root: Path, store: StateStore) -> bool:
    root = root.resolve()
    current = workspace_fingerprint(root)
    previous = store.get_meta("workspace_fingerprint")
    if previous is None:
        store.set_meta("workspace_fingerprint", current)
        return False
    ignored = ignored_watch_state(root) if git_state(root).get("is_git") else {"watched": [], "opaque_paths": []}
    store.set_meta("ignored_watch", {"watched_paths": sorted(item.path for item in ignored.get("watched", [])), "opaque_paths": list(ignored.get("opaque_paths", []))})
    if current == previous:
        return False
    store.record_mutation("*", "external_workspace_change", str(previous), current)
    store.set_meta("workspace_fingerprint", current)
    return True


def _map_current(items: list[FileSnapshot]) -> dict[str, FileSnapshot]:
    return {item.path: item for item in items}


def changes(root: Path, store: StateStore) -> dict[str, Any]:
    root = root.resolve()
    baseline = store.baseline()
    current = _map_current(snapshot_files(root))
    base_paths = set(baseline)
    current_paths = set(current)
    added = sorted(current_paths - base_paths)
    deleted = sorted(base_paths - current_paths)
    modified: list[str] = []
    for path in sorted(base_paths & current_paths):
        before = baseline[path]
        now = current[path]
        if before["sha256"] != now.sha256 or int(before["mode"]) != int(now.mode):
            modified.append(path)

    git_before = store.get_meta("baseline_git", {"is_git": False})
    git_now = git_state(root)
    rename_pairs: list[dict[str, str]] = []
    for entry in git_now.get("status", []):
        if entry.get("kind") == "renamed" and entry.get("old_path"):
            rename_pairs.append({"from": str(entry["old_path"]), "to": str(entry["path"])})

    protected = store.protected_paths()
    changed_paths = set(added) | set(deleted) | set(modified)
    journaled = store.mutation_paths()
    unexpected_protected = sorted((protected & changed_paths) - journaled)

    git_summary = {
        "is_git": bool(git_now.get("is_git")),
        "head_before": git_before.get("head"),
        "head_now": git_now.get("head"),
        "head_changed": git_before.get("head") != git_now.get("head"),
        "branch_before": git_before.get("branch"),
        "branch_now": git_now.get("branch"),
        "branch_changed": git_before.get("branch") != git_now.get("branch"),
        "index_before": git_before.get("staged_diff_sha256"),
        "index_now": git_now.get("staged_diff_sha256"),
        "index_changed_from_baseline": git_before.get("staged_diff_sha256") != git_now.get("staged_diff_sha256"),
        "worktree_before": git_before.get("worktree_diff_sha256"),
        "worktree_now": git_now.get("worktree_diff_sha256"),
        "status": git_now.get("status", []),
        "repo_probe_failed": bool(git_now.get("repo_probe_failed")),
        "status_probe_failed": bool(git_now.get("status_probe_failed")),
        "head_probe_failed": bool(git_now.get("head_probe_failed")),
        "branch_probe_failed": bool(git_now.get("branch_probe_failed")),
        "probe_degraded": bool(git_now.get("probe_degraded")),
    }
    return {
        "root": str(root),
        "generation": store.generation(),
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "renamed": rename_pairs,
        "protected_paths": sorted(protected),
        "agent_owned_paths": sorted(journaled),
        "unexpected_protected_changes": unexpected_protected,
        "ignored_watch": store.get_meta("ignored_watch", {"watched_paths": [], "opaque_paths": []}),
        "git": git_summary,
    }
