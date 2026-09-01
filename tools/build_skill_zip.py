#!/usr/bin/env python3
"""Build the installable Codex Loop runtime Skill archive.

The repository contains development-only files that must not be carried into the
ChatGPT Skill package. This builder emits one deterministic ``skill.zip``-style
archive rooted at ``codex-loop/`` and containing only runtime resources.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT_FILES = ("ATTRIBUTION.md", "LICENSE", "NOTICE", "SKILL.md")
RUNTIME_DIRS = ("agents", "assets", "references", "scripts")
IGNORED_PARTS = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _skill_name(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    match = re.search(r"(?m)^name:\s*[\"']?([a-z0-9-]+)[\"']?\s*$", text)
    if not match:
        raise ValueError("SKILL.md must contain a lowercase hyphen-case name")
    return match.group(1)


def _runtime_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for name in ROOT_FILES:
        path = source / name
        if not path.is_file():
            raise ValueError(f"required runtime file missing: {name}")
        files.append(path)

    for dirname in RUNTIME_DIRS:
        directory = source / dirname
        if not directory.is_dir():
            raise ValueError(f"required runtime directory missing: {dirname}/")
        for path in directory.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(source)
            if any(part in IGNORED_PARTS for part in rel.parts):
                continue
            if path.suffix in IGNORED_SUFFIXES:
                continue
            if path.is_symlink():
                raise ValueError(f"symlinks are not allowed in Skill packages: {rel}")
            files.append(path)

    return sorted(set(files), key=lambda p: p.relative_to(source).as_posix())


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


def build_skill_zip(source: Path, output: Path) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    name = _skill_name(source / "SKILL.md")
    if name != "codex-loop":
        raise ValueError(f"unexpected Skill name: {name}")
    _validate_chatgpt_metadata(source)
    files = _runtime_files(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                rel = PurePosixPath(name) / PurePosixPath(path.relative_to(source).as_posix())
                info = zipfile.ZipInfo(rel.as_posix(), FIXED_ZIP_TIME)
                info.create_system = 3
                # Match the user-verified ChatGPT package: regular files are archived as 0644.
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(tmp, output)
    finally:
        if tmp.exists():
            tmp.unlink()

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"output": str(output), "sha256": digest, "file_count": len(files), "skill_name": name}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=".", help="repository root (default: current directory)")
    parser.add_argument("--output", required=True, help="output ZIP path")
    args = parser.parse_args(argv)
    try:
        result = build_skill_zip(Path(args.source), Path(args.output))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"built {result['output']}")
    print(f"skill={result['skill_name']} files={result['file_count']} sha256={result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
