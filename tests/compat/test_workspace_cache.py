import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.codex_loop_runtime.workspace_cache import (
    CACHE_DRIVE_FOLDER,
    build_workspace_cache,
    restore_workspace_cache,
    validate_workspace_cache,
    workspace_cache_cleanup_plan,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, stdout=subprocess.PIPE
    ).stdout.strip()


class WorkspaceCacheTests(unittest.TestCase):
    def init_dirty_repo(self, root: Path) -> tuple[str, str]:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "cache-test"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "cache@example.com"], cwd=root, check=True)
        (root / "tracked.txt").write_text("base\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        (root / "tracked.txt").write_text("staged\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        with (root / "tracked.txt").open("a") as f:
            f.write("unstaged\n")
        (root / "untracked.bin").write_bytes(b"\x00cache\xff\n")
        (root / "ignored.tmp").write_text("ignored\n")
        (root / ".gitignore").write_text("ignored.tmp\n")
        subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "ignore"], cwd=root, check=True)
        # restore dirty tracked state after commit
        (root / "tracked.txt").write_text("staged\n")
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        with (root / "tracked.txt").open("a") as f:
            f.write("unstaged\n")
        return git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")

    def test_round_trip_preserves_git_identity_and_dirty_state(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / "src"
            src.mkdir()
            head, tree = self.init_dirty_repo(src)
            capsule = base / "cache.tar.gz"
            receipt = build_workspace_cache(src, output=capsule, repository="owner/repo")
            self.assertEqual(receipt["head_commit"], head)
            self.assertEqual(receipt["head_tree"], tree)
            self.assertEqual(receipt["drive_folder_path"], CACHE_DRIVE_FOLDER)
            self.assertEqual(
                datetime.fromisoformat(receipt["expires_at"].replace("Z", "+00:00"))
                - datetime.fromisoformat(receipt["created_at"].replace("Z", "+00:00")),
                timedelta(days=7),
            )
            validated = validate_workspace_cache(capsule, expected_sha256=receipt["capsule_sha256"])
            self.assertEqual(validated["head_commit"], head)
            dest = base / "restored"
            consumed = base / "consumed.json"
            restored = restore_workspace_cache(
                capsule,
                destination=dest,
                expected_sha256=receipt["capsule_sha256"],
                consumption_receipt_output=consumed,
            )
            self.assertEqual(restored["status"], "WORKSPACE_RESTORED")
            self.assertFalse(restored["cleanup_failure_invalidates_restore"])
            self.assertEqual(git(dest, "rev-parse", "HEAD"), head)
            self.assertEqual(git(dest, "rev-parse", "HEAD^{tree}"), tree)
            self.assertEqual(git(dest, "status", "--short"), git(src, "status", "--short"))
            self.assertEqual((dest / "tracked.txt").read_bytes(), (src / "tracked.txt").read_bytes())
            self.assertEqual((dest / "untracked.bin").read_bytes(), (src / "untracked.bin").read_bytes())
            self.assertFalse((dest / "ignored.tmp").exists())
            consumed_data = json.loads(consumed.read_text())
            self.assertEqual(consumed_data["cache_id"], receipt["cache_id"])
            self.assertTrue(consumed_data["cleanup_pending"])

    def test_detached_head_round_trip_preserves_exact_identity(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            src = base / "src"
            src.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=src, check=True)
            subprocess.run(["git", "config", "user.name", "cache-test"], cwd=src, check=True)
            subprocess.run(["git", "config", "user.email", "cache@example.com"], cwd=src, check=True)
            (src / "a.txt").write_text("a\n")
            subprocess.run(["git", "add", "."], cwd=src, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=src, check=True)
            head = git(src, "rev-parse", "HEAD")
            tree = git(src, "rev-parse", "HEAD^{tree}")
            subprocess.run(["git", "checkout", "--detach", "-q", head], cwd=src, check=True)
            (src / "scratch.txt").write_text("scratch\n")
            capsule = base / "detached.tar.gz"
            receipt = build_workspace_cache(src, output=capsule, repository="owner/repo")
            self.assertIsNone(receipt["branch"])
            dest = base / "restored"
            restored = restore_workspace_cache(capsule, destination=dest, expected_sha256=receipt["capsule_sha256"])
            self.assertEqual(restored["head_commit"], head)
            self.assertEqual(restored["head_tree"], tree)
            self.assertIsNone(restored["branch"])
            self.assertEqual((dest / "scratch.txt").read_text(), "scratch\n")

    def test_cli_exposes_workspace_cache_surface(self):
        root = Path(__file__).resolve().parents[2]
        cli = root / "scripts" / "codex_loop.py"
        for command in ("workspace-cache-create", "workspace-cache-validate", "workspace-cache-restore", "workspace-cache-cleanup-plan"):
            proc = subprocess.run(["python3", str(cli), command, "--help"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(proc.returncode, 0, command)

    def test_outer_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            root.mkdir()
            self.init_dirty_repo(root)
            capsule = Path(td) / "cache.tar.gz"
            build_workspace_cache(root, output=capsule)
            with self.assertRaises(ValueError):
                validate_workspace_cache(capsule, expected_sha256="0" * 64)

    def test_cleanup_plan_handles_consumed_expired_and_unproven(self):
        now = datetime(2026, 9, 10, tzinfo=timezone.utc)
        old = "2026-09-01T00:00:00Z"
        fresh = "2026-09-09T00:00:00Z"
        cache_a = "a" * 32
        cache_b = "b" * 32
        cache_c = "c" * 32
        sha = "d" * 64
        objects = [
            {"id": "a1", "name": f"workspace-cache-v1-{cache_a}-20260909T000000Z-{sha}.tar.gz", "created_at": fresh, "bounded_parent_proven": True, "ownership_proven": True},
            {"id": "a2", "name": f"workspace-cache-consumed-v1-{cache_a}.json", "created_at": fresh, "bounded_parent_proven": True, "ownership_proven": True},
            {"id": "b1", "name": f"workspace-cache-v1-{cache_b}-20260901T000000Z-{sha}.tar.gz", "created_at": old, "bounded_parent_proven": True, "ownership_proven": True},
            {"id": "c1", "name": f"workspace-cache-v1-{cache_c}-20260901T000000Z-{sha}.tar.gz", "created_at": old, "bounded_parent_proven": False, "ownership_proven": True},
            {"id": "other", "name": "not-a-cache.txt", "created_at": old, "bounded_parent_proven": True, "ownership_proven": True},
        ]
        plan = workspace_cache_cleanup_plan(objects, now=now)
        reasons = {item["cache_id"]: item["reason"] for item in plan["delete_candidates"]}
        self.assertEqual(reasons[cache_a], "consumed")
        self.assertEqual(reasons[cache_b], "expired_7d")
        self.assertIn(cache_a, plan["auto_restore_excluded_cache_ids"])
        self.assertTrue(any(item.get("cache_id") == cache_c for item in plan["cleanup_pending"]))
        self.assertEqual(plan["ignored_non_cache_objects"][0]["id"], "other")

        preserved = workspace_cache_cleanup_plan(objects, now=now, preserve_cache_ids={cache_b})
        self.assertIn(cache_b, preserved["preserved_cache_ids"])
        self.assertFalse(any(item.get("cache_id") == cache_b for item in preserved["delete_candidates"]))
        self.assertTrue(any(item.get("cache_id") == cache_b and item["reason"] == "explicit_restore_in_progress" for item in preserved["retained"]))


if __name__ == "__main__":
    unittest.main()
