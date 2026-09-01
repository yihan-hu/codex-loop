from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def file_manifest_digest(source: Path, files: Iterable[Path]) -> tuple[str, list[dict[str, object]]]:
    rows=[]
    for path in sorted(files,key=lambda p:p.relative_to(source).as_posix()):
        rel=path.relative_to(source).as_posix(); data=path.read_bytes()
        rows.append({"path":rel,"size":len(data),"sha256":hashlib.sha256(data).hexdigest()})
    encoded=json.dumps(rows,ensure_ascii=True,sort_keys=True,separators=(",",":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest(), rows


def build_deployment_manifest(source: Path, files: Iterable[Path], *, repository: str, commit: str, tree: str, profile: str="chatgpt-runtime") -> dict[str, object]:
    if "/" not in repository or repository.count("/") != 1: raise ValueError("repository must be OWNER/REPO")
    for name,value in (("commit",commit),("tree",tree)):
        if len(value)!=40 or any(c not in "0123456789abcdefABCDEF" for c in value): raise ValueError(f"{name} must be a full 40-hex Git SHA")
    digest, rows=file_manifest_digest(source,files)
    return {"schema_version":1,"skill_name":"codex-loop","source":{"repository":repository,"commit":commit.lower(),"tree":tree.lower()},"bundle":{"profile":profile,"file_count":len(rows),"manifest_sha256":digest},"privacy":{"contains_host_profile":False,"contains_local_paths":False,"contains_drive_ids":False,"contains_task_or_conversation_ids":False}}
