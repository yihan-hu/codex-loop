#!/usr/bin/env python3
"""Validate the fixed Codex Loop installer handoff and provenance-bound package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

EXPECTED_FIELDS = {
    "version",
    "installer_skill",
    "skill_name",
    "repository",
    "source_state",
    "deployment_target",
    "source_commit",
    "source_tree",
    "package_sha256",
}
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def fail(message: str) -> int:
    print(json.dumps({"status": "FAIL", "error": message}, sort_keys=True))
    return 1


def load_handoff(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("handoff must be a JSON object")
    if set(value) != EXPECTED_FIELDS:
        missing = sorted(EXPECTED_FIELDS - set(value))
        extra = sorted(set(value) - EXPECTED_FIELDS)
        raise ValueError(f"handoff fields mismatch: missing={missing} extra={extra}")
    return value


def validate_constants(value: dict) -> None:
    expected = {
        "version": 1,
        "installer_skill": "codex-loop-install",
        "skill_name": "codex-loop",
        "repository": "yihan-hu/codex-loop",
        "source_state": "SOURCE_PUSHED",
        "deployment_target": "chatgpt_web_skill",
    }
    for key, want in expected.items():
        if value.get(key) != want:
            raise ValueError(f"handoff {key} must equal {want!r}")
    if not FULL_SHA.fullmatch(str(value["source_commit"])):
        raise ValueError("source_commit must be 40 lowercase hex")
    if not FULL_SHA.fullmatch(str(value["source_tree"])):
        raise ValueError("source_tree must be 40 lowercase hex")
    if not SHA256.fullmatch(str(value["package_sha256"])):
        raise ValueError("package_sha256 must be 64 lowercase hex")


def validate_package(package: Path, handoff: dict) -> dict:
    payload = package.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != handoff["package_sha256"]:
        raise ValueError("package SHA-256 does not match handoff")
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        if "codex-loop/SKILL.md" not in names:
            raise ValueError("package is not rooted at codex-loop/")
        foreign_skill_roots = {
            name.split("/", 1)[0]
            for name in names
            if "/SKILL.md" in name and name.count("/") == 1
        }
        if foreign_skill_roots != {"codex-loop"}:
            raise ValueError(f"package contains unexpected Skill roots: {sorted(foreign_skill_roots)}")
        manifest_name = "codex-loop/references/deployment-manifest.json"
        if manifest_name not in names:
            raise ValueError("package lacks deployment-manifest.json")
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
    if manifest.get("skill_name") != "codex-loop":
        raise ValueError("deployment manifest Skill name mismatch")
    distribution = manifest.get("distribution")
    if not isinstance(distribution, dict) or distribution.get("profile") != "maintainer":
        raise ValueError("installer requires a maintainer provenance-bound package")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("deployment manifest source binding missing")
    expected_source = {
        "repository": handoff["repository"],
        "commit": handoff["source_commit"],
        "tree": handoff["source_tree"],
    }
    if source != expected_source:
        raise ValueError("deployment manifest source binding does not match handoff")
    return {"package_sha256": digest, "manifest_source": source}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    args = parser.parse_args()
    try:
        handoff = load_handoff(args.handoff)
        validate_constants(handoff)
        result = validate_package(args.package, handoff)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        return fail(str(exc))
    print(json.dumps({
        "status": "PASS",
        **handoff,
        **result,
        "installer_invocation_mode": "implicit_exact_codex_loop_intent_or_explicit_skill",
        "terminal_surface_contract": "present_exact_canonical_package_through_host_native_skill_update_surface",
        "attachment_only_install_allowed": False,
        "bridge_required": False,
        "next_action": "present_exact_canonical_package_through_host_native_skill_update_surface_and_end_turn",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
