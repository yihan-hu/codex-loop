from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GIT_PROBE_TIMEOUT_SECONDS = 30.0
MAX_IGNORED_WATCH_FILES = 256
MAX_IGNORED_WATCH_FILE_BYTES = 1024 * 1024
MAX_IGNORED_WATCH_TOTAL_BYTES = 8 * 1024 * 1024

from .environment import build_internal_git_env


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    sha256: str
    size: int
    mode: int


def _trusted_system_path() -> str:
    if os.name != "nt":
        return os.defpath
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        return ""
    return os.pathsep.join([str(Path(system_root) / "System32"), system_root])


def _workspace_hint(cwd: Path) -> Path:
    cursor = cwd.resolve()
    while True:
        try:
            if (cursor / ".git").exists():
                return cursor
        except OSError:
            pass
        if cursor.parent == cursor:
            return cwd.resolve()
        cursor = cursor.parent


def _git_executable(cwd: Path) -> str:
    found = shutil.which("git", path=_trusted_system_path())
    if not found:
        raise FileNotFoundError("trusted system git executable not found")
    executable = Path(found).resolve()
    workspace = _workspace_hint(cwd)
    if executable == workspace or executable.is_relative_to(workspace):
        raise PermissionError(f"runtime-owned Git probe resolved Git inside workspace: {executable}")
    return str(executable)


def run_git(cwd: Path, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[bytes]:
    env = build_internal_git_env()
    git = _git_executable(cwd)
    argv = [git, "-c", "core.fsmonitor=false", "-c", "core.filemode=true", "-c", "diff.external=", *args]
    proc = subprocess.Popen(
        argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        close_fds=True, start_new_session=(os.name != "nt"),
    )
    try:
        stdout, stderr = proc.communicate(timeout=GIT_PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        _terminate_probe(proc)
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(argv, GIT_PROBE_TIMEOUT_SECONDS, output=stdout, stderr=stderr) from exc
    completed = subprocess.CompletedProcess(argv, int(proc.returncode), stdout, stderr)
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, argv, output=stdout, stderr=stderr)
    return completed


def repo_root(cwd: str | os.PathLike[str]) -> Path:
    path = Path(cwd).resolve()
    try:
        proc = run_git(path, ["rev-parse", "--show-toplevel"])
        if proc.returncode == 0:
            return Path(proc.stdout.decode("utf-8", errors="surrogateescape").strip()).resolve()
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        pass
    cursor = path
    while True:
        try:
            if (cursor / ".git").exists():
                return cursor
        except OSError:
            pass
        if cursor.parent == cursor:
            return path
        cursor = cursor.parent


def git_repo_probe(root: Path) -> bool | None:
    try:
        proc = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return False
    return proc.stdout.decode("utf-8", errors="replace").strip().lower() == "true"


def _has_git_marker(root: Path) -> bool:
    try:
        return (root / ".git").exists() or (root / ".git").is_symlink()
    except OSError:
        return False


def is_git_repo(root: Path) -> bool:
    return git_repo_probe(root) is True


def _git_text_probe(root: Path, args: list[str]) -> tuple[str | None, bool]:
    try:
        proc = run_git(root, args)
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return None, True
    if proc.returncode != 0:
        return None, False
    return proc.stdout.decode("utf-8", errors="replace").strip(), False


def _git_text(root: Path, args: list[str]) -> str | None:
    value, _failed = _git_text_probe(root, args)
    return value


def _git_bytes(root: Path, args: list[str]) -> bytes | None:
    try:
        proc = run_git(root, args)
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _terminate_probe(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name != "nt":
            import signal
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=1.0)
    except Exception:
        try:
            if os.name != "nt":
                import signal
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait(timeout=1.0)
        except Exception:
            pass


def _git_output_sha256(root: Path, args: list[str]) -> str | None:
    try:
        env = build_internal_git_env()
        git = _git_executable(root)
        proc = subprocess.Popen(
            [git, "-c", "core.fsmonitor=false", "-c", "diff.external=", *args],
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=(os.name != "nt"),
        )
    except (FileNotFoundError, PermissionError, OSError):
        return None
    assert proc.stdout is not None
    h = hashlib.sha256()
    read_error: list[BaseException] = []

    def reader() -> None:
        try:
            for chunk in iter(lambda: proc.stdout.read(1024 * 1024), b""):
                h.update(chunk)
        except BaseException as exc:
            read_error.append(exc)
        finally:
            try:
                proc.stdout.close()
            except OSError:
                pass

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    try:
        code = proc.wait(timeout=GIT_PROBE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate_probe(proc)
        thread.join(timeout=2.0)
        return None
    thread.join(timeout=2.0)
    if thread.is_alive() or read_error:
        _terminate_probe(proc)
        return None
    return h.hexdigest() if code == 0 else None


def _git_head_probe(root: Path) -> tuple[str | None, bool]:
    try:
        proc = run_git(root, ["rev-parse", "--verify", "--quiet", "HEAD"])
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return None, True
    if proc.returncode == 0:
        return proc.stdout.decode("utf-8", errors="replace").strip(), False
    # `--verify --quiet` returns 1 when HEAD legitimately has no commit yet.
    if proc.returncode == 1:
        return None, False
    return None, True


def _git_branch_probe(root: Path) -> tuple[str | None, bool]:
    try:
        proc = run_git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return None, True
    if proc.returncode == 0:
        return proc.stdout.decode("utf-8", errors="replace").strip(), False
    # symbolic-ref exits 1 for a legitimate detached HEAD.
    if proc.returncode == 1:
        return None, False
    return None, True


def git_head(root: Path) -> str | None:
    return _git_head_probe(root)[0]


def git_branch(root: Path) -> str | None:
    return _git_branch_probe(root)[0]


def git_status_porcelain_z(root: Path) -> bytes | None:
    return _git_bytes(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])


def parse_status_porcelain_z(data: bytes) -> list[dict[str, Any]]:
    parts = data.split(b"\0")
    result: list[dict[str, Any]] = []
    i = 0
    while i < len(parts):
        raw = parts[i]
        i += 1
        if not raw:
            continue
        text = raw.decode("utf-8", errors="surrogateescape")
        if len(text) < 3:
            continue
        xy = text[:2]
        path = text[3:] if len(text) >= 3 and text[2] == " " else text[2:].lstrip()
        entry: dict[str, Any] = {
            "index": xy[0],
            "worktree": xy[1],
            "path": path,
            "kind": "untracked" if xy == "??" else "changed",
        }
        if ("R" in xy or "C" in xy) and i < len(parts) and parts[i]:
            old_path = parts[i].decode("utf-8", errors="surrogateescape")
            i += 1
            entry["old_path"] = old_path
            entry["kind"] = "renamed" if "R" in xy else "copied"
        result.append(entry)
    return result


def git_status(root: Path) -> str:
    raw = git_status_porcelain_z(root)
    if raw is None:
        return "<git status unavailable>"
    return raw.replace(b"\0", b"\n").decode("utf-8", errors="replace")


def git_state(root: Path) -> dict[str, Any]:
    repo_probe = git_repo_probe(root)
    if repo_probe is not True:
        if repo_probe is None and _has_git_marker(root):
            return {
                "is_git": True,
                "repo_probe_failed": True,
                "status_probe_failed": True,
                "probe_degraded": True,
                "protected_paths": [],
                "status": [],
            }
        return {"is_git": False}
    status_raw = git_status_porcelain_z(root)
    status_probe_failed = status_raw is None
    head, head_probe_failed = _git_head_probe(root)
    branch, branch_probe_failed = _git_branch_probe(root)
    status = parse_status_porcelain_z(status_raw or b"")
    protected = set()
    for entry in status:
        protected.add(str(entry["path"]))
        if entry.get("old_path"):
            protected.add(str(entry["old_path"]))
    staged = _git_output_sha256(root, ["diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"])
    worktree = _git_output_sha256(root, ["diff", "--binary", "--no-ext-diff", "--no-textconv"])
    return {
        "is_git": True,
        "head": head,
        "branch": branch,
        "status": status,
        "status_sha256": hash_bytes(status_raw) if status_raw is not None else None,
        "staged_diff_sha256": staged,
        "worktree_diff_sha256": worktree,
        "repo_probe_failed": False,
        "status_probe_failed": status_probe_failed,
        "head_probe_failed": head_probe_failed,
        "branch_probe_failed": branch_probe_failed,
        "probe_degraded": status_probe_failed or head_probe_failed or branch_probe_failed or staged is None or worktree is None,
        "protected_paths": sorted(protected),
    }


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_mode(path: Path) -> int | None:
    try:
        return stat.S_IMODE(path.lstat().st_mode)
    except (FileNotFoundError, OSError):
        return None


def hash_file(path: Path) -> str | None:
    try:
        st = path.lstat()
        if stat.S_ISLNK(st.st_mode):
            raw = os.fsencode(os.readlink(path))
            return hashlib.sha256(b"symlink\0" + raw).hexdigest()
        if not stat.S_ISREG(st.st_mode):
            return None
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return None


def _git_files(root: Path) -> list[Path] | None:
    try:
        proc = run_git(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [root / raw.decode("utf-8", errors="surrogateescape") for raw in proc.stdout.split(b"\0") if raw]


def _git_ignored_roots(root: Path) -> list[Path] | None:
    try:
        proc = run_git(root, ["ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--directory"])
    except (FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [root / raw.decode("utf-8", errors="surrogateescape") for raw in proc.stdout.split(b"\0") if raw]


def ignored_watch_state(root: Path) -> dict[str, Any]:
    """Bounded content monitoring for ignored inputs that may affect local validation.

    Small ignored files/trees are hashed and become protected baseline inputs. Large or
    unreadable ignored paths are explicit opaque paths rather than silent freshness gaps.
    """
    root = root.resolve()
    roots = _git_ignored_roots(root)
    if roots is None:
        return {"watched": [], "opaque_paths": ["<ignored-probe-failed>"]}
    watched: dict[str, FileSnapshot] = {}
    opaque: set[str] = set()
    total = 0

    def add_file(path: Path, opaque_owner: str | None = None) -> bool:
        nonlocal total
        try:
            st = path.lstat()
            rel = str(path.relative_to(root))
        except (OSError, ValueError):
            if opaque_owner:
                opaque.add(opaque_owner)
            return False
        if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            return True
        if len(watched) >= MAX_IGNORED_WATCH_FILES:
            opaque.add(opaque_owner or rel)
            return False
        size = int(st.st_size)
        if stat.S_ISREG(st.st_mode) and size > MAX_IGNORED_WATCH_FILE_BYTES:
            opaque.add(opaque_owner or rel)
            return False
        if total + size > MAX_IGNORED_WATCH_TOTAL_BYTES:
            opaque.add(opaque_owner or rel)
            return False
        digest = hash_file(path)
        if digest is None:
            opaque.add(opaque_owner or rel)
            return False
        watched[rel] = FileSnapshot(rel, digest, size, stat.S_IMODE(st.st_mode))
        total += size
        return True

    for entry in roots:
        try:
            rel_owner = str(entry.relative_to(root)).rstrip("/") or "."
            st = entry.lstat()
        except (OSError, ValueError):
            try:
                rel_owner = str(entry.relative_to(root)).rstrip("/") or "."
            except ValueError:
                rel_owner = str(entry)
            opaque.add(rel_owner)
            continue
        if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            stop = False
            try:
                for current, dirs, files in os.walk(entry, followlinks=False):
                    current_path = Path(current)
                    for name in list(dirs):
                        child = current_path / name
                        try:
                            if child.is_symlink() and not add_file(child, rel_owner):
                                stop = True; break
                        except OSError:
                            opaque.add(rel_owner); stop = True; break
                    if stop:
                        break
                    dirs[:] = [d for d in dirs if not (current_path / d).is_symlink()]
                    for name in files:
                        if not add_file(current_path / name, rel_owner):
                            stop = True; break
                    if stop:
                        break
            except OSError:
                opaque.add(rel_owner)
        else:
            add_file(entry, rel_owner)
    return {
        "watched": [watched[key] for key in sorted(watched)],
        "opaque_paths": sorted(opaque),
        "watched_bytes": total,
    }


def _ignored_content_fingerprint(root: Path) -> bytes:
    state = ignored_watch_state(root)
    data = bytearray()
    for item in state["watched"]:
        data.extend(item.path.encode("utf-8", errors="surrogateescape")); data.extend(b"\0")
        data.extend(item.sha256.encode()); data.extend(b"\0")
        data.extend(str(item.mode).encode()); data.extend(b"\0")
    data.extend(b"OPAQUE\0")
    for rel in state["opaque_paths"]:
        data.extend(str(rel).encode("utf-8", errors="surrogateescape")); data.extend(b"\0")
    return bytes(data)


def _non_git_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        original_dirs = list(dirs)
        for name in original_dirs:
            path = current_path / name
            try:
                if path.is_symlink():
                    result.append(path)
            except OSError:
                pass
        dirs[:] = [d for d in original_dirs if d != ".git" and not (current_path / d).is_symlink()]
        for name in files:
            result.append(current_path / name)
    return result


def snapshot_files(root: Path) -> list[FileSnapshot]:
    root = root.resolve()
    files = _git_files(root)
    if files is None:
        files = _non_git_files(root)
    else:
        ignored = ignored_watch_state(root)
        files = [*files, *(root / item.path for item in ignored["watched"])]
    result: list[FileSnapshot] = []
    for path in files:
        try:
            st = path.lstat()
            digest = hash_file(path)
            if digest is None:
                continue
            rel = str(path.relative_to(root))
            result.append(FileSnapshot(rel, digest, st.st_size, stat.S_IMODE(st.st_mode)))
        except (OSError, PermissionError, ValueError):
            continue
    result.sort(key=lambda item: item.path)
    return result


def _untracked_content_fingerprint(root: Path) -> bytes:
    status_raw = git_status_porcelain_z(root)
    if status_raw is None:
        return b"<git-status-probe-failed>"
    data = bytearray()
    for entry in parse_status_porcelain_z(status_raw):
        if entry["kind"] != "untracked":
            continue
        path = root / str(entry["path"])
        digest = hash_file(path)
        mode = file_mode(path)
        if digest is None:
            continue
        data.extend(str(entry["path"]).encode("utf-8", errors="surrogateescape"))
        data.extend(b"\0")
        data.extend(digest.encode())
        data.extend(b"\0")
        data.extend(str(mode if mode is not None else -1).encode())
        data.extend(b"\0")
    return bytes(data)


def workspace_fingerprint(root: Path) -> str:
    root = root.resolve()
    repo_probe = git_repo_probe(root)
    if repo_probe is True:
        h = hashlib.sha256()
        head, head_failed = _git_head_probe(root)
        branch, branch_failed = _git_branch_probe(root)
        h.update((head or "").encode())
        h.update(b"\0")
        h.update((branch or "").encode())
        h.update(b"\0")
        if head_failed or branch_failed:
            h.update(b"<git-identity-probe-failed>")
        status_raw = git_status_porcelain_z(root)
        if status_raw is None:
            h.update(b"<git-status-probe-failed>")
        else:
            h.update(status_raw)
        staged = _git_output_sha256(root, ["diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv"])
        worktree = _git_output_sha256(root, ["diff", "--binary", "--no-ext-diff", "--no-textconv"])
        if status_raw is None or staged is None or worktree is None or head_failed or branch_failed:
            # Fail closed: a broken/slow Git probe must never make stale validation look fresh.
            h.update(b"\0DEGRADED_FULL_FILE_FINGERPRINT\0")
            for item in snapshot_files(root):
                h.update(item.path.encode("utf-8", errors="surrogateescape")); h.update(b"\0")
                h.update(item.sha256.encode()); h.update(b"\0")
                h.update(str(item.mode).encode()); h.update(b"\0")
        else:
            h.update(b"\0INDEX\0"); h.update(staged.encode())
            h.update(b"\0WORKTREE\0"); h.update(worktree.encode())
        h.update(b"\0UNTRACKED\0")
        h.update(_untracked_content_fingerprint(root))
        h.update(b"\0IGNORED_WATCH\0")
        h.update(_ignored_content_fingerprint(root))
        return h.hexdigest()
    prefix = "GIT_REPO_PROBE_FAILED\n" if repo_probe is None and _has_git_marker(root) else "NON_GIT\n"
    payload = prefix + "\n".join(f"{x.path}\0{x.sha256}\0{x.size}\0{x.mode:o}" for x in snapshot_files(root))
    return hashlib.sha256(payload.encode("utf-8", errors="surrogateescape")).hexdigest()


def ensure_inside_workspace(root: Path, target: Path) -> Path:
    root = root.resolve()
    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path is outside workspace: {target}") from exc
    return resolved


def workspace_lexical_path(root: Path, target: Path) -> Path:
    root = root.resolve()
    lexical = Path(target)
    if not lexical.is_absolute():
        lexical = root / lexical
    lexical = Path(os.path.abspath(lexical))
    try:
        lexical.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"path is outside workspace: {lexical}") from exc
    return lexical


def _reject_symlink_parents(root: Path, target: Path) -> None:
    root = root.resolve()
    lexical = workspace_lexical_path(root, target)
    cur = root
    parts = lexical.relative_to(root).parts
    for part in parts[:-1]:
        cur = cur / part
        try:
            st = cur.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            raise RuntimeError(f"workspace read refuses symlink parent component: {cur}")
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError(f"workspace read parent is not a directory: {cur}")


def hash_workspace_path(root: Path, target: Path) -> tuple[Path, str | None]:
    lexical = workspace_lexical_path(root, target)
    _reject_symlink_parents(root, lexical)
    return lexical, hash_file(lexical)
