from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
BUNDLE_PROFILE = "chatgpt-runtime"
DEPLOYMENT_MANIFEST_REL = Path("references/deployment-manifest.json")
ROOT_FILES = ("ATTRIBUTION.md", "LICENSE", "NOTICE", "SKILL.md")
RUNTIME_DIRS = ("agents", "assets", "references", "scripts")
IGNORED_PARTS = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def runtime_files(source: Path) -> list[Path]:
    source = source.resolve()
    generated = (source / DEPLOYMENT_MANIFEST_REL).resolve()
    if generated.exists() or generated.is_symlink():
        raise ValueError("references/deployment-manifest.json is build-generated and must not exist in source")
    files: list[Path] = []
    for name in ROOT_FILES:
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required runtime file missing or unsafe: {name}")
        files.append(path)
    for dirname in RUNTIME_DIRS:
        directory = source / dirname
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"required runtime directory missing or unsafe: {dirname}/")
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(source)
            if rel == DEPLOYMENT_MANIFEST_REL:
                continue
            if any(part in IGNORED_PARTS for part in rel.parts):
                continue
            if path.suffix in IGNORED_SUFFIXES:
                continue
            if path.is_symlink():
                raise ValueError(f"symlinks are not allowed in Skill packages: {rel}")
            files.append(path)
    return sorted(set(files), key=lambda p: p.relative_to(source).as_posix())


def build_runtime_file_manifest(source: Path) -> list[dict[str, Any]]:
    source = source.resolve()
    return [
        {
            "path": path.relative_to(source).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in runtime_files(source)
    ]


def runtime_manifest_sha256(source: Path) -> str:
    return _sha256_bytes(_canonical_json_bytes(build_runtime_file_manifest(source)))


def _git_object_sha(kind: bytes, payload: bytes) -> bytes:
    header = kind + b" " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).digest()


def _git_mode(path: Path) -> bytes:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        return b"120000"
    if stat.S_ISREG(mode):
        return b"100755" if mode & stat.S_IXUSR else b"100644"
    if stat.S_ISDIR(mode):
        return b"40000"
    raise ValueError(f"unsupported Git tree entry type: {path}")


def _tree_sha(path: Path, *, root: Path) -> bytes:
    entries: list[tuple[bytes, bool, Path]] = []
    for child in path.iterdir():
        if path == root and child.name == ".git":
            continue
        name = os.fsencode(child.name)
        is_dir = child.is_dir() and not child.is_symlink()
        entries.append((name, is_dir, child))
    entries.sort(key=lambda item: item[0] + (b"/" if item[1] else b""))
    payload = bytearray()
    for name, is_dir, child in entries:
        if is_dir:
            object_sha = _tree_sha(child, root=root)
        elif child.is_symlink():
            object_sha = _git_object_sha(b"blob", os.fsencode(os.readlink(child)))
        elif child.is_file():
            object_sha = _git_object_sha(b"blob", child.read_bytes())
        else:
            raise ValueError(f"unsupported Git tree entry type: {child}")
        payload.extend(_git_mode(child))
        payload.extend(b" ")
        payload.extend(name)
        payload.extend(b"\0")
        payload.extend(object_sha)
    return _git_object_sha(b"tree", bytes(payload))


def git_tree_sha(source: Path) -> str:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError("source must be a directory")
    return _tree_sha(source, root=source).hex()


def build_deployment_manifest(
    source: Path,
    *,
    repository: str,
    commit: str,
    tree: str,
    skill_name: str = "codex-loop",
) -> dict[str, Any]:
    repository = str(repository).strip()
    commit = str(commit).strip().lower()
    tree = str(tree).strip().lower()
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must be exact OWNER/REPO")
    if not _FULL_SHA_RE.fullmatch(commit):
        raise ValueError("commit must be a full 40-hex Git commit SHA")
    if not _FULL_SHA_RE.fullmatch(tree):
        raise ValueError("tree must be a full 40-hex Git tree SHA")
    if skill_name != "codex-loop":
        raise ValueError("unexpected Skill name")
    file_manifest = build_runtime_file_manifest(source)
    actual_tree = git_tree_sha(source)
    if actual_tree != tree:
        raise ValueError(f"source tree mismatch: expected {tree}, observed {actual_tree}")
    return {
        "schema_version": SCHEMA_VERSION,
        "skill_name": skill_name,
        "source": {
            "repository": repository,
            "commit": commit,
            "tree": tree,
        },
        "bundle": {
            "profile": BUNDLE_PROFILE,
            "file_count": len(file_manifest),
            "manifest_sha256": _sha256_bytes(_canonical_json_bytes(file_manifest)),
        },
    }


def deployment_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    validate_deployment_manifest(manifest)
    return (json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")


def validate_deployment_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "skill_name", "source", "bundle"}:
        raise ValueError("invalid deployment manifest top-level schema")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("skill_name") != "codex-loop":
        raise ValueError("unsupported deployment manifest identity")
    source = manifest.get("source")
    bundle = manifest.get("bundle")
    if not isinstance(source, dict) or set(source) != {"repository", "commit", "tree"}:
        raise ValueError("invalid deployment manifest source schema")
    if not isinstance(bundle, dict) or set(bundle) != {"profile", "file_count", "manifest_sha256"}:
        raise ValueError("invalid deployment manifest bundle schema")
    if not _REPOSITORY_RE.fullmatch(str(source.get("repository") or "")):
        raise ValueError("invalid deployment repository")
    for key in ("commit", "tree"):
        if not _FULL_SHA_RE.fullmatch(str(source.get(key) or "")):
            raise ValueError(f"invalid deployment source {key}")
    if bundle.get("profile") != BUNDLE_PROFILE:
        raise ValueError("unsupported deployment bundle profile")
    if not isinstance(bundle.get("file_count"), int) or int(bundle["file_count"]) < 1:
        raise ValueError("invalid deployment bundle file_count")
    if not re.fullmatch(r"^[0-9a-f]{64}$", str(bundle.get("manifest_sha256") or "")):
        raise ValueError("invalid deployment bundle manifest_sha256")
    return manifest


def verify_installed_skill(skill_root: Path) -> dict[str, Any]:
    skill_root = skill_root.resolve()
    path = skill_root / DEPLOYMENT_MANIFEST_REL
    if path.is_symlink() or not path.is_file():
        raise ValueError("installed Skill has no safe deployment-manifest.json")
    payload = path.read_bytes()
    if len(payload) > 64 * 1024:
        raise ValueError("deployment manifest exceeds 64 KiB")
    try:
        manifest = validate_deployment_manifest(json.loads(payload.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("deployment manifest must be valid UTF-8 JSON") from exc
    files = build_runtime_file_manifest_for_installed(skill_root)
    observed_sha = _sha256_bytes(_canonical_json_bytes(files))
    if len(files) != int(manifest["bundle"]["file_count"]):
        raise ValueError("installed Skill runtime file count does not match deployment provenance")
    if observed_sha != manifest["bundle"]["manifest_sha256"]:
        raise ValueError("installed Skill runtime manifest hash does not match deployment provenance")
    return {
        "valid": True,
        "source": manifest["source"],
        "bundle": manifest["bundle"],
        "deployment_manifest": str(path),
    }


def build_runtime_file_manifest_for_installed(skill_root: Path) -> list[dict[str, Any]]:
    skill_root = skill_root.resolve()
    files: list[Path] = []
    for name in ROOT_FILES:
        path = skill_root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required installed runtime file missing or unsafe: {name}")
        files.append(path)
    for dirname in RUNTIME_DIRS:
        directory = skill_root / dirname
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"required installed runtime directory missing or unsafe: {dirname}/")
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(skill_root)
            if rel == DEPLOYMENT_MANIFEST_REL:
                continue
            if any(part in IGNORED_PARTS for part in rel.parts) or path.suffix in IGNORED_SUFFIXES:
                continue
            if path.is_symlink():
                raise ValueError(f"symlinks are not allowed in installed Skill runtime: {rel}")
            files.append(path)
    files = sorted(set(files), key=lambda p: p.relative_to(skill_root).as_posix())
    return [
        {"path": p.relative_to(skill_root).as_posix(), "size": p.stat().st_size, "sha256": _sha256_bytes(p.read_bytes())}
        for p in files
    ]
