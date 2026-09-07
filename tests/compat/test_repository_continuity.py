from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.codex_loop_runtime.repository_continuity import (
    COLD_ACQUIRE_REQUIRED,
    HOT_REUSE,
    WARM_RESTORE_PUBLISHED_SOURCE,
    WARM_RESTORE_WORKSPACE_CACHE,
    repository_enter,
)

CLI = Path(__file__).resolve().parents[2] / "scripts" / "codex_loop.py"


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def init_repo(root: Path) -> tuple[str, str]:
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git(root, "config", "user.name", "Codex Loop Test")
    git(root, "config", "user.email", "codex-loop@example.invalid")
    git(root, "remote", "add", "origin", "https://github.com/yihan-hu/codex-loop.git")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-q", "-m", "base")
    return git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")


class RepositoryContinuityTests(unittest.TestCase):
    def test_cli_repository_enter_uses_routing_gate_and_returns_hot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            head, tree = init_repo(root)
            route = subprocess.run(
                ["python3", str(CLI), "route-init", "--host-surface", "chatgpt_web"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            session_id = json.loads(route.stdout)["data"]["session_id"]
            proc = subprocess.run(
                [
                    "python3", str(CLI), "repository-enter",
                    "--session-id", session_id,
                    "--cwd", str(root),
                    "--repository", "yihan-hu/codex-loop",
                    "--branch", "main",
                    "--remote-head", head,
                    "--remote-tree", tree,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
            )
            result = json.loads(proc.stdout)["data"]
            self.assertEqual(result["status"], HOT_REUSE)
            self.assertEqual(result["remote_sync"]["state"], "IN_SYNC")

    def test_hot_workspace_is_reused_without_source_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            head, tree = init_repo(root)
            result = repository_enter(
                root,
                repository="yihan-hu/codex-loop",
                branch="main",
                remote_head=head,
                remote_tree=tree,
            )
            self.assertEqual(result["status"], HOT_REUSE)
            self.assertFalse(result["source_reacquisition_required"])
            self.assertFalse(result["workspace_restore_required"])
            self.assertEqual(result["remote_sync"]["state"], "IN_SYNC")
            self.assertTrue(result["ready_for_mutation"])
            self.assertTrue(result["source_provenance"]["verified"])
            self.assertFalse(result["source_provenance"]["path_bound"])
            self.assertTrue(result["workspace_lease"]["path_bound"])

    def test_source_provenance_survives_workspace_path_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "first"
            head, tree = init_repo(first)
            first_result = repository_enter(
                first,
                repository="yihan-hu/codex-loop",
                branch="main",
                remote_head=head,
                remote_tree=tree,
            )
            provenance = first_result["source_provenance"]

            second = base / "second"
            subprocess.run(["git", "clone", "-q", "--no-local", str(first), str(second)], check=True)
            git(second, "remote", "set-url", "origin", "https://github.com/yihan-hu/codex-loop.git")
            second_result = repository_enter(
                second,
                repository="yihan-hu/codex-loop",
                branch="main",
                remote_head=head,
                remote_tree=tree,
                source_provenance=provenance,
            )
            self.assertEqual(second_result["status"], HOT_REUSE)
            self.assertEqual(second_result["source_provenance"]["base_commit"], head)
            self.assertNotEqual(
                first_result["workspace_lease"]["canonical_root"],
                second_result["workspace_lease"]["canonical_root"],
            )
            self.assertNotEqual(
                first_result["workspace_lease"]["repository_id"],
                second_result["workspace_lease"]["repository_id"],
            )

    def test_unseen_remote_head_requires_incremental_fetch_not_reacquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            init_repo(root)
            result = repository_enter(
                root,
                repository="yihan-hu/codex-loop",
                branch="main",
                remote_head="a" * 40,
                remote_tree="b" * 40,
            )
            self.assertEqual(result["status"], HOT_REUSE)
            self.assertFalse(result["source_reacquisition_required"])
            self.assertEqual(result["remote_sync"]["state"], "REMOTE_HEAD_UNSEEN")
            self.assertTrue(result["remote_sync"]["requires_incremental_fetch"])
            self.assertFalse(result["ready_for_mutation"])
            self.assertFalse(result["source_provenance"]["verified"])

    def test_remote_ahead_with_known_objects_is_sync_state_not_identity_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            base_head, _base_tree = init_repo(root)
            (root / "tracked.txt").write_text("remote\n", encoding="utf-8")
            git(root, "add", "tracked.txt")
            git(root, "commit", "-q", "-m", "remote")
            remote_head = git(root, "rev-parse", "HEAD")
            remote_tree = git(root, "rev-parse", "HEAD^{tree}")
            git(root, "reset", "--hard", base_head)

            result = repository_enter(
                root,
                repository="yihan-hu/codex-loop",
                branch="main",
                remote_head=remote_head,
                remote_tree=remote_tree,
            )
            self.assertEqual(result["status"], HOT_REUSE)
            self.assertEqual(result["remote_sync"]["state"], "REMOTE_AHEAD")
            self.assertFalse(result["source_reacquisition_required"])

    def test_missing_hot_prefers_workspace_cache_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            cache = {
                "cache_id": "c" * 32,
                "capsule_sha256": "d" * 64,
                "head_commit": "1" * 40,
                "head_tree": "2" * 40,
                "branch": "main",
                "repository": "yihan-hu/codex-loop",
                "expires_at": "2999-01-01T00:00:00Z",
                "consumed": False,
                "expired": False,
            }
            published = {
                "published_commit": "3" * 40,
                "published_tree": "4" * 40,
                "published_source_artifact": "published-source-1",
                "published_source_artifact_id": "123",
                "published_source_sha256": "5" * 64,
                "published_source_size": 1024,
                "fresh_restore": "PASS",
            }
            result = repository_enter(
                missing,
                repository="yihan-hu/codex-loop",
                branch="main",
                workspace_cache=cache,
                published_source=published,
            )
            self.assertEqual(result["status"], WARM_RESTORE_WORKSPACE_CACHE)
            self.assertFalse(result["source_reacquisition_required"])
            self.assertTrue(result["workspace_restore_required"])
            self.assertFalse(result["source_provenance"]["path_bound"])
            self.assertFalse(result["source_provenance"]["verified"])
            self.assertIn("workspace-cache-validate", result["source_provenance"]["verification_pending"])

    def test_missing_hot_uses_exact_published_source_before_cold_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            remote_head = "3" * 40
            remote_tree = "4" * 40
            published = {
                "published_commit": remote_head,
                "published_tree": remote_tree,
                "published_source_artifact": "published-source-42",
                "published_source_artifact_id": "9001",
                "published_source_sha256": "5" * 64,
                "published_source_size": 2048,
                "fresh_restore": "PASS",
            }
            result = repository_enter(
                missing,
                repository="yihan-hu/codex-loop",
                branch="main",
                remote_head=remote_head,
                remote_tree=remote_tree,
                published_source=published,
            )
            self.assertEqual(result["status"], WARM_RESTORE_PUBLISHED_SOURCE)
            self.assertFalse(result["source_reacquisition_required"])
            self.assertEqual(result["restore"]["published_commit"], remote_head)
            self.assertEqual(result["source_provenance"]["base_commit"], remote_head)

    def test_stale_published_source_is_warm_baseline_then_incremental_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            published = {
                "published_commit": "3" * 40,
                "published_tree": "4" * 40,
                "published_source_artifact": "published-source-42",
                "published_source_artifact_id": "9001",
                "published_source_sha256": "5" * 64,
                "published_source_size": 2048,
                "fresh_restore": "PASS",
            }
            result = repository_enter(
                missing,
                repository="yihan-hu/codex-loop",
                branch="main",
                remote_head="6" * 40,
                remote_tree="7" * 40,
                published_source=published,
            )
            self.assertEqual(result["status"], WARM_RESTORE_PUBLISHED_SOURCE)
            self.assertFalse(result["source_reacquisition_required"])
            self.assertTrue(result["restore"]["incremental_sync_required"])
            self.assertFalse(result["restore"]["remote_match"])
            self.assertIn("fetch only missing remote objects", result["next_action"])

    def test_unrelated_hot_history_is_rejected_even_with_matching_origin_and_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            remote_head, remote_tree = init_repo(root)
            (root / "tracked.txt").write_text("unrelated\n", encoding="utf-8")
            git(root, "add", "tracked.txt")
            unrelated_tree = git(root, "write-tree")
            unrelated_head = git(root, "commit-tree", unrelated_tree, "-m", "unrelated root")
            git(root, "reset", "--hard", unrelated_head)

            result = repository_enter(
                root,
                repository="yihan-hu/codex-loop",
                branch="main",
                remote_head=remote_head,
                remote_tree=remote_tree,
            )
            self.assertEqual(result["status"], COLD_ACQUIRE_REQUIRED)
            self.assertTrue(result["source_reacquisition_required"])
            self.assertIn("unrelated", " ".join(result["hot_rejection_reasons"]).lower())

    def test_source_only_snapshot_is_ignored_and_falls_to_warm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "snapshot"
            root.mkdir()
            (root / "SKILL.md").write_text("snapshot only\n", encoding="utf-8")
            published = {
                "published_commit": "3" * 40,
                "published_tree": "4" * 40,
                "published_source_artifact": "published-source-42",
                "published_source_artifact_id": "9001",
                "published_source_sha256": "5" * 64,
                "published_source_size": 2048,
                "fresh_restore": "PASS",
            }
            result = repository_enter(
                root,
                repository="yihan-hu/codex-loop",
                branch="main",
                published_source=published,
            )
            self.assertEqual(result["status"], WARM_RESTORE_PUBLISHED_SOURCE)
            self.assertIn("not a real Git working tree", " ".join(result["hot_rejection_reasons"]))

    def test_no_hot_or_warm_requires_cold_acquisition(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = repository_enter(
                Path(tmp) / "missing",
                repository="yihan-hu/codex-loop",
                branch="main",
            )
            self.assertEqual(result["status"], COLD_ACQUIRE_REQUIRED)
            self.assertTrue(result["full_source_acquisition_required"])


if __name__ == "__main__":
    unittest.main()
