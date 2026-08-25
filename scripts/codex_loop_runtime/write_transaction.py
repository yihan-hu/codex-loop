from __future__ import annotations

import ctypes
import errno
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .state import NO_WRITE_PROFILES, StateStore
from .workspace import ensure_inside_workspace, hash_bytes, hash_file, workspace_fingerprint

MAX_LOCAL_WRITE_BYTES = 16 * 1024 * 1024


_AT_FDCWD = -100
_RENAME_EXCHANGE = 2


def _renameat2_exchange(left: str | Path, right: str | Path) -> None:
    """Atomically exchange two pathnames on Linux; fail closed elsewhere."""
    if os.name == "nt":
        raise NotImplementedError("atomic rename exchange is unavailable on Windows")
    libc = ctypes.CDLL(None, use_errno=True)
    func = getattr(libc, "renameat2", None)
    if func is None:
        raise NotImplementedError("renameat2 is unavailable on this platform")
    func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    func.restype = ctypes.c_int
    rc = func(_AT_FDCWD, os.fsencode(left), _AT_FDCWD, os.fsencode(right), _RENAME_EXCHANGE)
    if rc != 0:
        err = ctypes.get_errno()
        if err in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise NotImplementedError("filesystem does not support atomic rename exchange")
        raise OSError(err, os.strerror(err), str(left), str(right))


def _commit_new_no_replace(temp_name: str, path: Path) -> None:
    """Atomically publish a new file without replacing a concurrent creator."""
    try:
        os.link(temp_name, path)
    except FileExistsError as exc:
        raise RuntimeError(f"write target appeared concurrently: {path}") from exc
    except OSError as exc:
        raise RuntimeError(
            f"filesystem cannot provide atomic no-replace creation for {path}; use a host-visible file operation"
        ) from exc
    os.unlink(temp_name)


def _commit_existing_exchange(temp_name: str, path: Path, pre_hash: str, pre_mode: int) -> tuple[bool, str | None]:
    """Exchange agent temp with target, verify displaced preimage, and roll back on mismatch.

    Returns (committed, recovery_path). recovery_path is populated only if a mismatch
    is detected and the rollback exchange itself fails; the displaced concurrent user
    preimage is deliberately preserved there.
    """
    try:
        _renameat2_exchange(temp_name, path)
    except (NotImplementedError, OSError) as exc:
        raise RuntimeError(
            f"filesystem cannot provide atomic compare-exchange for {path}; use a host-visible file operation"
        ) from exc
    displaced_hash = hash_file(Path(temp_name))
    try:
        displaced_mode = stat.S_IMODE(Path(temp_name).lstat().st_mode)
    except OSError:
        displaced_mode = -1
    if displaced_hash == pre_hash and displaced_mode == int(pre_mode):
        return True, None

    # The object at target changed after the last observation. Restore it atomically.
    try:
        _renameat2_exchange(temp_name, path)
    except Exception as rollback_exc:
        recovery = Path(temp_name).with_name(f".{path.name}.codex-loop-recovery-{os.getpid()}-{next(tempfile._get_candidate_names())}")
        try:
            os.replace(temp_name, recovery)
            recovery_path = str(recovery)
        except Exception:
            recovery_path = temp_name
        raise RuntimeError(
            f"concurrent modification detected for {path}; rollback failed, displaced user preimage preserved at {recovery_path}"
        ) from rollback_exc
    raise RuntimeError(f"concurrent modification detected before atomic replacement: {path}")


@dataclass(frozen=True)
class WriteResult:
    path: str
    pre_sha256: str | None
    post_sha256: str
    generation: int


def _reject_symlink_components(root: Path, target: Path) -> None:
    root = root.resolve()
    relative = target.relative_to(root)
    cur = root
    for part in relative.parts:
        cur = cur / part
        try:
            mode = cur.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise RuntimeError(f"guarded write refuses symlink path component: {cur}")
        if cur != target and not stat.S_ISDIR(mode):
            raise RuntimeError(f"guarded write parent is not a directory: {cur}")


def guarded_write(
    root: Path,
    store: StateStore,
    target: Path,
    content: bytes,
    *,
    expected_sha256: str | None = None,
    allow_protected: bool = False,
    protected_override_reason: str | None = None,
) -> WriteResult:
    store.ensure_active()
    active_isolation = store.active_isolation()
    if active_isolation is not None and str(active_isolation.get("mutation_policy")) == "read_only":
        raise PermissionError(
            f"active isolated task {active_isolation.get('isolation_id')} is read-only; local guarded writes are forbidden"
        )
    if len(content) > MAX_LOCAL_WRITE_BYTES:
        raise ValueError("local guarded write payload exceeds 16 MiB; use a host-visible file operation")
    profile = str(store.get_meta("profile", "regular"))
    if profile in NO_WRITE_PROFILES:
        raise PermissionError(f"task profile {profile} does not permit local writes")
    root = root.resolve()
    lexical = Path(target)
    if not lexical.is_absolute():
        lexical = root / lexical
    lexical = Path(os.path.abspath(lexical))
    try:
        lexical.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"write target is outside workspace: {lexical}") from exc
    _reject_symlink_components(root, lexical)
    path = lexical

    exists = path.exists()
    if exists:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise RuntimeError(f"guarded writer only replaces regular files: {path}")
        if expected_sha256 is None:
            raise RuntimeError("existing files require --expected-sha256 from the latest observed preimage")
    _reject_symlink_components(root, path)
    pre_hash = hash_file(path)
    if expected_sha256 is not None and pre_hash != expected_sha256:
        raise RuntimeError(f"preimage changed for {path}: expected {expected_sha256}, found {pre_hash}")

    rel = path.relative_to(root).as_posix()
    protected = rel in store.protected_paths()
    if protected and not allow_protected:
        raise PermissionError(f"pre-existing user change is protected: {rel}; pass explicit protected-change authorization only when required")
    override_reason = None
    if protected and allow_protected:
        override_reason = (protected_override_reason or "").strip()
        if not override_reason:
            raise ValueError("overriding a protected pre-existing change requires a concise reason")

    payload = {"path": str(path), "pre_sha256": pre_hash, "size": len(content), "protected": protected}
    _reject_symlink_components(root, path)
    if hash_file(path) != pre_hash:
        raise RuntimeError(f"preimage changed while pre-write checks ran: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(root, path)
    old_mode = (path.stat().st_mode & 0o7777) if exists else 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.codex-loop-", dir=path.parent)
    preserve_temp = False
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, old_mode)
        _reject_symlink_components(root, path)
        if exists:
            # Do not trust a path-level check as the commit gate. The atomic exchange
            # captures the exact object present at the commit instant into temp_name.
            try:
                _commit_existing_exchange(temp_name, path, pre_hash or "", old_mode)
            except RuntimeError as exc:
                if "preserved at" in str(exc):
                    preserve_temp = True
                raise
        else:
            _commit_new_no_replace(temp_name, path)
    finally:
        if not preserve_temp:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    post_hash = hash_bytes(content)
    generation = store.record_mutation(
        rel, "write", pre_hash, post_hash, protected=protected, override_reason=override_reason
    )
    store.set_meta("workspace_fingerprint", workspace_fingerprint(root))
    return WriteResult(str(path), pre_hash, post_hash, generation)
