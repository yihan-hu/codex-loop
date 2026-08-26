import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from codex_loop_runtime.change_tracker import capture_baseline, sync_generation
from codex_loop_runtime.release_lineage import (
    capture_workspace_binding, dispatch_publish, publish_plan, record_publish_outcome,
)
from codex_loop_runtime.state import create_store


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, text=True)
    return proc.stdout.strip()


def init_repo(root: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.com")
    (root / "tracked.txt").write_text("base\n")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-qm", "base")
    return git(root, "rev-parse", "HEAD")


def make_store(root: Path):
    store = create_store(root)
    store.configure_task(
        store.path.parent.name, "fast push", ["fast path works"],
        requires_validation=False, no_validation_reason="fixture exercises publish bookkeeping",
    )
    store.set_meta("workspace_binding", capture_workspace_binding(root))
    capture_baseline(root, store)
    return store


class FastPushTests(unittest.TestCase):
    def test_commit_of_reviewed_index_preserves_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); init_repo(root); store = make_store(root)
            (root / "tracked.txt").write_text("changed\n")
            git(root, "add", "tracked.txt")
            self.assertTrue(sync_generation(root, store))
            generation = store.generation()
            store.set_criterion(0, "pass", "content reviewed")
            store.mark_reviewed()
            git(root, "commit", "-qm", "change")
            self.assertFalse(sync_generation(root, store))
            self.assertEqual(store.generation(), generation)
            self.assertEqual(int(store.get_meta("changes_reviewed_generation", -1)), generation)
            self.assertEqual(store.criteria()[0]["evidence_generation"], generation)

    def test_reset_to_different_content_stales_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = init_repo(root); store = make_store(root)
            (root / "tracked.txt").write_text("changed\n"); git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "change")
            sync_generation(root, store); generation = store.generation()
            git(root, "reset", "--hard", base)
            self.assertTrue(sync_generation(root, store))
            self.assertGreater(store.generation(), generation)

    def test_source_only_publish_needs_no_release_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = init_repo(root); store = make_store(root)
            (root / "tracked.txt").write_text("changed\n"); git(root, "add", "tracked.txt")
            sync_generation(root, store); store.set_criterion(0, "pass", "reviewed"); store.mark_reviewed()
            git(root, "commit", "-qm", "change")
            self.assertFalse(sync_generation(root, store))
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, source_only=True)
            self.assertTrue(plan["ready"]); self.assertTrue(plan["source_only"]); self.assertNotIn("release_id", plan)
            target = plan["target"]
            dispatch_publish(store, action_id=plan["action_id"], transport="git")
            result = record_publish_outcome(
                root, store, action_id=plan["action_id"], state="terminal_success", transport="git",
                evidence="native git readback matched", remote_commit=target["commit"], remote_tree=target["tree"],
            )
            self.assertEqual(result["state"], "terminal_success")
            self.assertTrue(result["source_only"]); self.assertNotIn("release_id", result)

    def test_release_publish_still_requires_receipt_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = init_repo(root); store = make_store(root)
            with self.assertRaisesRegex(RuntimeError, "no release receipt"):
                publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base)


if __name__ == "__main__":
    unittest.main()
