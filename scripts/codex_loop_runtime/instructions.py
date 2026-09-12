from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass
from pathlib import Path

from .workspace import ensure_inside_workspace, repo_root

# Local deterministic subset only. Host trust decisions, host/user instructions,
# multi-environment assembly, and the full configurable upstream project-root marker
# policy remain host-owned and must not be inferred from workspace text here.
DEFAULT_FILENAMES = ("AGENTS.override.md", "AGENTS.md")


@dataclass(frozen=True)
class InstructionEntry:
    path: str
    contents: str
    sha256: str
    complete: bool
    provenance: str = "workspace_instruction"


@dataclass(frozen=True)
class InstructionDiscovery:
    entries: tuple[InstructionEntry, ...]
    complete: bool
    truncated_paths: tuple[str, ...]
    max_bytes: int
    bytes_read: int


def _search_dirs(root: Path, cwd: Path) -> list[Path]:
    root = root.resolve()
    cwd = cwd.resolve()
    try:
        cwd.relative_to(root)
    except ValueError:
        return [cwd]
    dirs: list[Path] = []
    cursor = cwd
    while True:
        dirs.append(cursor)
        if cursor == root:
            break
        cursor = cursor.parent
    dirs.reverse()
    return dirs


def _candidate(path: Path, root: Path) -> tuple[Path, Path] | None:
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        resolved = ensure_inside_workspace(root, path)
        try:
            target_st = resolved.stat()
        except OSError:
            return None
        if not stat.S_ISREG(target_st.st_mode):
            raise RuntimeError(f"instruction symlink target is not a regular file: {path}")
        return path, resolved
    if stat.S_ISREG(st.st_mode):
        return path, path
    return None


def discover(
    cwd: str | Path,
    *,
    fallback_filenames: tuple[str, ...] = (),
    max_bytes: int = 32 * 1024,
) -> InstructionDiscovery:
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    cwd_path = Path(cwd).resolve()
    root = repo_root(cwd_path)
    candidates = list(DEFAULT_FILENAMES)
    for name in fallback_filenames:
        if not name:
            continue
        candidate = Path(name)
        if candidate.name != name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError(f"instruction fallback must be a filename, not a path: {name!r}")
        if name not in candidates:
            candidates.append(name)

    selected_paths: list[tuple[Path, Path]] = []
    for directory in _search_dirs(root, cwd_path):
        for name in candidates:
            selected = _candidate(directory / name, root)
            if selected is not None:
                selected_paths.append(selected)
                break

    remaining = max_bytes
    entries: list[InstructionEntry] = []
    truncated: list[str] = []
    bytes_read = 0
    for lexical, read_target in selected_paths:
        if remaining <= 0:
            truncated.append(str(lexical))
            continue
        with read_target.open("rb") as handle:
            probe = handle.read(remaining + 1)
        entry_complete = len(probe) <= remaining
        data = probe if entry_complete else probe[:remaining]
        if not entry_complete:
            truncated.append(str(lexical))
        if not data:
            continue
        text = data.decode("utf-8", errors="replace")
        if text.strip():
            entries.append(
                InstructionEntry(
                    path=str(lexical),
                    contents=text,
                    sha256=hashlib.sha256(data).hexdigest(),
                    complete=entry_complete,
                )
            )
        used = len(data)
        bytes_read += used
        remaining -= used

    return InstructionDiscovery(
        entries=tuple(entries),
        complete=not truncated,
        truncated_paths=tuple(truncated),
        max_bytes=max_bytes,
        bytes_read=bytes_read,
    )
