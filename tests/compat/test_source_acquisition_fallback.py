import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.codex_loop_runtime.source_acquisition import (
    restored_identity_result,
    source_acquisition_plan,
    verify_restored_git_workspace,
)

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

    def test_observability_gap_continues_same_authority_discovery_before_blocking(self):
        plan = source_acquisition_plan()
        self.assertEqual(plan["status"], "CONTINUE_DISCOVERY")
        self.assertEqual(plan["classification"], "DIRECT_ARTIFACT_DISCOVERY_INCOMPLETE")
        self.assertEqual(plan["discovery_scope"], "same_github_authority")
        self.assertFalse(plan["fallback_allowed"])
        self.assertIn("specialized workflow-run query", plan["next"])
        self.assertIn("receipt-bound published-source", plan["next"])

        recovered = source_acquisition_plan(receipt_bound_bundle_available=True)
        self.assertEqual(recovered["status"], "DIRECT")
        self.assertEqual(recovered["method"], "receipt_bound_git_bundle")

        blocked = source_acquisition_plan(same_authority_artifact_discovery_exhausted=True)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["classification"], "WORKSPACE_DOWNLOAD_ARTIFACT_UNAVAILABLE")
        self.assertEqual(blocked["discovery_scope"], "same_github_authority_exhausted")
        self.assertIn("do not start slow recovery automatically", blocked["next"])

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

    def test_exact_git_workspace_verifier_proves_commit_tree_origin_branch_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@e"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
            (root / "tracked.txt").write_text("exact\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "exact"], cwd=root, check=True)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/owner/repo.git"], cwd=root, check=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True).strip()
            result = verify_restored_git_workspace(
                root, repository="owner/repo", expected_commit=commit, expected_tree=tree,
                branch="main", method="github_git_bundle",
            )
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["exact"])
            self.assertTrue(result["history_complete"])
            self.assertEqual(result["origin_hint"], "github.com/owner/repo")
            self.assertEqual(result["workspace_binding"]["base_commit"], commit)

    def test_git_workspace_verifier_blocks_source_only_or_wrong_lineage_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@e"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
            (root / "tracked.txt").write_text("snapshot\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "snapshot root"], cwd=root, check=True)
            subprocess.run(["git", "remote", "add", "origin", "https://github.com/owner/repo.git"], cwd=root, check=True)
            actual_tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True).strip()
            result = verify_restored_git_workspace(
                root, repository="owner/repo", expected_commit="a" * 40, expected_tree=actual_tree,
                branch="main", method="receipt_bound_git_bundle",
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["classification"], "WORKSPACE_GIT_IDENTITY_MISMATCH")
            self.assertFalse(result["fallback_allowed"])
            self.assertIn("Git HEAD does not equal expected source commit", result["reasons"])
            self.assertIn("stop before lifecycle rebind or mutation", result["next"])

    def test_identity_mismatch_never_auto_falls_back(self):
        result = restored_identity_result(
            expected_commit="a" * 40, expected_tree="b" * 40,
            actual_commit="a" * 40, actual_tree="c" * 40,
        )
        self.assertEqual(result["classification"], "WORKSPACE_GIT_IDENTITY_MISMATCH")
        self.assertFalse(result["fallback_allowed"])
        self.assertIn("stop", result["next"])

    def test_cli_requires_exhausted_same_authority_discovery_before_blocking(self):
        discovery = subprocess.run(
            [sys.executable, str(CLI), "source-acquisition-plan"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        )
        self.assertEqual(json.loads(discovery.stdout)["data"]["status"], "CONTINUE_DISCOVERY")
        blocked = subprocess.run(
            [sys.executable, str(CLI), "source-acquisition-plan",
             "--same-authority-artifact-discovery-exhausted"],
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

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@e"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
            (root / "tracked.txt").write_text("exact\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "exact"], cwd=root, check=True)
            subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repo.git"], cwd=root, check=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True).strip()
            verified = subprocess.run(
                [sys.executable, str(CLI), "source-acquisition-verify",
                 "--cwd", str(root), "--repository", "owner/repo",
                 "--expected-commit", commit, "--expected-tree", tree, "--branch", "main"],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            self.assertEqual(json.loads(verified.stdout)["data"]["status"], "PASS")

    def test_verified_source_can_rebind_lifecycle_from_legacy_non_git_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy = base / "legacy"
            repo = base / "repo"
            legacy.mkdir()
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@e"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            (repo / "tracked.txt").write_text("exact\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "exact"], cwd=repo, check=True)
            subprocess.run(["git", "remote", "add", "origin", "git@github.com:owner/repo.git"], cwd=repo, check=True)
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, text=True).strip()
            env = os.environ.copy()
            env["CODEX_LOOP_HOME"] = str(base / "runtime")

            boot = subprocess.run(
                [sys.executable, str(CLI), "bootstrap", "--request-anchor", "rebind legacy workspace"],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            task_id = json.loads(boot.stdout)["data"]["task_id"]
            subprocess.run(
                [sys.executable, str(CLI), "orient", "--task-id", task_id, "--cwd", str(legacy)],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            verified = subprocess.run(
                [sys.executable, str(CLI), "source-acquisition-verify",
                 "--task-id", task_id, "--cwd", str(repo), "--repository", "owner/repo",
                 "--expected-commit", commit, "--expected-tree", tree, "--branch", "main"],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            verified_data = json.loads(verified.stdout)["data"]
            self.assertTrue(verified_data["lifecycle_rebind_ready"])
            subprocess.run(["git", "remote", "set-url", "origin", "git@github.com:other/repo.git"], cwd=repo, check=True)
            rejected = subprocess.run(
                [sys.executable, str(CLI), "orient", "--task-id", task_id, "--cwd", str(repo), "--rebind-verified"],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("origin does not match", rejected.stdout + rejected.stderr)
            subprocess.run(["git", "remote", "set-url", "origin", "git@github.com:owner/repo.git"], cwd=repo, check=True)
            rebound = subprocess.run(
                [sys.executable, str(CLI), "orient", "--task-id", task_id, "--cwd", str(repo), "--rebind-verified"],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            rebound_data = json.loads(rebound.stdout)["data"]
            self.assertTrue(rebound_data["rebound"])
            self.assertTrue(rebound_data["safe_to_mutate"])
            self.assertEqual(rebound_data["workspace_binding"]["base_commit"], commit)


if __name__ == "__main__":
    unittest.main()
