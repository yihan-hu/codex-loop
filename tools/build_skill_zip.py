#!/usr/bin/env python3
"""Build a deterministic, provenance-bound Codex Loop Skill archive."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from codex_loop_runtime.deployment_manifest import (
    DEPLOYMENT_MANIFEST_REL,
    IGNORED_PARTS,
    IGNORED_SUFFIXES,
    ROOT_FILES,
    RUNTIME_DIRS,
    build_deployment_manifest,
    deployment_manifest_bytes,
    runtime_files,
)

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _skill_name(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*[\"']?([a-z0-9-]+)[\"']?\s*$", text)
    if not match:
        raise ValueError("SKILL.md must contain a lowercase hyphen-case name")
    return match.group(1)


def _runtime_files(source: Path) -> list[Path]:
    return runtime_files(source)


def _validate_chatgpt_metadata(source: Path) -> None:
    metadata = (source / "agents" / "openai.yaml").read_text(encoding="utf-8")
    required = (
        'display_name: "Codex Loop"',
        'short_description: "Adaptive lifecycle for multi-step objectives"',
        'icon_small: "./assets/icon.svg"',
        'icon_large: "./assets/icon.svg"',
        'default_prompt: "Use $codex-loop ',
        "allow_implicit_invocation: true",
    )
    for fragment in required:
        if fragment not in metadata:
            raise ValueError(f"agents/openai.yaml missing install-verified metadata: {fragment}")
    if "products:" in metadata:
        raise ValueError("agents/openai.yaml must not include the legacy policy.products override")


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, FIXED_ZIP_TIME)
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def build_skill_zip(
    source: Path,
    output: Path,
    *,
    repository: str,
    commit: str,
    tree: str,
) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    name = _skill_name(source / "SKILL.md")
    if name != "codex-loop":
        raise ValueError(f"unexpected Skill name: {name}")
    _validate_chatgpt_metadata(source)
    files = _runtime_files(source)
    manifest = build_deployment_manifest(
        source,
        repository=repository,
        commit=commit,
        tree=tree,
        skill_name=name,
    )
    manifest_payload = deployment_manifest_bytes(manifest)

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                rel = PurePosixPath(name) / PurePosixPath(path.relative_to(source).as_posix())
                archive.writestr(_zip_info(rel.as_posix()), path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            generated_rel = PurePosixPath(name) / PurePosixPath(DEPLOYMENT_MANIFEST_REL.as_posix())
            archive.writestr(_zip_info(generated_rel.as_posix()), manifest_payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(tmp, output)
    finally:
        if tmp.exists():
            tmp.unlink()

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {
        "output": str(output),
        "sha256": digest,
        "file_count": len(files) + 1,
        "runtime_file_count": len(files),
        "skill_name": name,
        "source": manifest["source"],
        "bundle_manifest_sha256": manifest["bundle"]["manifest_sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".", help="repository root (default: current directory)")
    parser.add_argument("--output", required=True, help="output ZIP path")
    parser.add_argument("--source-repository", required=True, help="exact GitHub OWNER/REPO")
    parser.add_argument("--source-commit", required=True, help="verified full 40-hex source commit")
    parser.add_argument("--source-tree", required=True, help="verified full 40-hex source tree")
    args = parser.parse_args(argv)
    try:
        result = build_skill_zip(
            Path(args.source), Path(args.output),
            repository=args.source_repository,
            commit=args.source_commit,
            tree=args.source_tree,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"built {result['output']}")
    print(
        f"skill={result['skill_name']} files={result['file_count']} sha256={result['sha256']} "
        f"source={result['source']['repository']}@{result['source']['commit']} tree={result['source']['tree']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
