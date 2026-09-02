#!/usr/bin/env python3
"""Generate a fresh install-compatible Codex Loop self-update bridge Skill.

The bridge is intentionally generated outside the Codex Loop Skill tree because a
Skill package may contain only one SKILL.md entrypoint. Keep each bridge minimal
and give every recovery attempt a fresh Skill identity so host-catalog collisions
cannot collapse the native Save surface into an existing-Skill trial surface.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
from pathlib import Path

BRIDGE_NAME_PREFIX = "codex-loop-update-bridge"
INSTANCE_ID_RE = re.compile(r"^[a-z0-9]{5,12}$")


def _resolve_instance_id(raw: str | None) -> str:
    instance_id = raw or secrets.token_hex(3)
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise SystemExit("instance id must be 5-12 lowercase alphanumeric characters")
    return instance_id


def _render_skill_md(bridge_name: str) -> str:
    return f'''---
name: {bridge_name}
description: "Minimal explicit-only one-shot recovery helper for a Codex Loop self-update after same-name update UI instability. Use only when explicitly invoked for this specific recovery instance."
---

# Codex Loop Update Bridge

When explicitly invoked to continue a proven Codex Loop recovery, require an already-validated canonical `codex-loop` `skill.zip` in the current conversation. Present that exact package through the host-native Skill update surface, then end the turn immediately. Do not invoke Codex Loop and do not edit, repackage, rename, or substitute the canonical package.
'''


def _render_openai_yaml(bridge_name: str, instance_id: str) -> str:
    return f'''interface:
  display_name: Codex Loop Update Bridge {instance_id.upper()}
  short_description: One-shot Codex Loop update recovery bridge
  default_prompt: Use ${bridge_name} to continue this isolated Codex Loop update recovery path.
policy:
  allow_implicit_invocation: false
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, help="Directory that will receive a freshly named bridge Skill folder")
    parser.add_argument(
        "--instance-id",
        help="Optional 5-12 character lowercase alphanumeric suffix for deterministic tests; omit in real recovery to generate a fresh suffix",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable generation metadata")
    args = parser.parse_args()

    instance_id = _resolve_instance_id(args.instance_id)
    bridge_name = f"{BRIDGE_NAME_PREFIX}-{instance_id}"
    root = Path(args.output_dir).expanduser().resolve() / bridge_name
    if root.exists():
        raise SystemExit(f"refusing to overwrite existing bridge directory: {root}")
    (root / "agents").mkdir(parents=True)
    (root / "SKILL.md").write_text(_render_skill_md(bridge_name), encoding="utf-8")
    (root / "agents" / "openai.yaml").write_text(_render_openai_yaml(bridge_name, instance_id), encoding="utf-8")

    payload = {
        "status": "BRIDGE_SOURCE_READY",
        "bridge_name": bridge_name,
        "bridge_name_prefix": BRIDGE_NAME_PREFIX,
        "instance_id": instance_id,
        "path": str(root),
        "explicit_only": True,
        "minimal_profile": True,
        "install_compatible_metadata_profile": True,
        "policy_products_present": False,
        "fresh_unique_identity": True,
        "fixed_name_reuse_allowed": False,
        "file_count": 2,
        "default_prompt_self_reference": f"${bridge_name}",
        "production_skill_name": "codex-loop",
        "production_package_mutation_allowed": False,
        "next_step": "package_generated_bridge_with_skill_creator_official_packager",
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
