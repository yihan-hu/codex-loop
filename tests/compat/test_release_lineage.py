import base64
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from codex_loop_runtime.change_tracker import capture_baseline, sync_generation
from codex_loop_runtime.completion import CompletionStatus, assess
from codex_loop_runtime.release_lineage import (
    CONNECTOR_INLINE_MAX_ENTRIES,
    CONNECTOR_INLINE_MAX_ENTRY_BYTES,
    CONNECTOR_INLINE_MAX_TOTAL_BYTES,
    MODEL_DISPATCH_BATCH_MAX_ITEMS,
    MODEL_DISPATCH_BATCH_MAX_RAW_BYTES,
    acknowledge_publish_model_dispatch_batch,
    acknowledge_publish_model_dispatch_tree,
    acknowledge_publish_stable,
    acknowledge_publish_stable_portable,
    capture_workspace_binding,
    classify_connector_manifest,
    current_release_receipt,
    diff_object_manifest,
    dispatch_publish,
    export_publish_stable_portable_receipt,
    publish_model_dispatch_status,
    publish_plan,
    publish_stable_status,
    reconcile_publish_stable,
    record_publish_outcome,
    record_release_receipt,
    release_plan,
    start_publish_model_dispatch,
    start_publish_stable,
    start_publish_stable_portable,
    workspace_binding_status,
)
from codex_loop_runtime.state import create_store


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, text=True)
    return proc.stdout.strip()


def init_repo(root: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    git(root, "config", "user.name", "Test User")
    git(root, "config", "user.email", "test@example.com")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-qm", "base")
    return git(root, "rev-parse", "HEAD")


def make_store(root: Path):
    store = create_store(root)
    store.configure_task(
        store.path.parent.name,
        "release lineage fixture",
        ["release lineage works"],
        requires_validation=False,
        no_validation_reason="fixture exercises release lineage directly",
    )
    store.set_meta("workspace_binding", capture_workspace_binding(root))
    capture_baseline(root, store)
    return store


class ReleaseLineageTests(unittest.TestCase):
    def test_worktrees_share_repository_identity_but_independent_clone_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "repo"
            worktree = Path(tmp) / "worktree"
            clone = Path(tmp) / "clone"
            base.mkdir()
            init_repo(base)
            subprocess.run(["git", "worktree", "add", "-q", "-b", "feature", str(worktree)], cwd=base, check=True)
            subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(base), str(clone)], check=True)
            a = capture_workspace_binding(base)
            b = capture_workspace_binding(worktree)
            c = capture_workspace_binding(clone)
            self.assertEqual(a["repository_id"], b["repository_id"])
            self.assertTrue(b["linked_worktree"])
            self.assertNotEqual(a["repository_id"], c["repository_id"])

    def test_binding_persists_only_credential_free_origin_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            git(root, "remote", "add", "origin", "https://user:topsecret@github.com/owner/repo.git")
            binding = capture_workspace_binding(root)
            self.assertEqual(binding["origin_hint"], "github.com/owner/repo")
            self.assertNotIn("topsecret", repr(binding))

    def test_binding_status_detects_different_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a"
            b = Path(tmp) / "b"
            a.mkdir(); b.mkdir()
            init_repo(a); init_repo(b)
            status = workspace_binding_status(b, capture_workspace_binding(a))
            self.assertTrue(status["bound"])
            self.assertFalse(status["matches"])
            self.assertIn("canonical root changed", status["reasons"])

    def test_binding_status_detects_origin_repoint_in_same_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            git(root, "remote", "add", "origin", "https://github.com/owner/repo.git")
            binding = capture_workspace_binding(root)
            git(root, "remote", "set-url", "origin", "https://github.com/other/repo.git")
            status = workspace_binding_status(root, binding)
            self.assertTrue(status["bound"])
            self.assertFalse(status["matches"])
            self.assertIn("Git origin identity changed", status["reasons"])
            git(root, "remote", "remove", "origin")
            removed = workspace_binding_status(root, binding)
            self.assertFalse(removed["matches"])
            self.assertIn("Git origin identity changed", removed["reasons"])

    def test_binding_status_detects_disconnected_history_in_same_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            binding = capture_workspace_binding(root)
            git(root, "checkout", "-q", "--orphan", "disconnected")
            git(root, "rm", "-q", "-rf", ".")
            (root / "replacement.txt").write_text("replacement\n", encoding="utf-8")
            git(root, "add", "replacement.txt")
            git(root, "commit", "-qm", "disconnected root")
            status = workspace_binding_status(root, binding)
            self.assertTrue(status["bound"])
            self.assertFalse(status["matches"])
            self.assertIn("Git history no longer descends from bound base commit", status["reasons"])

    def test_release_plan_requires_committed_tracked_source_and_excludes_untracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            store = make_store(root)
            (root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "not committed"):
                release_plan(root, store, artifact_name="skill.zip")
            git(root, "checkout", "--", "tracked.txt")
            (root / "scratch.log").write_text("not source\n", encoding="utf-8")
            plan = release_plan(root, store, artifact_name="skill.zip", archive_prefix="codex-loop")
            self.assertTrue(plan["ready"])
            self.assertEqual(plan["source"]["commit"], git(root, "rev-parse", "HEAD"))
            self.assertEqual(plan["source"]["tree"], git(root, "rev-parse", "HEAD^{tree}"))
            self.assertIn("scratch.log", plan["excluded_untracked"]["paths"])
            self.assertEqual(plan["archive"]["argv"][-1], plan["source"]["commit"])
            self.assertIn("codex-loop/", plan["archive"]["argv"])

    def test_release_receipt_is_generation_and_commit_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            store = make_store(root)
            receipt = record_release_receipt(
                root,
                store,
                artifact_name="skill.zip",
                artifact_sha256="a" * 64,
                evidence="archive and package hashes were verified",
            )
            current = current_release_receipt(root, store, receipt["release_id"])
            self.assertTrue(current["current"])
            (root / "later.txt").write_text("later\n", encoding="utf-8")
            sync_generation(root, store)
            stale = current_release_receipt(root, store, receipt["release_id"])
            self.assertFalse(stale["current"])

    def test_diff_manifest_uses_git_object_ids_and_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            (root / "new.txt").write_text("new\n", encoding="utf-8")
            git(root, "add", "-A")
            git(root, "commit", "-qm", "change")
            target = git(root, "rev-parse", "HEAD")
            manifest = diff_object_manifest(root, base, target)
            by_path = {x["path"]: x for x in manifest}
            self.assertEqual(set(by_path), {"new.txt", "tracked.txt"})
            for item in by_path.values():
                self.assertRegex(item["new_sha"], r"^[0-9a-f]{40}$")
                self.assertEqual(item["object_type"], "blob")
                self.assertGreater(item["size"], 0)

    def test_connector_transfer_batches_utf8_from_git_objects_not_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            (root / "tracked.txt").write_text("target text\n", encoding="utf-8")
            (root / "new.txt").write_text("new text\n", encoding="utf-8")
            git(root, "add", "tracked.txt", "new.txt")
            git(root, "commit", "-qm", "text batch")
            target = git(root, "rev-parse", "HEAD")
            manifest = diff_object_manifest(root, base, target)

            # Classification must read the committed Git blobs, never the mutable worktree copy.
            (root / "tracked.txt").write_bytes(b"\x00\xffworktree-only")
            classified, summary = classify_connector_manifest(root, manifest)
            by_path = {item["path"]: item for item in classified}
            self.assertEqual(by_path["tracked.txt"]["transfer"], "inline_utf8")
            self.assertEqual(by_path["new.txt"]["transfer"], "inline_utf8")
            self.assertTrue(by_path["tracked.txt"]["content_source"].startswith("git_blob:"))
            self.assertEqual(summary["inline_utf8"]["count"], 2)
            self.assertEqual(summary["create_blob"]["count"], 0)
            self.assertEqual(summary["estimated_connector_writes_before_commit"], 1)

    def test_connector_transfer_falls_back_for_binary_and_oversized_blobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            (root / "binary.dat").write_bytes(b"\x00\xff\x01")
            (root / "oversized.txt").write_text("x" * (CONNECTOR_INLINE_MAX_ENTRY_BYTES + 1), encoding="utf-8")
            git(root, "add", "binary.dat", "oversized.txt")
            git(root, "commit", "-qm", "fallback blobs")
            target = git(root, "rev-parse", "HEAD")
            classified, summary = classify_connector_manifest(root, diff_object_manifest(root, base, target))
            by_path = {item["path"]: item for item in classified}
            self.assertEqual(by_path["binary.dat"]["transfer"], "create_blob")
            self.assertEqual(by_path["binary.dat"]["transfer_reason"], "contains_nul")
            self.assertEqual(by_path["oversized.txt"]["transfer"], "create_blob")
            self.assertEqual(by_path["oversized.txt"]["transfer_reason"], "entry_too_large")
            self.assertEqual(summary["create_blob"]["count"], 2)
            self.assertEqual(summary["estimated_connector_writes_before_commit"], 3)

    def test_connector_transfer_respects_total_inline_byte_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            chunk = 120 * 1024
            for index in range(5):
                (root / f"batch-{index}.txt").write_text("x" * chunk, encoding="utf-8")
            git(root, "add", "batch-0.txt", "batch-1.txt", "batch-2.txt", "batch-3.txt", "batch-4.txt")
            git(root, "commit", "-qm", "bounded text batch")
            target = git(root, "rev-parse", "HEAD")
            classified, summary = classify_connector_manifest(root, diff_object_manifest(root, base, target))
            inline = [item for item in classified if item["transfer"] == "inline_utf8"]
            fallback = [item for item in classified if item["transfer"] == "create_blob"]
            self.assertEqual(len(inline), 4)
            self.assertEqual(len(fallback), 1)
            self.assertEqual(fallback[0]["transfer_reason"], "inline_byte_budget_exceeded")
            self.assertLessEqual(summary["inline_utf8"]["bytes"], CONNECTOR_INLINE_MAX_TOTAL_BYTES)

    def test_connector_transfer_respects_inline_entry_count_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            for index in range(CONNECTOR_INLINE_MAX_ENTRIES + 1):
                (root / f"entry-{index:03d}.txt").write_text("x", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-qm", "bounded entry count")
            target = git(root, "rev-parse", "HEAD")
            classified, summary = classify_connector_manifest(root, diff_object_manifest(root, base, target))
            inline = [item for item in classified if item["transfer"] == "inline_utf8"]
            fallback = [item for item in classified if item["transfer"] == "create_blob"]
            self.assertEqual(len(inline), CONNECTOR_INLINE_MAX_ENTRIES)
            self.assertEqual(len(fallback), 1)
            self.assertEqual(fallback[0]["transfer_reason"], "inline_entry_budget_exceeded")
            self.assertEqual(summary["inline_utf8"]["count"], CONNECTOR_INLINE_MAX_ENTRIES)

    def test_connector_transfer_keeps_deletion_in_batched_tree_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            (root / "tracked.txt").unlink()
            git(root, "add", "-A")
            git(root, "commit", "-qm", "delete tracked")
            target = git(root, "rev-parse", "HEAD")
            classified, summary = classify_connector_manifest(root, diff_object_manifest(root, base, target))
            self.assertEqual(len(classified), 1)
            self.assertEqual(classified[0]["path"], "tracked.txt")
            self.assertEqual(classified[0]["transfer"], "tree_delete")
            self.assertEqual(classified[0]["tree_mode"], "100644")
            self.assertEqual(classified[0]["tree_type"], "blob")
            self.assertEqual(summary["tree_delete"]["count"], 1)
            self.assertEqual(summary["estimated_connector_writes_before_commit"], 1)

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_model_dispatch_queue_batches_exact_blobs_resumes_and_builds_one_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            store = make_store(root)
            (root / "tracked.txt").unlink()
            for index in range(5):
                (root / f"blob-{index}.txt").write_text(chr(65 + index) * 40000, encoding="utf-8")
            git(root, "add", "-A")
            git(root, "commit", "-qm", "model dispatcher payloads")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(
                root, store, artifact_name="skill.zip", artifact_sha256="8" * 64, evidence="verified",
            )
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            dispatch_publish(store, action_id=plan["action_id"], transport="github_object_api")

            first = start_publish_model_dispatch(root, store, action_id=plan["action_id"])
            self.assertEqual(first["phase"], "blob_batch")
            self.assertLessEqual(first["batch"]["count"], MODEL_DISPATCH_BATCH_MAX_ITEMS)
            self.assertLessEqual(first["batch"]["raw_bytes"], MODEL_DISPATCH_BATCH_MAX_RAW_BYTES)
            self.assertEqual(first["batch"]["count"], 2)
            first_shas = []
            for item in first["batch"]["items"]:
                self.assertEqual(item["connector_action"], "create_blob")
                self.assertEqual(item["connector_args"]["encoding"], "base64")
                payload = base64.b64decode(item["connector_args"]["content"], validate=True)
                expected = subprocess.run(
                    ["git", "cat-file", "blob", item["expected_sha"]], cwd=root, check=True, stdout=subprocess.PIPE,
                ).stdout
                self.assertEqual(payload, expected)
                first_shas.append(item["expected_sha"])

            resumed = start_publish_model_dispatch(root, store, action_id=plan["action_id"])
            self.assertEqual(resumed["queue_digest"], first["queue_digest"])
            self.assertEqual(resumed["cursor"], 0)
            with self.assertRaisesRegex(RuntimeError, "SHA mismatch"):
                acknowledge_publish_model_dispatch_batch(
                    root, store, action_id=plan["action_id"], returned_shas=[first_shas[0], "0" * 40],
                )
            self.assertEqual(publish_model_dispatch_status(root, store, action_id=plan["action_id"])["cursor"], 0)

            view = acknowledge_publish_model_dispatch_batch(root, store, action_id=plan["action_id"], returned_shas=first_shas)
            self.assertEqual(view["cursor"], 2)
            while view["phase"] == "blob_batch":
                returned = [item["expected_sha"] for item in view["batch"]["items"]]
                view = acknowledge_publish_model_dispatch_batch(root, store, action_id=plan["action_id"], returned_shas=returned)

            self.assertEqual(view["phase"], "create_tree")
            self.assertEqual(view["cursor"], 5)
            self.assertEqual(view["expected_tree"], receipt["source_tree"])
            elements = view["connector_args"]["tree_elements"]
            self.assertEqual(len(elements), 6)
            deletion = next(item for item in elements if item["path"] == "tracked.txt")
            self.assertIsNone(deletion["sha"])
            for item in elements:
                self.assertNotIn("content", item)
            with self.assertRaisesRegex(RuntimeError, "target tree"):
                acknowledge_publish_model_dispatch_tree(root, store, action_id=plan["action_id"], returned_tree="f" * 40)
            commit = acknowledge_publish_model_dispatch_tree(
                root, store, action_id=plan["action_id"], returned_tree=receipt["source_tree"],
            )
            self.assertEqual(commit["phase"], "tree_verified")
            self.assertEqual(commit["commit_plan"]["tree_sha"], receipt["source_tree"])
            self.assertEqual(commit["commit_plan"]["parent_sha"], base)
            self.assertIn("do not blindly replay create_commit", commit["retry_rule"])

    def test_model_dispatch_rejects_wrong_transport_and_unstarted_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            store = make_store(root)
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "target")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="7" * 64, evidence="verified")
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            dispatch_publish(store, action_id=plan["action_id"], transport="git")
            with self.assertRaisesRegex(RuntimeError, "github_object_api"):
                start_publish_model_dispatch(root, store, action_id=plan["action_id"])

    def test_publish_plan_is_native_git_only_through_rdc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            base_tree = git(root, "rev-parse", "HEAD^{tree}")
            store = make_store(root)
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt")
            git(root, "commit", "-qm", "target")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(
                root, store, artifact_name="skill.zip", artifact_sha256="b" * 64, evidence="verified artifact",
            )
            git(root, "remote", "add", "origin", str(Path(tmp) / "unused.git"))
            plan = publish_plan(
                root, store, repository="owner/repo", branch="main", remote_head=base, remote_tree=base_tree,
                release_id=receipt["release_id"],
            )
            self.assertTrue(plan["ready"])
            self.assertEqual(plan["transport_order"], ["git"])
            self.assertEqual(plan["host_executor"], "remote_desktop_commander")
            self.assertIsNone(plan["fallback_transport"])
            self.assertTrue(plan["git"]["configured_remote"])
            self.assertTrue(plan["git"]["required"])
            self.assertNotIn("github_object_api", plan)
            self.assertIn("do not switch publish transport", plan["git"]["failure_rule"])
            self.assertEqual(store.external_action(plan["action_id"])["state"], "planned")

    def test_publish_plan_refuses_non_ancestor_remote_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            store = make_store(root)
            git(root, "checkout", "-qb", "target")
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "target")
            target = git(root, "rev-parse", "HEAD")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="c" * 64, evidence="verified")
            git(root, "checkout", "-qb", "remote", base)
            (root / "remote.txt").write_text("remote\n", encoding="utf-8")
            git(root, "add", "remote.txt"); git(root, "commit", "-qm", "remote")
            remote_head = git(root, "rev-parse", "HEAD")
            git(root, "checkout", "-q", "target")
            self.assertEqual(git(root, "rev-parse", "HEAD"), target)
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=remote_head, release_id=receipt["release_id"])
            self.assertFalse(plan["ready"])
            self.assertTrue(plan["requires_integration"])
            self.assertEqual(store.external_actions(), [])

    def test_publish_outcome_requires_tree_equality_and_git_commit_equality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            store = make_store(root)
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "target")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="d" * 64, evidence="verified")
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            dispatch_publish(store, action_id=plan["action_id"], transport="git")
            with self.assertRaisesRegex(RuntimeError, "remote tree"):
                record_publish_outcome(
                    root, store, action_id=plan["action_id"], state="terminal_success", transport="git",
                    remote_commit=receipt["source_commit"], remote_tree="e" * 40, evidence="remote observed",
                )
            result = record_publish_outcome(
                root, store, action_id=plan["action_id"], state="terminal_success", transport="git",
                remote_commit=receipt["source_commit"], remote_tree=receipt["source_tree"], evidence="remote ref and tree observed",
            )
            self.assertEqual(result["state"], "terminal_success")
            self.assertEqual(store.unresolved_external_count(), 0)

    def test_publish_requires_existing_validation_review_gates_without_new_parallel_audit_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            store = create_store(root)
            store.configure_task(store.path.parent.name, "publish audit", ["ready"], requires_validation=True)
            store.set_meta("workspace_binding", capture_workspace_binding(root))
            capture_baseline(root, store)
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "target")
            sync_generation(root, store)
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="9" * 64, evidence="verified")
            with self.assertRaisesRegex(RuntimeError, "passing validation"):
                publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            plan = store.create_validation_plan(store.generation(), ["pytest", "-q"], cwd=root)
            store.record_host_validation(plan["plan_id"], store.generation(), ["pytest", "-q"], 0, cwd=root, evidence="host pytest passed")
            with self.assertRaisesRegex(RuntimeError, "reviewed"):
                publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            store.mark_reviewed()
            out = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            self.assertTrue(out["ready"])

    def test_completion_blocks_replaced_repository_identity_for_bound_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            other = Path(tmp) / "other"
            root.mkdir(); other.mkdir()
            init_repo(root); init_repo(other)
            store = make_store(root)
            store.set_criterion(0, "pass", "fixture criterion observed")
            bad_binding = capture_workspace_binding(other)
            bad_binding["canonical_root"] = str(root.resolve())
            store.set_meta("workspace_binding", bad_binding)
            decision = assess(root, store)
            self.assertEqual(decision.status, CompletionStatus.BLOCKED)
            self.assertTrue(any("canonical workspace binding" in reason for reason in decision.reasons))

    def _stable_fixture(self, root: Path):
        base = init_repo(root)
        store = make_store(root)
        (root / "tracked.txt").write_text("target\n", encoding="utf-8")
        (root / "new.txt").write_text("new\n", encoding="utf-8")
        git(root, "add", "tracked.txt", "new.txt")
        git(root, "commit", "-qm", "stable target")
        sync_generation(root, store)
        store.mark_reviewed()
        receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="8" * 64, evidence="verified")
        plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
        dispatch_publish(store, action_id=plan["action_id"], transport="github_object_api")
        return base, store, receipt, plan

    def _drive_one_stable_path(self, root: Path, store, action_id: str, *, tree_sha: str, commit_sha: str):
        view = publish_stable_status(root, store, action_id=action_id)
        if view["phase"] == "path_blob":
            expected = view["ack_result"]["sha"]
            view = acknowledge_publish_stable(root, store, action_id=action_id, result={"sha": expected})
        self.assertEqual(view["phase"], "path_tree")
        view = acknowledge_publish_stable(root, store, action_id=action_id, result={"sha": tree_sha})
        self.assertEqual(view["phase"], "path_commit")
        view = acknowledge_publish_stable(root, store, action_id=action_id, result={"sha": commit_sha})
        self.assertEqual(view["phase"], "path_ref_update")
        view = acknowledge_publish_stable(root, store, action_id=action_id, result={"ok": True})
        self.assertEqual(view["phase"], "path_ref_readback")
        return acknowledge_publish_stable(root, store, action_id=action_id, result={"sha": commit_sha})

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_stable_publish_happy_path_uses_fixed_control_and_remote_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, store, receipt, plan = self._stable_fixture(root)
            self.assertTrue(plan["github_object_api"]["stable_dispatcher"]["available"])
            view = start_publish_stable(root, store, action_id=plan["action_id"])
            self.assertEqual(view["control"], "CONTINUE")
            self.assertEqual(view["phase"], "create_staging_branch")
            self.assertEqual(view["connector_args"]["sha"], base)
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"ok": True})
            self.assertEqual(view["phase"], "staging_branch_readback")
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": base})

            total = view["total_paths"]
            self.assertGreaterEqual(total, 1)
            for index in range(total):
                last = index == total - 1
                tree_sha = receipt["source_tree"] if last else (f"{index + 1:x}" * 40)[:40]
                commit_sha = (f"{index + 9:x}" * 40)[:40]
                view = self._drive_one_stable_path(root, store, plan["action_id"], tree_sha=tree_sha, commit_sha=commit_sha)
            self.assertEqual(view["phase"], "staging_verify")
            staging_head = view["ack_result"]["sha"]
            view = acknowledge_publish_stable(
                root, store, action_id=plan["action_id"], result={"sha": staging_head, "tree": receipt["source_tree"]},
            )
            self.assertEqual(view["phase"], "final_commit")
            final_commit = "d" * 40
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": final_commit})
            self.assertEqual(view["phase"], "target_ref_precondition")
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": base})
            self.assertEqual(view["phase"], "target_ref_update")
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"ok": True})
            self.assertEqual(view["phase"], "target_ref_readback")
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": final_commit})
            self.assertEqual(view["phase"], "final_commit_readback")
            out = acknowledge_publish_stable(
                root, store, action_id=plan["action_id"],
                result={"sha": final_commit, "tree": receipt["source_tree"], "parent": base},
            )
            self.assertEqual(out["control"], "COMPLETE")
            self.assertEqual(store.external_action(plan["action_id"])["state"], "terminal_success")
            self.assertTrue(out["publish"]["requires_local_reconciliation"])

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_stable_publish_status_is_replay_safe_and_blob_mismatch_does_not_advance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, store, _receipt, plan = self._stable_fixture(root)
            start_publish_stable(root, store, action_id=plan["action_id"])
            acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"ok": True})
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": base})
            self.assertEqual(view["phase"], "path_blob")
            replay = publish_stable_status(root, store, action_id=plan["action_id"])
            self.assertEqual(view["connector_args"], replay["connector_args"])
            with self.assertRaisesRegex(RuntimeError, "blob SHA mismatch"):
                acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": "f" * 40})
            after = publish_stable_status(root, store, action_id=plan["action_id"])
            self.assertEqual(after["phase"], "path_blob")
            self.assertEqual(after["cursor"], view["cursor"])

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_stable_publish_reconcile_advances_only_from_observed_checkpoint_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, store, _receipt, plan = self._stable_fixture(root)
            start_publish_stable(root, store, action_id=plan["action_id"])
            view = reconcile_publish_stable(root, store, action_id=plan["action_id"], observed_staging_head=base)
            self.assertIn(view["phase"], {"path_blob", "path_tree"})
            if view["phase"] == "path_blob":
                view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": view["ack_result"]["sha"]})
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": "a" * 40})
            pending = "b" * 40
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": pending})
            self.assertEqual(view["phase"], "path_ref_update")
            with self.assertRaisesRegex(RuntimeError, "unexpected head|mismatch"):
                reconcile_publish_stable(root, store, action_id=plan["action_id"], observed_staging_head="c" * 40)
            still_pending = publish_stable_status(root, store, action_id=plan["action_id"])
            self.assertEqual(still_pending["phase"], "path_ref_update")
            self.assertEqual(still_pending["cursor"], 0)
            recovered = reconcile_publish_stable(root, store, action_id=plan["action_id"], observed_staging_head=pending, observed_staging_tree="a" * 40)
            self.assertEqual(recovered["cursor"], 1)

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_stable_publish_final_tree_and_target_precondition_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, store, receipt, plan = self._stable_fixture(root)
            start_publish_stable(root, store, action_id=plan["action_id"])
            acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"ok": True})
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": base})
            total = view["total_paths"]
            for index in range(total):
                if view["phase"] == "path_blob":
                    view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": view["ack_result"]["sha"]})
                if index == total - 1:
                    with self.assertRaisesRegex(RuntimeError, "audited target tree"):
                        acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": "e" * 40})
                    view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": receipt["source_tree"]})
                else:
                    view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": (f"{index + 1:x}" * 40)[:40]})
                checkpoint = (f"{index + 8:x}" * 40)[:40]
                view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": checkpoint})
                view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"ok": True})
                view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": checkpoint})
            staging_head = view["ack_result"]["sha"]
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": staging_head, "tree": receipt["source_tree"]})
            final_commit = "d" * 40
            view = acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": final_commit})
            self.assertEqual(view["phase"], "target_ref_precondition")
            with self.assertRaisesRegex(RuntimeError, "moved since stable publish preflight"):
                acknowledge_publish_stable(root, store, action_id=plan["action_id"], result={"sha": "c" * 40})
            self.assertEqual(publish_stable_status(root, store, action_id=plan["action_id"])["phase"], "target_ref_precondition")

    def _portable_export_fixture(self, tmp: str):
        root = Path(tmp) / "repo"
        root.mkdir()
        base, store, receipt, plan = self._stable_fixture(root)
        receipt_file = Path(tmp) / "portable-receipt.json"
        self.assertTrue(plan["github_object_api"]["portable_stable_dispatcher"]["available"])
        self.assertFalse(plan["github_object_api"]["portable_stable_dispatcher"]["local_git_required_after_export"])
        exported = export_publish_stable_portable_receipt(
            root, store, action_id=plan["action_id"], output_file=receipt_file,
        )
        self.assertEqual(exported["target_tree"], receipt["source_tree"])
        self.assertTrue(receipt_file.exists())
        return root, base, store, receipt, plan, receipt_file

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_portable_stable_receipt_resumes_after_git_and_task_state_are_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, base, store, receipt, _plan, receipt_file = self._portable_export_fixture(tmp)
            base_tree = git(root, "rev-parse", f"{base}^{{tree}}")
            # Simulate a new execution sandbox: the original Git DB and task store are unavailable.
            git_dir = root / ".git"
            lost_git = root / ".git.lost"
            git_dir.rename(lost_git)

            view = start_publish_stable_portable(receipt_file=receipt_file)
            self.assertEqual(view["phase"], "target_observe")
            self.assertFalse(view["llm_contract"]["local_git_required_after_export"])
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": base},
            )
            self.assertEqual(view["phase"], "staging_observe")
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"not_found": True},
            )
            self.assertEqual(view["phase"], "create_staging")
            staging_branch = view["connector_args"]["branch_name"]
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"ok": True},
            )
            self.assertEqual(view["phase"], "staging_confirm")
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"],
                result={"sha": base, "tree": base_tree, "message": "base"},
            )
            self.assertIn(view["phase"], {"path_blob", "path_tree"})
            self.assertEqual(view["staging_branch"], staging_branch)

            # Drive exactly one path to a durable remote checkpoint.
            if view["phase"] == "path_blob":
                expected_blob = view["ack_result"]["sha"]
                view = acknowledge_publish_stable_portable(
                    receipt_file=receipt_file, token=view["token"], result={"sha": expected_blob},
                )
            self.assertEqual(view["phase"], "path_tree")
            first_tree = "a" * 40
            if view["cursor"] == view["total_paths"] - 1:
                first_tree = receipt["source_tree"]
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": first_tree},
            )
            self.assertEqual(view["phase"], "path_commit")
            checkpoint_message = view["connector_args"]["message"]
            checkpoint_commit = "b" * 40
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": checkpoint_commit},
            )
            self.assertEqual(view["phase"], "path_ref_update")
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"ok": True},
            )
            self.assertEqual(view["phase"], "path_ref_readback")
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"],
                result={"sha": checkpoint_commit, "tree": first_tree, "message": checkpoint_message},
            )
            self.assertEqual(view["cursor"], 1)

            # Lose every transient token and restart only from the immutable receipt + GitHub observation.
            restarted = start_publish_stable_portable(receipt_file=receipt_file)
            restarted = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=restarted["token"], result={"sha": base},
            )
            self.assertEqual(restarted["phase"], "staging_observe")
            restarted = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=restarted["token"],
                result={"sha": checkpoint_commit, "tree": first_tree, "message": checkpoint_message},
            )
            self.assertEqual(restarted["cursor"], 1)
            self.assertIn(restarted["phase"], {"path_blob", "path_tree", "target_recheck"})

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_portable_stable_happy_path_completes_without_runtime_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, base, _store, receipt, _plan, receipt_file = self._portable_export_fixture(tmp)
            base_tree = git(root, "rev-parse", f"{base}^{{tree}}")
            view = start_publish_stable_portable(receipt_file=receipt_file)
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": base},
            )
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"not_found": True},
            )
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"ok": True},
            )
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"],
                result={"sha": base, "tree": base_tree, "message": "base"},
            )

            total = view["total_paths"]
            for index in range(total):
                if view["phase"] == "path_blob":
                    view = acknowledge_publish_stable_portable(
                        receipt_file=receipt_file, token=view["token"], result={"sha": view["ack_result"]["sha"]},
                    )
                self.assertEqual(view["phase"], "path_tree")
                tree_sha = receipt["source_tree"] if index == total - 1 else (f"{index + 1:x}" * 40)[:40]
                view = acknowledge_publish_stable_portable(
                    receipt_file=receipt_file, token=view["token"], result={"sha": tree_sha},
                )
                checkpoint_message = view["connector_args"]["message"]
                checkpoint_commit = (f"{index + 8:x}" * 40)[:40]
                view = acknowledge_publish_stable_portable(
                    receipt_file=receipt_file, token=view["token"], result={"sha": checkpoint_commit},
                )
                view = acknowledge_publish_stable_portable(
                    receipt_file=receipt_file, token=view["token"], result={"ok": True},
                )
                view = acknowledge_publish_stable_portable(
                    receipt_file=receipt_file, token=view["token"],
                    result={"sha": checkpoint_commit, "tree": tree_sha, "message": checkpoint_message},
                )

            self.assertEqual(view["phase"], "target_recheck")
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": base},
            )
            self.assertEqual(view["phase"], "final_commit")
            final_commit = "f" * 40
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": final_commit},
            )
            self.assertEqual(view["phase"], "target_ref_update")
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"ok": True},
            )
            self.assertEqual(view["phase"], "target_ref_readback")
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": final_commit},
            )
            self.assertEqual(view["phase"], "final_commit_readback")
            done = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"],
                result={"sha": final_commit, "tree": receipt["source_tree"], "parent": base},
            )
            self.assertEqual(done["control"], "COMPLETE")
            self.assertEqual(done["remote_tree"], receipt["source_tree"])

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_portable_stable_receipt_detects_payload_and_digest_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            _root, _base, store, _receipt, _plan, receipt_file = self._portable_export_fixture(tmp)
            data = __import__("json").loads(receipt_file.read_text(encoding="utf-8"))
            first = next(item for item in data["items"] if not item["delete"])
            first["content_base64"] = base64.b64encode(b"tampered").decode("ascii")
            receipt_file.write_text(__import__("json").dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                start_publish_stable_portable(receipt_file=receipt_file)

    @unittest.skip("legacy connector publish transport is intentionally unsupported")
    def test_portable_stable_target_movement_only_accepts_exact_completed_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            _root, base, store, receipt, _plan, receipt_file = self._portable_export_fixture(tmp)
            moved = "c" * 40
            view = start_publish_stable_portable(receipt_file=receipt_file)
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": moved},
            )
            self.assertEqual(view["phase"], "target_existing_verify")
            done = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"],
                result={"sha": moved, "tree": receipt["source_tree"], "parent": base},
            )
            self.assertEqual(done["control"], "COMPLETE")
            self.assertTrue(done["already_published"])

            view = start_publish_stable_portable(receipt_file=receipt_file)
            view = acknowledge_publish_stable_portable(
                receipt_file=receipt_file, token=view["token"], result={"sha": moved},
            )
            with self.assertRaisesRegex(RuntimeError, "moved concurrently"):
                acknowledge_publish_stable_portable(
                    receipt_file=receipt_file, token=view["token"],
                    result={"sha": moved, "tree": "d" * 40, "parent": base},
                )

    def test_connector_publish_transport_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            store = make_store(root)
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "target")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="f" * 64, evidence="verified")
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            with self.assertRaisesRegex(ValueError, "native git only"):
                dispatch_publish(store, action_id=plan["action_id"], transport="github_object_api")

    def test_publish_plan_remote_tree_is_optional_for_native_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            store = make_store(root)
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "target")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="1" * 64, evidence="verified")
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            self.assertEqual(plan["transport_order"], ["git"])
            self.assertNotIn("github_object_api", plan)

    def test_publish_action_identity_is_commit_bound_even_when_tree_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            store = make_store(root)
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "target")
            first_commit = git(root, "rev-parse", "HEAD")
            first_tree = git(root, "rev-parse", "HEAD^{tree}")
            sync_generation(root, store)
            store.mark_reviewed()
            first_receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="2" * 64, evidence="verified first")
            first_plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=first_receipt["release_id"])

            git(root, "commit", "--allow-empty", "-qm", "metadata-only release commit")
            second_commit = git(root, "rev-parse", "HEAD")
            self.assertNotEqual(first_commit, second_commit)
            self.assertEqual(first_tree, git(root, "rev-parse", "HEAD^{tree}"))
            sync_generation(root, store)
            store.mark_reviewed()
            second_receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="3" * 64, evidence="verified second")
            second_plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=second_receipt["release_id"])

            self.assertNotEqual(first_plan["action_id"], second_plan["action_id"])
            self.assertTrue(store.external_action(first_plan["action_id"])["identity"].endswith(first_commit))
            self.assertTrue(store.external_action(second_plan["action_id"])["identity"].endswith(second_commit))

    def test_already_published_rejects_conflicting_remote_tree_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = init_repo(root)
            store = make_store(root)
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="4" * 64, evidence="verified")
            with self.assertRaisesRegex(RuntimeError, "conflicts with the audited target commit"):
                publish_plan(
                    root,
                    store,
                    repository="owner/repo",
                    branch="main",
                    remote_head=head,
                    remote_tree="f" * 40,
                    release_id=receipt["release_id"],
                )

    def test_native_git_publish_does_not_offer_connector_fallback_for_submodule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "main"
            subrepo = Path(tmp) / "subrepo"
            root.mkdir(); subrepo.mkdir()
            base = init_repo(root)
            init_repo(subrepo)
            store = make_store(root)
            git(root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(subrepo), "vendor/sub")
            git(root, "commit", "-qm", "add gitlink")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="5" * 64, evidence="verified")
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            self.assertEqual(plan["transport_order"], ["git"])
            self.assertNotIn("github_object_api", plan)
            with self.assertRaisesRegex(ValueError, "native git only"):
                dispatch_publish(store, action_id=plan["action_id"], transport="github_object_api")


if __name__ == "__main__":
    unittest.main()
