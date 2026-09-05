from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .host_config import effective_host_profile, host_config_set

CACHE_SCHEMA_VERSION = 1
CACHE_KIND = "codex_loop_workspace_cache"
CONSUMPTION_KIND = "codex_loop_workspace_cache_consumed"
CACHE_TTL_DAYS = 3
CACHE_DRIVE_FOLDER = "Codex Loop/.runtime/workspace-cache"
_CACHE_NAME_RE = re.compile(
    r"^workspace-cache-v1-(?P<cache_id>[0-9a-f]{32})-(?P<created>[0-9]{8}T[0-9]{6}Z)-(?P<sha>[0-9a-f]{64})\.tar\.gz$"
)
_CONSUMED_NAME_RE = re.compile(r"^workspace-cache-consumed-v1-(?P<cache_id>[0-9a-f]{32})\.json$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA64_RE = re.compile(r"^[0-9a-f]{64}$")


def _utc_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _git(root: Path, *args: str, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(
        ["git", *args], cwd=root, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed: {proc.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return proc


def _git_text(root: Path, *args: str) -> str:
    return _git(root, *args).stdout.decode("utf-8", errors="strict").strip()


def _repo_identity(root: Path) -> tuple[str, str, str | None]:
    head = _git_text(root, "rev-parse", "HEAD").lower()
    tree = _git_text(root, "rev-parse", "HEAD^{tree}").lower()
    branch_proc = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    branch = None if branch_proc.returncode != 0 else branch_proc.stdout.decode("utf-8").strip()
    if not _SHA40_RE.fullmatch(head) or not _SHA40_RE.fullmatch(tree):
        raise RuntimeError("workspace cache requires full Git commit/tree identity")
    return head, tree, branch or None


def _untracked_paths(root: Path) -> list[str]:
    raw = _git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    return [p.decode("utf-8", errors="surrogateescape") for p in raw.split(b"\0") if p]


def _safe_rel(path_text: str) -> PurePosixPath:
    path = PurePosixPath(path_text)
    if path.is_absolute() or not path.parts or ".." in path.parts or path.parts[0] in {".git", ""}:
        raise ValueError(f"unsafe workspace cache path: {path_text}")
    return path


def _untracked_manifest(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for text in sorted(paths):
        rel = _safe_rel(text)
        path = root.joinpath(*rel.parts)
        st = path.lstat()
        mode = stat.S_IMODE(st.st_mode)
        if stat.S_ISREG(st.st_mode):
            entries.append({
                "path": rel.as_posix(),
                "type": "file",
                "mode": mode,
                "size": st.st_size,
                "sha256": _sha256_file(path),
            })
        elif stat.S_ISLNK(st.st_mode):
            target = os.readlink(path)
            target_path = Path(target)
            if target_path.is_absolute():
                raise ValueError(f"absolute untracked symlink is not cacheable: {text}")
            resolved = (path.parent / target_path).resolve(strict=False)
            try:
                resolved.relative_to(root.resolve())
            except ValueError as exc:
                raise ValueError(f"untracked symlink escapes workspace: {text} -> {target}") from exc
            entries.append({
                "path": rel.as_posix(),
                "type": "symlink",
                "mode": mode,
                "target": target,
                "sha256": _sha256_bytes(target.encode("utf-8", errors="surrogateescape")),
            })
        else:
            raise ValueError(f"unsupported untracked filesystem entry: {text}")
    return entries


def _write_untracked_tar(root: Path, entries: list[dict[str, Any]], output: Path) -> None:
    with tarfile.open(output, "w") as tf:
        for entry in entries:
            rel = _safe_rel(str(entry["path"]))
            path = root.joinpath(*rel.parts)
            info = tarfile.TarInfo(rel.as_posix())
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = int(entry["mode"])
            if entry["type"] == "file":
                info.type = tarfile.REGTYPE
                info.size = int(entry["size"])
                with path.open("rb") as f:
                    tf.addfile(info, f)
            elif entry["type"] == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = str(entry["target"])
                info.size = 0
                tf.addfile(info)
            else:
                raise ValueError(f"unsupported untracked manifest type: {entry['type']}")


def _state_components(root: Path, temp_dir: Path) -> dict[str, Any]:
    staged = _git(root, "diff", "--cached", "--binary", "--full-index", "HEAD", "--").stdout
    unstaged = _git(root, "diff", "--binary", "--full-index", "--").stdout
    staged_path = temp_dir / "staged.patch"
    unstaged_path = temp_dir / "unstaged.patch"
    staged_path.write_bytes(staged)
    unstaged_path.write_bytes(unstaged)

    untracked = _untracked_manifest(root, _untracked_paths(root))
    untracked_path = temp_dir / "untracked.tar"
    _write_untracked_tar(root, untracked, untracked_path)

    return {
        "staged": {"file": "staged.patch", "size": len(staged), "sha256": _sha256_bytes(staged)},
        "unstaged": {"file": "unstaged.patch", "size": len(unstaged), "sha256": _sha256_bytes(unstaged)},
        "untracked": {
            "file": "untracked.tar",
            "size": untracked_path.stat().st_size,
            "sha256": _sha256_file(untracked_path),
            "entries": untracked,
        },
    }


def _state_fingerprint(head: str, tree: str, components: dict[str, Any]) -> str:
    return _canonical_sha256({
        "head_commit": head,
        "head_tree": tree,
        "staged_sha256": components["staged"]["sha256"],
        "unstaged_sha256": components["unstaged"]["sha256"],
        "untracked_entries": components["untracked"]["entries"],
    })


def _build_bundle(root: Path, branch: str | None, output: Path) -> dict[str, Any]:
    head = _git_text(root, "rev-parse", "HEAD")
    if branch:
        ref = f"refs/heads/{branch}"
        ref_head = _git_text(root, "rev-parse", ref)
        if ref_head != head:
            raise RuntimeError("current branch ref does not match HEAD")
        bundle_ref = ref
        temporary_ref = None
    else:
        temporary_ref = f"refs/heads/codex-loop-cache-{uuid.uuid4().hex}"
        _git(root, "update-ref", temporary_ref, head)
        bundle_ref = temporary_ref
    try:
        _git(root, "bundle", "create", str(output), bundle_ref)
    finally:
        if temporary_ref:
            _git(root, "update-ref", "-d", temporary_ref, check=False)
    verify = _git(root, "bundle", "verify", str(output), check=False)
    if verify.returncode != 0:
        raise RuntimeError(
            "workspace cache Git bundle is incomplete; the workspace must contain the Git object closure for HEAD: "
            + verify.stderr.decode("utf-8", errors="replace").strip()
        )
    return {"file": "repo.bundle", "size": output.stat().st_size, "sha256": _sha256_file(output)}


def _write_capsule(parts_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_name = tempfile.mkstemp(prefix=".workspace-cache-", suffix=".tar", dir=str(output.parent))
    os.close(fd)
    raw = Path(raw_name)
    try:
        with tarfile.open(raw, "w") as tf:
            for name in ("manifest.json", "repo.bundle", "staged.patch", "unstaged.patch", "untracked.tar"):
                path = parts_dir / name
                info = tf.gettarinfo(str(path), arcname=name)
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with path.open("rb") as f:
                    tf.addfile(info, f)
        with raw.open("rb") as src, output.open("wb") as dst_raw, gzip.GzipFile(
            filename="", mode="wb", fileobj=dst_raw, mtime=0
        ) as dst:
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(chunk)
    finally:
        raw.unlink(missing_ok=True)


def build_workspace_cache(
    root: Path,
    *,
    output: Path,
    repository: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    if not (root / ".git").exists():
        raise RuntimeError("workspace cache requires a real Git working tree")
    head, tree, branch = _repo_identity(root)
    current = _utc_now(now)
    cache_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="codex-loop-workspace-cache-") as tmp_name:
        parts = Path(tmp_name)
        bundle = _build_bundle(root, branch, parts / "repo.bundle")
        components = _state_components(root, parts)
        manifest = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "kind": CACHE_KIND,
            "cache_id": cache_id,
            "created_at": _iso(current),
            "expires_at": _iso(current + timedelta(days=CACHE_TTL_DAYS)),
            "ttl_days": CACHE_TTL_DAYS,
            "repository": repository,
            "branch": branch,
            "head_commit": head,
            "head_tree": tree,
            "git_bundle": bundle,
            "workspace_state": components,
            "state_fingerprint": _state_fingerprint(head, tree, components),
            "privacy": {
                "ignored_files_included": False,
                "git_config_included": False,
                "git_hooks_included": False,
                "credentials_included": False,
            },
            "drive": {
                "backend": "google_drive",
                "folder_path": CACHE_DRIVE_FOLDER,
                "visibility": "private",
                "one_shot": True,
                "cleanup_on_successful_restore": False,
                "cleanup_requires_llm_review": True,
                "cleanup_requires_human_confirmation": True,
                "cleanup_failure_invalidates_restore": False,
            },
        }
        (parts / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        _write_capsule(parts, output.resolve())

    outer_sha = _sha256_file(output.resolve())
    created_token = current.strftime("%Y%m%dT%H%M%SZ")
    drive_file_name = f"workspace-cache-v1-{cache_id}-{created_token}-{outer_sha}.tar.gz"
    consumed_receipt_name = f"workspace-cache-consumed-v1-{cache_id}.json"
    return {
        "schema_version": 1,
        "status": "WORKSPACE_CACHE_CREATED",
        "cache_id": cache_id,
        "capsule_path": str(output.resolve()),
        "capsule_size": output.resolve().stat().st_size,
        "capsule_sha256": outer_sha,
        "drive_file_name": drive_file_name,
        "drive_folder_path": CACHE_DRIVE_FOLDER,
        "consumed_receipt_name": consumed_receipt_name,
        "created_at": manifest["created_at"],
        "expires_at": manifest["expires_at"],
        "head_commit": head,
        "head_tree": tree,
        "branch": branch,
        "state_fingerprint": manifest["state_fingerprint"],
        "cache_folder_registration_required": True,
        "next": "register drive_folder_path in host-local Drive cache policy, upload this exact private capsule, and retain the returned Drive object identity in host-private state; do not auto-delete it",
    }


def _safe_read_capsule(capsule: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    allowed = {"manifest.json", "repo.bundle", "staged.patch", "unstaged.patch", "untracked.tar"}
    payloads: dict[str, bytes] = {}
    with tarfile.open(capsule, "r:gz") as tf:
        members = tf.getmembers()
        names = {m.name for m in members}
        if names != allowed:
            raise ValueError(f"workspace cache capsule entries mismatch: {sorted(names)}")
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                raise ValueError(f"unsafe workspace cache member: {member.name}")
            source = tf.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read workspace cache member: {member.name}")
            payloads[member.name] = source.read()
    try:
        manifest = json.loads(payloads["manifest.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("workspace cache manifest is not valid UTF-8 JSON") from exc
    return validate_workspace_cache_manifest(manifest), payloads


def validate_workspace_cache_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("workspace cache manifest must be an object")
    required = {
        "schema_version", "kind", "cache_id", "created_at", "expires_at", "ttl_days", "repository",
        "branch", "head_commit", "head_tree", "git_bundle", "workspace_state", "state_fingerprint", "privacy", "drive",
    }
    if set(manifest) != required:
        raise ValueError(f"workspace cache manifest fields mismatch: {sorted(set(manifest) ^ required)}")
    if manifest["schema_version"] != CACHE_SCHEMA_VERSION or manifest["kind"] != CACHE_KIND:
        raise ValueError("unsupported workspace cache schema/kind")
    if not re.fullmatch(r"[0-9a-f]{32}", str(manifest["cache_id"])):
        raise ValueError("invalid workspace cache id")
    if int(manifest["ttl_days"]) != CACHE_TTL_DAYS:
        raise ValueError("workspace cache TTL must be exactly 7 days")
    created = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00"))
    expires = datetime.fromisoformat(str(manifest["expires_at"]).replace("Z", "+00:00"))
    if expires - created != timedelta(days=CACHE_TTL_DAYS):
        raise ValueError("workspace cache expires_at must be created_at + 7 days")
    for key in ("head_commit", "head_tree"):
        if not _SHA40_RE.fullmatch(str(manifest[key])):
            raise ValueError(f"invalid {key}")
    if manifest["branch"] is not None and (not isinstance(manifest["branch"], str) or not manifest["branch"].strip()):
        raise ValueError("workspace cache branch must be null or non-empty string")
    if not _SHA64_RE.fullmatch(str(manifest["state_fingerprint"])):
        raise ValueError("invalid workspace cache state_fingerprint")
    for component in (manifest["git_bundle"], manifest["workspace_state"]["staged"], manifest["workspace_state"]["unstaged"], manifest["workspace_state"]["untracked"]):
        if not isinstance(component, dict) or not _SHA64_RE.fullmatch(str(component.get("sha256") or "")) or int(component.get("size", -1)) < 0:
            raise ValueError("invalid workspace cache component metadata")
    privacy = manifest["privacy"]
    if privacy != {
        "ignored_files_included": False,
        "git_config_included": False,
        "git_hooks_included": False,
        "credentials_included": False,
    }:
        raise ValueError("workspace cache privacy contract mismatch")
    drive = manifest["drive"]
    if drive.get("folder_path") != CACHE_DRIVE_FOLDER or drive.get("visibility") != "private" or not drive.get("one_shot"):
        raise ValueError("workspace cache Drive contract mismatch")
    return manifest


def validate_workspace_cache(capsule: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    capsule = capsule.resolve()
    if expected_sha256 is not None:
        expected_sha256 = expected_sha256.strip().lower()
        if not _SHA64_RE.fullmatch(expected_sha256):
            raise ValueError("expected workspace cache SHA-256 must be full 64-hex")
        actual_outer = _sha256_file(capsule)
        if actual_outer != expected_sha256:
            raise ValueError("workspace cache outer SHA-256 mismatch")
    else:
        actual_outer = _sha256_file(capsule)
    manifest, payloads = _safe_read_capsule(capsule)
    checks = {
        "repo.bundle": manifest["git_bundle"],
        "staged.patch": manifest["workspace_state"]["staged"],
        "unstaged.patch": manifest["workspace_state"]["unstaged"],
        "untracked.tar": manifest["workspace_state"]["untracked"],
    }
    for name, metadata in checks.items():
        payload = payloads[name]
        if len(payload) != int(metadata["size"]) or _sha256_bytes(payload) != metadata["sha256"]:
            raise ValueError(f"workspace cache component integrity mismatch: {name}")
    with tempfile.TemporaryDirectory(prefix="codex-loop-bundle-verify-") as tmp_name:
        tmp = Path(tmp_name)
        (tmp / "repo.bundle").write_bytes(payloads["repo.bundle"])
        subprocess.run(["git", "init", "-q", str(tmp / "repo")], check=True)
        verify = subprocess.run(
            ["git", "-C", str(tmp / "repo"), "bundle", "verify", str(tmp / "repo.bundle")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if verify.returncode != 0:
            raise ValueError("workspace cache Git bundle verification failed")
    return {
        "status": "WORKSPACE_CACHE_VALID",
        "capsule_sha256": actual_outer,
        "capsule_size": capsule.stat().st_size,
        "cache_id": manifest["cache_id"],
        "created_at": manifest["created_at"],
        "expires_at": manifest["expires_at"],
        "head_commit": manifest["head_commit"],
        "head_tree": manifest["head_tree"],
        "branch": manifest["branch"],
        "state_fingerprint": manifest["state_fingerprint"],
        "manifest": manifest,
    }


def _restore_untracked(root: Path, tar_payload: bytes, entries: list[dict[str, Any]]) -> None:
    expected = {str(e["path"]): e for e in entries}
    with tarfile.open(fileobj=io.BytesIO(tar_payload), mode="r:") as tf:
        members = tf.getmembers()
        if {m.name for m in members} != set(expected):
            raise ValueError("untracked archive entries do not match manifest")
        for member in members:
            entry = expected[member.name]
            rel = _safe_rel(member.name)
            dest = root.joinpath(*rel.parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if entry["type"] == "file":
                if not member.isfile():
                    raise ValueError(f"untracked type mismatch: {member.name}")
                src = tf.extractfile(member)
                if src is None:
                    raise ValueError(f"cannot read untracked file: {member.name}")
                data = src.read()
                if _sha256_bytes(data) != entry["sha256"] or len(data) != int(entry["size"]):
                    raise ValueError(f"untracked file integrity mismatch: {member.name}")
                dest.write_bytes(data)
                dest.chmod(int(entry["mode"]))
            elif entry["type"] == "symlink":
                if not member.issym() or member.linkname != entry["target"]:
                    raise ValueError(f"untracked symlink mismatch: {member.name}")
                target = Path(str(entry["target"]))
                if target.is_absolute():
                    raise ValueError(f"absolute untracked symlink rejected: {member.name}")
                resolved = (dest.parent / target).resolve(strict=False)
                try:
                    resolved.relative_to(root.resolve())
                except ValueError as exc:
                    raise ValueError(f"untracked symlink escapes restored workspace: {member.name}") from exc
                dest.symlink_to(str(entry["target"]))
            else:
                raise ValueError(f"unsupported untracked type: {entry['type']}")


def _observed_state_components(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="codex-loop-cache-state-") as tmp_name:
        return _state_components(root, Path(tmp_name))


def write_consumption_receipt(
    output: Path,
    *,
    cache_id: str,
    capsule_sha256: str,
    head_commit: str,
    head_tree: str,
    state_fingerprint: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", cache_id):
        raise ValueError("invalid cache id for consumption receipt")
    for label, value, pattern in (
        ("capsule_sha256", capsule_sha256, _SHA64_RE),
        ("head_commit", head_commit, _SHA40_RE),
        ("head_tree", head_tree, _SHA40_RE),
        ("state_fingerprint", state_fingerprint, _SHA64_RE),
    ):
        if not pattern.fullmatch(value):
            raise ValueError(f"invalid {label} for consumption receipt")
    receipt = {
        "schema_version": 1,
        "kind": CONSUMPTION_KIND,
        "cache_id": cache_id,
        "consumed_at": _iso(_utc_now(now)),
        "capsule_sha256": capsule_sha256,
        "restored_head_commit": head_commit,
        "restored_head_tree": head_tree,
        "restored_state_fingerprint": state_fingerprint,
        "cleanup_pending": True,
        "rule": "successful restore is authoritative even if later Drive deletion fails; this receipt excludes the capsule from future automatic restore selection",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def restore_workspace_cache(
    capsule: Path,
    *,
    destination: Path,
    expected_sha256: str | None = None,
    consumption_receipt_output: Path | None = None,
) -> dict[str, Any]:
    validated = validate_workspace_cache(capsule, expected_sha256=expected_sha256)
    manifest = validated["manifest"]
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("workspace cache restore destination must be absent or empty")
    destination.mkdir(parents=True, exist_ok=True)
    manifest2, payloads = _safe_read_capsule(capsule.resolve())
    if manifest2["cache_id"] != manifest["cache_id"]:
        raise ValueError("workspace cache manifest changed during restore")
    bundle_path = destination.parent / f".{destination.name}-{manifest['cache_id']}.bundle"
    bundle_path.write_bytes(payloads["repo.bundle"])
    try:
        subprocess.run(["git", "init", "-q", str(destination)], check=True)
        branch = manifest["branch"]
        if branch:
            ref = f"refs/heads/{branch}"
            staging_ref = "refs/codex-loop/restore"
            fetch = subprocess.run(
                ["git", "-C", str(destination), "fetch", str(bundle_path), f"{ref}:{staging_ref}"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if fetch.returncode != 0:
                raise RuntimeError(
                    "failed to restore branch from workspace cache Git bundle: "
                    + fetch.stderr.decode("utf-8", errors="replace").strip()
                )
            _git(destination, "update-ref", ref, manifest["head_commit"])
            _git(destination, "symbolic-ref", "HEAD", ref)
            _git(destination, "reset", "--hard", manifest["head_commit"])
            _git(destination, "update-ref", "-d", staging_ref, check=False)
        else:
            fetch = subprocess.run(
                ["git", "-C", str(destination), "fetch", str(bundle_path), manifest["head_commit"]],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            if fetch.returncode != 0:
                raise RuntimeError("failed to restore detached HEAD from workspace cache Git bundle")
            _git(destination, "checkout", "--detach", manifest["head_commit"])
        head, tree, observed_branch = _repo_identity(destination)
        if head != manifest["head_commit"] or tree != manifest["head_tree"]:
            raise RuntimeError("restored workspace Git commit/tree identity mismatch")
        staged = payloads["staged.patch"]
        if staged:
            _git(destination, "apply", "--index", "--binary", "-", input_bytes=staged)
        unstaged = payloads["unstaged.patch"]
        if unstaged:
            _git(destination, "apply", "--binary", "-", input_bytes=unstaged)
        _restore_untracked(destination, payloads["untracked.tar"], manifest["workspace_state"]["untracked"]["entries"])
        observed_components = _observed_state_components(destination)
        observed_fingerprint = _state_fingerprint(head, tree, observed_components)
        if observed_fingerprint != manifest["state_fingerprint"]:
            raise RuntimeError("restored workspace staged/unstaged/untracked state mismatch")
        receipt_path = None
        if consumption_receipt_output is not None:
            receipt_path = consumption_receipt_output.resolve()
            write_consumption_receipt(
                receipt_path,
                cache_id=manifest["cache_id"],
                capsule_sha256=validated["capsule_sha256"],
                head_commit=head,
                head_tree=tree,
                state_fingerprint=observed_fingerprint,
            )
        return {
            "status": "WORKSPACE_RESTORED",
            "cache_id": manifest["cache_id"],
            "destination": str(destination),
            "head_commit": head,
            "head_tree": tree,
            "branch": observed_branch,
            "state_fingerprint": observed_fingerprint,
            "consumption_receipt_path": None if receipt_path is None else str(receipt_path),
            "cleanup_status": "CACHE_CLEANUP_PENDING",
            "cleanup_failure_invalidates_restore": False,
            "next": "bind this restored workspace as the sole mutable authority; keep the consumption receipt as restore-exclusion evidence and defer Drive deletion to the registered >3-day cache cleanup flow with LLM review and explicit user confirmation",
        }
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        bundle_path.unlink(missing_ok=True)


def workspace_cache_cleanup_plan(
    objects: list[dict[str, Any]], *, now: datetime | None = None, preserve_cache_ids: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(objects, list):
        raise ValueError("workspace cache cleanup objects must be a list")
    current = _utc_now(now)
    preserved = {str(x).strip().lower() for x in (preserve_cache_ids or set())}
    if any(not re.fullmatch(r"[0-9a-f]{32}", x) for x in preserved):
        raise ValueError("preserve_cache_ids must contain full 32-hex cache IDs")
    capsules: dict[str, dict[str, Any]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    ignored: list[dict[str, Any]] = []
    for raw in objects:
        if not isinstance(raw, dict):
            raise ValueError("workspace cache cleanup object must be an object")
        allowed = {"id", "name", "created_at", "bounded_parent_proven", "ownership_proven"}
        extra = set(raw) - allowed
        if extra:
            raise ValueError(f"workspace cache cleanup object has unsupported fields: {sorted(extra)}")
        object_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        created_at = str(raw.get("created_at") or "").strip()
        if not object_id or not name or not created_at:
            raise ValueError("workspace cache cleanup object requires id, name, created_at")
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("workspace cache cleanup created_at must be ISO-8601") from exc
        item = {
            "id": object_id,
            "name": name,
            "created_at": _iso(created.astimezone(timezone.utc)),
            "bounded_parent_proven": bool(raw.get("bounded_parent_proven")),
            "ownership_proven": bool(raw.get("ownership_proven")),
        }
        match = _CACHE_NAME_RE.fullmatch(name)
        if match:
            item["cache_id"] = match.group("cache_id")
            item["filename_sha256"] = match.group("sha")
            capsules[item["cache_id"]] = item
            continue
        match = _CONSUMED_NAME_RE.fullmatch(name)
        if match:
            item["cache_id"] = match.group("cache_id")
            receipts[item["cache_id"]] = item
            continue
        ignored.append(item)

    delete_candidates: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    cleanup_pending: list[dict[str, Any]] = []
    for cache_id, capsule in sorted(capsules.items()):
        created = datetime.fromisoformat(capsule["created_at"].replace("Z", "+00:00"))
        consumed = cache_id in receipts
        expired = current >= created + timedelta(days=CACHE_TTL_DAYS)
        eligible = expired
        scope_proven = capsule["bounded_parent_proven"] and capsule["ownership_proven"]
        if cache_id in preserved:
            retained.append({**capsule, "reason": "explicit_restore_in_progress"})
        elif eligible and scope_proven:
            delete_candidates.append({
                **capsule,
                "reason": "expired_3d_consumed" if consumed else "expired_3d",
                "candidate_semantics": "llm_review_only_not_delete_authorization",
                "retry_policy": "fresh exact-id/title/parent readback then at most one retry in this cache operation",
            })
        elif eligible:
            cleanup_pending.append({**capsule, "reason": "ownership_or_bounded_scope_unproven"})
        else:
            retained.append({**capsule, "reason": "younger_than_3d"})

    receipt_deletes: list[dict[str, Any]] = []
    for cache_id, receipt in sorted(receipts.items()):
        capsule = capsules.get(cache_id)
        scope_proven = receipt["bounded_parent_proven"] and receipt["ownership_proven"]
        receipt_created = datetime.fromisoformat(receipt["created_at"].replace("Z", "+00:00"))
        receipt_expired = current >= receipt_created + timedelta(days=CACHE_TTL_DAYS)
        capsule_selected = any(x["cache_id"] == cache_id for x in delete_candidates)
        if scope_proven and receipt_expired and (capsule is None or capsule_selected):
            receipt_deletes.append({
                **receipt,
                "reason": "expired_3d_consumption_receipt_housekeeping",
                "candidate_semantics": "llm_review_only_not_delete_authorization",
                "delete_after_capsule": capsule is not None,
            })
        elif receipt_expired and not scope_proven:
            cleanup_pending.append({**receipt, "reason": "receipt_ownership_or_bounded_scope_unproven"})

    return {
        "status": "WORKSPACE_CACHE_CLEANUP_PLAN",
        "drive_folder_path": CACHE_DRIVE_FOLDER,
        "ttl_days": CACHE_TTL_DAYS,
        "delete_candidates": delete_candidates,
        "receipt_delete_candidates": receipt_deletes,
        "retained": retained,
        "cleanup_pending": cleanup_pending,
        "ignored_non_cache_objects": ignored,
        "auto_restore_excluded_cache_ids": sorted(receipts),
        "preserved_cache_ids": sorted(preserved),
        "requires_llm_cache_confirmation": True,
        "requires_human_confirmation": True,
        "requires_drive_delete_switch": True,
        "candidate_semantics": "review_only_not_delete_authorization",
        "rule": "workspace-cache cleanup only nominates exact owned >=3-day objects for the generic Drive cache review flow; consumed state excludes auto-restore but never authorizes immediate deletion; one failed cleanup never invalidates a successful restore",
    }

DRIVE_CACHE_CLEANUP_DAYS = 3
DRIVE_CACHE_PLAN_KIND = "codex_loop_drive_cache_cleanup_plan"


def _normalize_drive_cache_folder_path(raw: str) -> str:
    value = str(raw).strip().replace("\\", "/")
    parts = [part for part in value.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("Drive cache folder path must be a canonical non-empty relative path")
    value = "/".join(parts)
    if len(value) > 1024 or any(ord(ch) < 32 for ch in value):
        raise ValueError("Drive cache folder path must be bounded printable text")
    return value


def drive_delete_policy() -> dict[str, Any]:
    profile = effective_host_profile()
    enabled = bool(profile["drive"]["delete_enabled"])
    return {
        "status": "DRIVE_DELETE_ENABLED" if enabled else "DRIVE_DELETE_DISABLED",
        "delete_enabled": enabled,
        "may_call_drive_delete": enabled,
        "config_path": profile["config_path"],
        "config_field": "drive.delete_enabled",
        "local_only": True,
        "uploaded_to_drive": False,
        "rule": "Drive delete actions may be called only when this host-local switch is enabled; the switch never substitutes for operation-specific review or human confirmation",
    }


def registered_drive_cache_folders() -> dict[str, Any]:
    profile = effective_host_profile()
    return {
        "status": "DRIVE_CACHE_REGISTRY",
        "folder_paths": list(profile["drive"]["cache_folder_paths"]),
        "config_path": profile["config_path"],
        "config_field": "drive.cache_folder_paths",
        "local_only": True,
        "uploaded_to_drive": False,
    }


def register_drive_cache_folder(folder_path: str) -> dict[str, Any]:
    normalized = _normalize_drive_cache_folder_path(folder_path)
    current = registered_drive_cache_folders()["folder_paths"]
    if normalized not in current:
        host_config_set("drive.cache_folder_paths", [*current, normalized])
    result = registered_drive_cache_folders()
    result.update({"status": "DRIVE_CACHE_FOLDER_REGISTERED", "registered_folder_path": normalized})
    return result


def unregister_drive_cache_folder(folder_path: str) -> dict[str, Any]:
    normalized = _normalize_drive_cache_folder_path(folder_path)
    current = registered_drive_cache_folders()["folder_paths"]
    updated = [item for item in current if item != normalized]
    if updated != current:
        host_config_set("drive.cache_folder_paths", updated)
    result = registered_drive_cache_folders()
    result.update({"status": "DRIVE_CACHE_FOLDER_UNREGISTERED", "unregistered_folder_path": normalized})
    return result


def _drive_cache_plan_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def drive_cache_cleanup_plan(objects: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(objects, list):
        raise ValueError("Drive cache cleanup objects must be a list")
    current = _utc_now(now)
    registered = set(registered_drive_cache_folders()["folder_paths"])
    review_candidates = []
    retained = []
    cleanup_pending = []
    ignored_unregistered = []
    seen_ids = set()
    for raw in objects:
        allowed = {"id", "name", "created_at", "folder_path", "url", "mime_type", "size", "bounded_parent_proven", "ownership_proven"}
        extra = set(raw) - allowed
        if extra:
            raise ValueError(f"Drive cache cleanup object has unsupported fields: {sorted(extra)}")
        object_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        created_at = str(raw.get("created_at") or "").strip()
        folder_path = _normalize_drive_cache_folder_path(str(raw.get("folder_path") or ""))
        if not object_id or not name or not created_at:
            raise ValueError("Drive cache cleanup object requires id, name, created_at, folder_path")
        if object_id in seen_ids:
            raise ValueError(f"duplicate Drive cache cleanup object id: {object_id}")
        seen_ids.add(object_id)
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        item = {"id": object_id, "name": name, "created_at": _iso(created), "folder_path": folder_path, "bounded_parent_proven": bool(raw.get("bounded_parent_proven")), "ownership_proven": bool(raw.get("ownership_proven"))}
        for key in ("url", "mime_type", "size"):
            if raw.get(key) is not None:
                item[key] = raw[key]
        if folder_path not in registered:
            ignored_unregistered.append({**item, "reason": "folder_not_registered_as_codex_loop_cache"})
        elif current < created + timedelta(days=DRIVE_CACHE_CLEANUP_DAYS):
            retained.append({**item, "reason": "younger_than_3d"})
        elif not (item["bounded_parent_proven"] and item["ownership_proven"]):
            cleanup_pending.append({**item, "reason": "ownership_or_registered_parent_scope_unproven"})
        else:
            review_candidates.append({**item, "reason": "older_than_3d_in_registered_cache_folder", "candidate_semantics": "llm_review_only_not_delete_authorization"})
    payload = {"kind": DRIVE_CACHE_PLAN_KIND, "generated_at": _iso(current), "retention_days": DRIVE_CACHE_CLEANUP_DAYS, "registered_folder_paths": sorted(registered), "review_candidates": review_candidates, "retained": retained, "cleanup_pending": cleanup_pending, "ignored_unregistered": ignored_unregistered}
    return {"status": "DRIVE_CACHE_LLM_REVIEW_REQUIRED" if review_candidates else "DRIVE_CACHE_NOTHING_TO_REVIEW", **payload, "plan_digest": _drive_cache_plan_digest(payload), "requires_llm_cache_confirmation": bool(review_candidates), "requires_human_confirmation_after_llm_review": bool(review_candidates), "delete_authorized": False}


def authorize_drive_cache_cleanup(plan: dict[str, Any], *, llm_confirmed_ids: list[str], llm_review_completed: bool, human_confirmation_observed: bool, confirmation_evidence: str | None) -> dict[str, Any]:
    if plan.get("kind") != DRIVE_CACHE_PLAN_KIND:
        raise ValueError("invalid Drive cache cleanup plan")
    payload = {key: plan.get(key) for key in ("kind", "generated_at", "retention_days", "registered_folder_paths", "review_candidates", "retained", "cleanup_pending", "ignored_unregistered")}
    expected_digest = _drive_cache_plan_digest(payload)
    if plan.get("plan_digest") != expected_digest:
        raise ValueError("Drive cache cleanup plan digest mismatch")
    if not llm_review_completed:
        raise ValueError("LLM cache review must complete exactly once before human confirmation")
    candidates = {str(item["id"]): item for item in plan.get("review_candidates") or []}
    confirmed = []
    for raw_id in llm_confirmed_ids:
        object_id = str(raw_id).strip()
        if object_id not in candidates:
            raise ValueError(f"LLM-confirmed object is not in the reviewed candidate set: {object_id}")
        if candidates[object_id] not in confirmed:
            confirmed.append(candidates[object_id])
    if not confirmed:
        return {"status": "DRIVE_CACHE_NO_LLM_CONFIRMED_OBJECTS", "plan_digest": expected_digest, "delete_ready": [], "delete_authorized": False}
    evidence = str(confirmation_evidence or "").strip()
    if not human_confirmation_observed or not evidence:
        raise ValueError("explicit current-turn human confirmation is required after LLM cache review")
    policy = drive_delete_policy()
    if not policy["delete_enabled"]:
        return {"status": "DRIVE_DELETE_DISABLED", "plan_digest": expected_digest, "llm_confirmed": confirmed, "delete_ready": [], "delete_authorized": False, "delete_policy": policy}
    return {"status": "DRIVE_CACHE_DELETE_READY", "plan_digest": expected_digest, "llm_confirmed": confirmed, "delete_ready": confirmed, "delete_authorized": True, "human_confirmation_sha256": hashlib.sha256(evidence.encode("utf-8")).hexdigest(), "delete_policy": policy}
