import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from scripts.codex_loop_runtime.routing_state import route_init, record_permission_observation
from scripts.codex_loop_runtime.state import StateStore
from scripts.codex_loop_runtime.web_publish import build_web_publish_bundle, web_publish_plan


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, check=True).stdout.strip()


def init_repo(root):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / "tracked.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    return git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")


def ready_store(root):
    store = StateStore(root.parent / (root.name + "-state.sqlite3"))
    store.configure_task(root.name, "publish", ["publish"], requires_validation=False, no_validation_reason="test fixture uses no executable workload")
    store.set_meta("changes_reviewed_generation", 0)
    return store


def scopes():
    return {"github_push": "repo:owner/repo", "github_actions": "actions:owner/repo:download", "google_drive_write": "drive:staging"}


class FastPublishTests(unittest.TestCase):
    def route(self):
        return route_init(session_id="fast-" + uuid.uuid4().hex, host_surface="chatgpt_web")

    def cleanup(self, r):
        p = Path(r["state_path"])
        for x in (p, p.with_suffix(".capabilities.json")):
            try:
                x.unlink()
            except FileNotFoundError:
                pass

    def caps(self, sid):
        for capability, scope in scopes().items():
            record_permission_observation(session_id=sid, capability=capability, scope=scope, evidence="live probe")

    def test_fast_publish_reuses_fresh_observations(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            head, _tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            self.caps(route["session_id"])
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree="0" * 40, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["mode"], "FAST_PUBLISH")
                self.assertTrue(plan["validation_reused"])
                self.assertEqual(len(plan["capability_observations_reused"]), 3)
            finally:
                self.cleanup(route)

    def test_dirty_workspace_falls_back(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            self.caps(route["session_id"])
            (root / "tracked.txt").write_text("dirty\n")
            try:
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree=tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["mode"], "FULL_VERIFIED_PUBLISH")
                self.assertIn("workspace_not_clean", plan["fallback_reasons"])
            finally:
                self.cleanup(route)

    def test_bundle_receipt_reuse_is_exact(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            self.caps(route["session_id"])
            bundle = root.parent / (root.name + "-fast-publish.bundle")
            try:
                receipt = build_web_publish_bundle(root, store, output=bundle)
                plan = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree="0" * 40, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertEqual(plan["bundle_action"], "reuse")
                self.assertEqual(plan["bundle"]["sha256"], receipt["sha256"])
                self.assertEqual(plan["bundle"]["source_commit"], head)
                self.assertEqual(plan["bundle"]["source_tree"], tree)
            finally:
                self.cleanup(route)
                bundle.unlink(missing_ok=True)

    def test_bundle_can_use_exact_ancestor_as_prerequisite(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            base_commit, _base_tree = init_repo(root)
            (root / "second.txt").write_text("second\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "second"], cwd=root, check=True)
            head = git(root, "rev-parse", "HEAD")
            store = ready_store(root)
            bundle = root.parent / (root.name + "-thin.bundle")
            try:
                receipt = build_web_publish_bundle(root, store, output=bundle, prerequisite_commit=base_commit)
                self.assertEqual(receipt["source_commit"], head)
                self.assertEqual(receipt["prerequisite_commit"], base_commit)
                verify = subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(verify.returncode, 0, verify.stderr)
            finally:
                bundle.unlink(missing_ok=True)

    def test_only_exact_remote_commit_and_tree_short_circuit_transport(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            head, tree = init_repo(root)
            store = ready_store(root)
            route = self.route()
            self.caps(route["session_id"])
            try:
                exact = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head=head, remote_tree=tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertTrue(exact["already_published_exactly"])
                self.assertIn("skip transport", exact["next"])
                tree_only = web_publish_plan(root, store, session_id=route["session_id"], repository="owner/repo", branch="main", remote_head="f" * 40, remote_tree=tree, capability_scopes=scopes(), verified_tree_fast_path=True)
                self.assertFalse(tree_only["already_published_exactly"])
            finally:
                self.cleanup(route)


if __name__ == "__main__":
    unittest.main()
