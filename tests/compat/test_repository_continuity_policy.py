from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RepositoryContinuityPolicyTests(unittest.TestCase):
    def test_skill_loads_repository_continuity_only_for_repository_routing(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        continuity = (ROOT / "references" / "repository-continuity.md").read_text(encoding="utf-8")
        self.assertIn("references/repository-continuity.md", skill)
        self.assertIn("Keep routing checks at the action boundary", skill)
        self.assertIn("HOT -> WARM -> COLD", continuity)
        self.assertIn("`HOT_REUSE` always wins", continuity)
        self.assertIn("COLD_ACQUIRE_REQUIRED", continuity)
        self.assertIn("REMOTE_HEAD_MOVED != SOURCE_IDENTITY_STALE", continuity)

    def test_source_acquisition_is_cold_only(self):
        text = (ROOT / "references" / "source-acquisition.md").read_text(encoding="utf-8")
        self.assertIn("only when `repository-enter` has already returned `COLD_ACQUIRE_REQUIRED`", text)
        self.assertIn("not automatically source-acquisition intent", text)
        self.assertIn("fetch only the missing remote objects", text)

    def test_published_source_is_declared_warm_recovery(self):
        text = (ROOT / "references" / "web-mode-publish.md").read_text(encoding="utf-8")
        self.assertIn("WARM_RESTORE_PUBLISHED_SOURCE", text)
        self.assertIn("WARM restore, not cold source acquisition", text)

    def test_architecture_tracks_git_like_continuity_gap(self):
        data = json.loads((ROOT / "references" / "architecture-fidelity.yaml").read_text(encoding="utf-8"))
        entries = {item["id"]: item for item in data["watch_surfaces"]}
        entry = entries["git_like_repository_continuity"]
        self.assertIn("path-independent source provenance", entry["divergence"])
        self.assertIn("cold source acquisition is never the normal push path", entry["upgrade_path"])


if __name__ == "__main__":
    unittest.main()
