#!/usr/bin/env python3
"""Prepare the ChatGPT-downloadable Codex Loop package without changing its bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(source: Path, output: Path) -> dict[str, object]:
    if source.name != "skill.zip":
        raise ValueError("source must be the official Skill Creator package named skill.zip")
    if output.name != "codex-loop.zip":
        raise ValueError("output must be named codex-loop.zip")
    if not source.is_file():
        raise FileNotFoundError(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)

    source_sha = sha256_file(source)
    output_sha = sha256_file(output)
    if source_sha != output_sha:
        raise RuntimeError("byte identity check failed after preparing codex-loop.zip")

    return {
        "status": "PASS",
        "source": str(source),
        "source_filename": source.name,
        "download_artifact": str(output),
        "download_filename": output.name,
        "source_sha256": source_sha,
        "download_sha256": output_sha,
        "byte_identical": True,
        "recompressed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy official skill.zip byte-for-byte to codex-loop.zip for fresh current-conversation artifact delivery."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
