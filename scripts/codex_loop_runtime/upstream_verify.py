from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify() -> list[dict[str, Any]]:
    skill_root = Path(__file__).resolve().parents[2]
    upstream = skill_root / "scripts" / "upstream"
    manifest = json.loads((upstream / "MANIFEST.json").read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for entry in manifest["files"]:
        if entry.get("local_path"):
            path = (skill_root / entry["local_path"]).resolve()
            try:
                path.relative_to(skill_root.resolve())
            except ValueError as exc:
                raise RuntimeError(f"manifest local_path escapes skill root: {entry['local_path']}") from exc
        else:
            path = upstream / entry["path"]
        data = path.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        ok = sha256 == entry["sha256"]
        blob = None
        if "git_blob_sha1" in entry:
            blob = _git_blob_sha1(data)
            ok = ok and blob == entry["git_blob_sha1"]
        result = {
            "path": entry["path"],
            "classification": entry["classification"],
            "sha256": sha256,
            "git_blob_sha1": blob,
            "ok": ok,
        }
        results.append(result)
        if not ok:
            raise RuntimeError(f"upstream integrity check failed for {entry['path']}")
    return results
