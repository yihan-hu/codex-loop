#!/usr/bin/env python3
"""Generate the proven-minimal Codex Loop self-update bridge Skill source.

The bridge is intentionally generated outside the Codex Loop Skill tree because a
Skill package may contain only one SKILL.md entrypoint. Keep this bridge minimal:
its purpose is to establish a stable different-name Skill execution identity for a
later host-native Codex Loop update turn, not to embed updater logic in the package.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BRIDGE_NAME = "codex-loop-update-bridge"

SKILL_MD = '''---
name: codex-loop-update-bridge
description: "Minimal explicit-only recovery helper used to verify the stable different-name installation path for a Codex Loop update. Use only when explicitly testing or continuing recovery from disappearing same-name Codex Loop update UI."
---

# Codex Loop Update Bridge

Respond with exactly: `UPDATE_BRIDGE_ACTIVE` when this Skill is explicitly invoked.
'''

OPENAI_YAML = '''interface:
  display_name: Codex Loop Update Bridge
  short_description: Minimal Codex Loop update recovery bridge
  default_prompt: Use $codex-loop-update-bridge to continue the stable different-name Codex Loop update recovery path.
policy:
  allow_implicit_invocation: false
  products:
  - chatgpt
  - codex
  - api
  - atlas
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, help="Directory that will receive codex-loop-update-bridge/")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable generation metadata")
    args = parser.parse_args()

    root = Path(args.output_dir).expanduser().resolve() / BRIDGE_NAME
    if root.exists():
        raise SystemExit(f"refusing to overwrite existing bridge directory: {root}")
    (root / "agents").mkdir(parents=True)
    (root / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (root / "agents" / "openai.yaml").write_text(OPENAI_YAML, encoding="utf-8")

    payload = {
        "status": "BRIDGE_SOURCE_READY",
        "bridge_name": BRIDGE_NAME,
        "path": str(root),
        "explicit_only": True,
        "minimal_profile": True,
        "file_count": 2,
        "default_prompt_self_reference": "$codex-loop-update-bridge",
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
