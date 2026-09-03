import json
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.codex_loop_runtime.source_acquisition import restored_identity_result, source_acquisition_plan

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


class SourceAcquisitionFallbackTests(unittest.TestCase):
    def test_exact_bundle_is_direct(self):
        plan = source_acquisition_plan(exact_commit_bundle_available=True)
        self.assertEqual(plan["status"], "DIRECT")
        self.assertEqual(plan["method"], "github_git_bundle")
        self.assertFalse(plan["fallback_allowed"])

    def test_receipt_bound_bundle_is_direct(self):
        plan = source_acquisition_plan(receipt_bound_bundle_available=True)
        self.assertEqual(plan["method"], "receipt_bound_git_bundle")
        self.assertFalse(plan["fallback_allowed"])

    def test_missing_direct_artifact_blocks_without_fallback(self):
        plan = source_acquisition_plan()
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertEqual(plan["classification"], "WORKSPACE_DOWNLOAD_ARTIFACT_UNAVAILABLE")
        self.assertFalse(plan["fallback_allowed"])
        self.assertIn("do not start slow recovery automatically", plan["next"])

    def test_fallback_requires_current_task_user_authorization_not_evidence_alone(self):
        with self.assertRaises(PermissionError):
            source_acquisition_plan(
                fallback_method="verified_incremental_replay",
                authorization_evidence="old conversation allowed it",
            )
        plan = source_acquisition_plan(
            fallback_method="verified_incremental_replay",
            current_user_fallback_authorization_observed=True,
            authorization_evidence="user explicitly allows verified incremental replay for this bootstrap only",
        )
        self.assertEqual(plan["status"], "FALLBACK_AUTHORIZED")
        self.assertEqual(plan["authorization_scope"], "current_task_only")
        self.assertTrue(plan["requires_exact_final_commit_tree"])

    def test_identity_mismatch_never_auto_falls_back(self):
        result = restored_identity_result(
            expected_commit="a" * 40, expected_tree="b" * 40,
            actual_commit="a" * 40, actual_tree="c" * 40,
        )
        self.assertEqual(result["classification"], "WORKSPACE_GIT_IDENTITY_MISMATCH")
        self.assertFalse(result["fallback_allowed"])
        self.assertIn("stop", result["next"])

    def test_cli_default_is_blocked_and_explicit_fallback_is_scoped(self):
        blocked = subprocess.run(
            [sys.executable, str(CLI), "source-acquisition-plan"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        self.assertEqual(json.loads(blocked.stdout)["data"]["status"], "BLOCKED")
        allowed = subprocess.run(
            [sys.executable, str(CLI), "source-acquisition-plan",
             "--fallback-method", "verified_incremental_replay",
             "--current-user-fallback-authorization-observed",
             "--authorization-evidence", "explicit current-task authorization"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        self.assertEqual(json.loads(allowed.stdout)["data"]["status"], "FALLBACK_AUTHORIZED")


if __name__ == "__main__":
    unittest.main()
