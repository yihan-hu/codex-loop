from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
BUNDLE_PROFILE = "chatgpt-runtime"
CONSUMER_PROFILE = "consumer"
MAINTAINER_PROFILE = "maintainer"
DISTRIBUTION_PROFILES = (CONSUMER_PROFILE, MAINTAINER_PROFILE)
DEPLOYMENT_MANIFEST_REL = Path("references/deployment-manifest.json")
ROOT_FILES = ("ATTRIBUTION.md", "LICENSE", "NOTICE", "SKILL.md")
RUNTIME_DIRS = ("agents", "assets", "references", "scripts")
IGNORED_PARTS = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _git_repo_root(source: Path) -> Path | None:
    proc = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "--show-toplevel"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        root = Path(proc.stdout.decode("utf-8", errors="strict").strip()).resolve()
    except UnicodeDecodeError:
        return None
    return root if root == source else None


def _git_text(source: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(source), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(
            "Git source probe failed: "
            + proc.stderr.decode("utf-8", errors="replace").strip()
        )
    return proc.stdout.decode("utf-8", errors="strict").strip()


def _assert_git_tracked_source_clean(source: Path) -> None:
    proc = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain=v1", "--untracked-files=no"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(
            "Git source cleanliness probe failed: "
            + proc.stderr.decode("utf-8", errors="replace").strip()
        )
    if proc.stdout:
        raise ValueError(
            "tracked source is dirty; commit or restore tracked changes before maintainer packaging"
        )


def _tracked_runtime_files(source: Path) -> list[Path] | None:
    if _git_repo_root(source) is None:
        return None
    pathspecs = [*ROOT_FILES, *RUNTIME_DIRS]
    proc = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z", "--", *pathspecs],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(
            "Git tracked-file projection failed: "
            + proc.stderr.decode("utf-8", errors="replace").strip()
        )
    rels = [Path(os.fsdecode(raw)) for raw in proc.stdout.split(b"\0") if raw]
    tracked = set(rels)
    for name in ROOT_FILES:
        if Path(name) not in tracked:
            raise ValueError(f"required runtime file is not tracked by Git: {name}")
    files: list[Path] = []
    for rel in rels:
        if rel == DEPLOYMENT_MANIFEST_REL:
            continue
        if any(part in IGNORED_PARTS for part in rel.parts) or rel.suffix in IGNORED_SUFFIXES:
            continue
        path = source / rel
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"tracked runtime file missing or unsafe: {rel}")
        files.append(path)
    return sorted(set(files), key=lambda p: p.relative_to(source).as_posix())


def _filesystem_runtime_files(source: Path) -> list[Path]:
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


def runtime_files(source: Path, *, tracked_only: bool = True) -> list[Path]:
    source = source.resolve()
    generated = (source / DEPLOYMENT_MANIFEST_REL).resolve()
    if generated.exists() or generated.is_symlink():
        raise ValueError("references/deployment-manifest.json is build-generated and must not exist in source")
    if tracked_only:
        tracked = _tracked_runtime_files(source)
        if tracked is not None:
            return tracked
    return _filesystem_runtime_files(source)


def build_runtime_file_manifest(source: Path, *, tracked_only: bool = True) -> list[dict[str, Any]]:
    source = source.resolve()
    return [
        {
            "path": path.relative_to(source).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256_bytes(path.read_bytes()),
        }
        for path in runtime_files(source, tracked_only=tracked_only)
    ]


def runtime_manifest_sha256(source: Path, *, tracked_only: bool = True) -> str:
    return _sha256_bytes(_canonical_json_bytes(build_runtime_file_manifest(source, tracked_only=tracked_only)))


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
    if _git_repo_root(source) is not None:
        return _git_text(source, "rev-parse", "HEAD^{tree}")
    return _tree_sha(source, root=source).hex()


def _validate_bundle(bundle: Any) -> None:
    if not isinstance(bundle, dict) or set(bundle) != {"profile", "file_count", "manifest_sha256"}:
        raise ValueError("invalid deployment manifest bundle schema")
    if bundle.get("profile") != BUNDLE_PROFILE:
        raise ValueError("unsupported deployment bundle profile")
    if not isinstance(bundle.get("file_count"), int) or int(bundle["file_count"]) < 1:
        raise ValueError("invalid deployment bundle file_count")
    if not _SHA256_RE.fullmatch(str(bundle.get("manifest_sha256") or "")):
        raise ValueError("invalid deployment bundle manifest_sha256")


def _validate_source(source: Any) -> None:
    if not isinstance(source, dict) or set(source) != {"repository", "commit", "tree"}:
        raise ValueError("invalid deployment manifest source schema")
    if not _REPOSITORY_RE.fullmatch(str(source.get("repository") or "")):
        raise ValueError("invalid deployment repository")
    for key in ("commit", "tree"):
        if not _FULL_SHA_RE.fullmatch(str(source.get(key) or "")):
            raise ValueError(f"invalid deployment source {key}")


def build_deployment_manifest(
    source: Path,
    *,
    distribution_profile: str = CONSUMER_PROFILE,
    repository: str | None = None,
    commit: str | None = None,
    tree: str | None = None,
    skill_name: str = "codex-loop",
) -> dict[str, Any]:
    source = source.resolve()
    distribution_profile = str(distribution_profile).strip().lower()
    if distribution_profile not in DISTRIBUTION_PROFILES:
        raise ValueError(f"unsupported distribution profile: {distribution_profile}")
    if skill_name != "codex-loop":
        raise ValueError("unexpected Skill name")

    if distribution_profile == CONSUMER_PROFILE:
        if any(value not in (None, "") for value in (repository, commit, tree)):
            raise ValueError("consumer packages must not carry repository, commit, or tree binding")
        file_manifest = build_runtime_file_manifest(source, tracked_only=False)
        return {
            "schema_version": SCHEMA_VERSION,
            "skill_name": skill_name,
            "distribution": {
                "profile": CONSUMER_PROFILE,
                "repository_binding": "none",
            },
            "bundle": {
                "profile": BUNDLE_PROFILE,
                "file_count": len(file_manifest),
                "manifest_sha256": _sha256_bytes(_canonical_json_bytes(file_manifest)),
            },
        }

    repository = str(repository or "").strip()
    commit = str(commit or "").strip().lower()
    tree = str(tree or "").strip().lower()
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("maintainer repository must be exact OWNER/REPO")
    if not _FULL_SHA_RE.fullmatch(commit):
        raise ValueError("maintainer commit must be a full 40-hex Git commit SHA")
    if not _FULL_SHA_RE.fullmatch(tree):
        raise ValueError("maintainer tree must be a full 40-hex Git tree SHA")
    if _git_repo_root(source) is not None:
        _assert_git_tracked_source_clean(source)
        actual_commit = _git_text(source, "rev-parse", "HEAD")
        if actual_commit != commit:
            raise ValueError(f"source commit mismatch: expected {commit}, observed {actual_commit}")
    file_manifest = build_runtime_file_manifest(source, tracked_only=True)
    actual_tree = git_tree_sha(source)
    if actual_tree != tree:
        raise ValueError(f"source tree mismatch: expected {tree}, observed {actual_tree}")
    return {
        "schema_version": SCHEMA_VERSION,
        "skill_name": skill_name,
        "distribution": {
            "profile": MAINTAINER_PROFILE,
            "repository_binding": "provenance_only",
        },
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
    if not isinstance(manifest, dict):
        raise ValueError("invalid deployment manifest top-level schema")
    if manifest.get("skill_name") != "codex-loop":
        raise ValueError("unsupported deployment manifest identity")

    version = manifest.get("schema_version")
    if version == LEGACY_SCHEMA_VERSION:
        if set(manifest) != {"schema_version", "skill_name", "source", "bundle"}:
            raise ValueError("invalid legacy deployment manifest top-level schema")
        _validate_source(manifest.get("source"))
        _validate_bundle(manifest.get("bundle"))
        return manifest

    if version != SCHEMA_VERSION:
        raise ValueError("unsupported deployment manifest identity")
    distribution = manifest.get("distribution")
    if not isinstance(distribution, dict) or set(distribution) != {"profile", "repository_binding"}:
        raise ValueError("invalid deployment distribution schema")
    profile = distribution.get("profile")
    binding = distribution.get("repository_binding")
    if profile == CONSUMER_PROFILE:
        if set(manifest) != {"schema_version", "skill_name", "distribution", "bundle"}:
            raise ValueError("consumer deployment manifest must not carry source repository identity")
        if binding != "none":
            raise ValueError("consumer deployment repository binding must be none")
    elif profile == MAINTAINER_PROFILE:
        if set(manifest) != {"schema_version", "skill_name", "distribution", "source", "bundle"}:
            raise ValueError("invalid maintainer deployment manifest top-level schema")
        if binding != "provenance_only":
            raise ValueError("maintainer repository binding must be provenance_only")
        _validate_source(manifest.get("source"))
    else:
        raise ValueError("unsupported deployment distribution profile")
    _validate_bundle(manifest.get("bundle"))
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

    if manifest["schema_version"] == LEGACY_SCHEMA_VERSION:
        distribution = {"profile": MAINTAINER_PROFILE, "repository_binding": "legacy_provenance_only"}
    else:
        distribution = manifest["distribution"]
    return {
        "valid": True,
        "distribution": distribution,
        "source": manifest.get("source"),
        "bundle": manifest["bundle"],
        "repository_binding_required": False,
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
