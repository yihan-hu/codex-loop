import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ArchitectureFidelityTests(unittest.TestCase):
    def test_manifest_has_no_unresolved_surfaces_and_divergences_have_upgrade_paths(self):
        data = json.loads((ROOT / "references" / "architecture-fidelity.yaml").read_text())
        self.assertEqual(data["schema_version"], 1)
        self.assertTrue(data["watch_surfaces"])
        for entry in data["watch_surfaces"]:
            self.assertNotEqual(entry["status"], "NEEDS_REVIEW")
            if entry["status"] in {"PARTIAL", "HOST_GAP", "LOCAL_DIVERGENCE"}:
                self.assertTrue(entry.get("divergence"))
                self.assertTrue(entry.get("upgrade_path"))

    def test_audit_script_checks_architecture_governance_without_upstream_checkout(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "audit_source_coverage.py")],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True,
        )
        result = json.loads(proc.stdout)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["architecture_surfaces"], 8)
        self.assertEqual(result["architecture_observed_commit"], "2b7c279735d0d096cf7b34fe98938f46792f4d4f")


if __name__ == "__main__":
    unittest.main()
