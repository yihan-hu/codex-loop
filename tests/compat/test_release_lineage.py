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
    capture_workspace_binding,
    classify_connector_manifest,
    current_release_receipt,
    diff_object_manifest,
    dispatch_publish,
    publish_model_dispatch_status,
    publish_plan,
    record_publish_outcome,
    record_release_receipt,
    release_plan,
    start_publish_model_dispatch,
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

    def test_publish_plan_prefers_git_and_builds_connector_manifest_from_remote_head(self):
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
                root,
                store,
                repository="owner/repo",
                branch="main",
                remote_head=base,
                remote_tree=base_tree,
                release_id=receipt["release_id"],
            )
            self.assertTrue(plan["ready"])
            self.assertEqual(plan["transport_order"], ["git", "github_object_api"])
            self.assertTrue(plan["git"]["configured_remote"])
            self.assertEqual(plan["github_object_api"]["base_tree"], base_tree)
            self.assertEqual(plan["github_object_api"]["base_tree_source"], "observed_remote")
            self.assertFalse(plan["github_object_api"]["requires_remote_tree"])
            self.assertTrue(plan["github_object_api"]["available"])
            self.assertEqual(plan["github_object_api"]["target_tree"], receipt["source_tree"])
            self.assertEqual([x["path"] for x in plan["github_object_api"]["changed_objects"]], ["tracked.txt"])
            self.assertEqual(plan["github_object_api"]["changed_objects"][0]["transfer"], "inline_utf8")
            self.assertEqual(plan["github_object_api"]["transfer_summary"]["inline_utf8"]["count"], 1)
            self.assertEqual(plan["github_object_api"]["transfer_summary"]["create_blob"]["count"], 0)
            self.assertTrue(plan["github_object_api"]["model_dispatcher"]["available"])
            self.assertEqual(plan["github_object_api"]["model_dispatcher"]["batch_max_items"], MODEL_DISPATCH_BATCH_MAX_ITEMS)
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

    def test_connector_transport_may_create_different_commit_only_when_tree_matches(self):
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
            dispatch_publish(store, action_id=plan["action_id"], transport="github_object_api")
            result = record_publish_outcome(
                root, store, action_id=plan["action_id"], state="terminal_success", transport="github_object_api",
                remote_commit="1" * 40, remote_tree=receipt["source_tree"], remote_parent=base,
                evidence="connector readback matched target tree and planned parent",
            )
            self.assertEqual(result["remote_tree"], receipt["source_tree"])
            self.assertNotEqual(result["remote_commit"], receipt["source_commit"])
            self.assertTrue(result["requires_local_reconciliation"])

    def test_publish_plan_uses_local_remote_commit_tree_when_remote_tree_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = init_repo(root)
            base_tree = git(root, "rev-parse", "HEAD^{tree}")
            store = make_store(root)
            (root / "tracked.txt").write_text("target\n", encoding="utf-8")
            git(root, "add", "tracked.txt"); git(root, "commit", "-qm", "target")
            sync_generation(root, store)
            store.mark_reviewed()
            receipt = record_release_receipt(root, store, artifact_name="skill.zip", artifact_sha256="1" * 64, evidence="verified")
            plan = publish_plan(root, store, repository="owner/repo", branch="main", remote_head=base, release_id=receipt["release_id"])
            self.assertEqual(plan["github_object_api"]["base_tree"], base_tree)
            self.assertEqual(plan["github_object_api"]["base_tree_source"], "local_remote_head_commit")
            self.assertFalse(plan["github_object_api"]["requires_remote_tree"])

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

    def test_connector_fallback_refuses_submodule_object_manifest(self):
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
            self.assertFalse(plan["github_object_api"]["available"])
            self.assertEqual(plan["github_object_api"]["unsupported_paths"], ["vendor/sub"])
            with self.assertRaisesRegex(RuntimeError, "fallback is unavailable"):
                dispatch_publish(store, action_id=plan["action_id"], transport="github_object_api")


if __name__ == "__main__":
    unittest.main()
