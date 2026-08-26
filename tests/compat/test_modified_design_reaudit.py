import contextlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
CLI = SKILL / "scripts" / "codex_loop.py"
sys.path.insert(0, str(SKILL / "scripts"))

from codex_loop_runtime.change_tracker import capture_baseline, sync_generation
from codex_loop_runtime.completion import CompletionStatus, assess
from codex_loop_runtime.shell import DetectedShell, ShellType
from codex_loop_runtime.shell_snapshot import capture_plan
from codex_loop_runtime.state import create_store
from codex_loop_runtime.workspace import hash_file
from codex_loop_runtime.write_transaction import guarded_write

NO_VALIDATION = "test fixture has no meaningful executable validation"

def host_validation(store, argv, exit_code, *, cwd, evidence):
    plan=store.create_validation_plan(store.generation(),argv,cwd=cwd)
    return store.record_host_validation(plan["plan_id"],store.generation(),argv,exit_code,cwd=cwd,evidence=evidence)


def call(*args, check=True):
    p = subprocess.run([sys.executable, str(CLI), *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)
    return json.loads(p.stdout or b"{}"), p


class ModifiedDesignReauditTests(unittest.TestCase):
    def make(self, root: Path, *, requires_validation=False):
        store = create_store(root)
        store.configure_task(
            store.path.parent.name,
            "objective",
            [],
            requires_validation=requires_validation,
            no_validation_reason=None if requires_validation else NO_VALIDATION,
        )
        capture_baseline(root, store)
        return store

    def test_criterion_and_steer_evidence_stale_after_workspace_generation_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "a.txt").write_text("one")
            store = self.make(root)
            store.set_criterion(0, "pass", "a.txt contains one")
            steer = store.record_steer("keep a.txt equal to one")
            store.ack_steer(steer, "current workspace preserves one")
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)
            digest = hash_file(root / "a.txt")
            guarded_write(
                root, store, root / "a.txt", b"two",
                expected_sha256=digest, allow_protected=True,
                protected_override_reason="test intentionally changes the protected baseline file",
            )
            store.mark_reviewed()
            decision = assess(root, store)
            self.assertEqual(decision.status, CompletionStatus.CONTINUE)
            self.assertTrue(any("criterion 0 evidence is stale" in x for x in decision.reasons))
            self.assertTrue(any("steers" in x and "stale" in x for x in decision.reasons))
            store.set_criterion(0, "pass", "a.txt now intentionally contains two")
            store.ack_steer(steer, "steer was re-evaluated after the intentional change")
            store.mark_reviewed()
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_reverted_workspace_change_does_not_require_final_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            target = root / "a.txt"
            target.write_text("base")
            store = self.make(root)
            digest = hash_file(target)
            guarded_write(
                root, store, target, b"changed", expected_sha256=digest,
                allow_protected=True,
                protected_override_reason="test intentionally changes the protected baseline file",
            )
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)
            digest = hash_file(target)
            guarded_write(
                root, store, target, b"base", expected_sha256=digest,
                allow_protected=True,
                protected_override_reason="test intentionally restores the protected baseline file",
            )
            store.set_criterion(0, "pass", "current workspace is back at the observed baseline")
            decision = assess(root, store)
            self.assertEqual(decision.status, CompletionStatus.PASS)
            self.assertFalse(any("reviewed" in reason for reason in decision.reasons))

    def test_validation_identity_includes_actual_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            a = root / "a"; b = root / "b"; a.mkdir(); b.mkdir()
            store = self.make(root, requires_validation=True)
            host_validation(store, ["pytest", "-q"], 0, cwd=a, evidence="a passed")
            host_validation(store, ["pytest", "-q"], 0, cwd=b, evidence="b passed")
            state = store.validation_state_for_generation(0)
            self.assertEqual(len(state["commands"]), 2)
            self.assertEqual({x["cwd"] for x in state["commands"]}, {str(a.resolve()), str(b.resolve())})

    def test_cli_local_validation_runs_in_requested_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            sub = root / "package"; sub.mkdir()
            boot, _ = call("bootstrap", "--cwd", root, "--objective", "validate cwd")
            tid = boot["data"]["task_id"]
            out, _ = call("validate", "--cwd", sub, "--task-id", tid, "--", "pwd")
            self.assertTrue(out["data"]["executed"])
            self.assertIn(str(sub.resolve()), out["data"]["result"]["stdout"])
            self.assertEqual(out["data"]["validation"]["cwd"], str(sub.resolve()))

    def test_legacy_validation_without_cwd_is_not_fresh_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root, requires_validation=True)
            with contextlib.closing(sqlite3.connect(store.path)) as db, db:
                db.execute(
                    "INSERT INTO validations(generation,command_json,cwd,exit_code,passed,source,evidence) VALUES(?,?,?,?,?,?,?)",
                    (0, json.dumps({"argv0": "pytest", "argc": 1, "sha256": "legacy"}), "", 0, 1, "host_observed", "legacy pass"),
                )
            store.set_criterion(0, "pass", "objective satisfied")
            decision = assess(root, store)
            self.assertEqual(decision.status, CompletionStatus.CONTINUE)
            self.assertTrue(any("lack cwd-aware identity" in reason for reason in decision.reasons))
            host_validation(store, ["pytest"], 0, cwd=root, evidence="rerun from known cwd")
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_no_validation_requires_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root)
            with self.assertRaisesRegex(ValueError, "disabling validation requires"):
                store.configure_task(store.path.parent.name, "objective", [], requires_validation=False)

    def test_protected_override_requires_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            target = root / "user.txt"; target.write_text("user")
            store = self.make(root)
            digest = hash_file(target)
            with self.assertRaisesRegex(ValueError, "requires a concise reason"):
                guarded_write(root, store, target, b"agent", expected_sha256=digest, allow_protected=True)
            guarded_write(
                root, store, target, b"agent", expected_sha256=digest, allow_protected=True,
                protected_override_reason="user explicitly requested modifying the preexisting file",
            )
            self.assertEqual(store.mutations()[-1]["override_reason"], "user explicitly requested modifying the preexisting file")

    def test_non_idempotent_external_identity_deduplicates_and_requires_dispatch_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            first = store.record_external("github_comment", "planned", "issue:1", action_class="external_non_idempotent")
            second = store.record_external("github_comment", "planned", "issue:1", action_class="external_non_idempotent")
            self.assertEqual(first, second)
            with self.assertRaisesRegex(ValueError, "advance it with --action-id"):
                store.record_external("github_comment", "terminal_success", "issue:1", {"observed": "present"}, action_class="external_non_idempotent")
            store.record_external("github_comment", "dispatched", "issue:1", action_class="external_non_idempotent", action_id=first)
            store.record_external("github_comment", "terminal_success", "issue:1", {"observed": "present"}, action_class="external_non_idempotent", action_id=first)

    def test_cli_external_dedup_reports_persisted_state_not_requested_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            boot, _ = call(
                "bootstrap", "--cwd", root, "--objective", "external bookkeeping",
                "--no-validation", "--no-validation-reason", NO_VALIDATION,
            )
            tid = boot["data"]["task_id"]
            planned, _ = call(
                "external", "--cwd", root, "--task-id", tid,
                "--kind", "github_comment", "--state", "planned",
                "--action-class", "external_non_idempotent", "--identity", "issue:1",
            )
            aid = planned["data"]["action_id"]
            call(
                "external", "--cwd", root, "--task-id", tid,
                "--kind", "github_comment", "--state", "dispatched",
                "--action-class", "external_non_idempotent", "--identity", "issue:1",
                "--action-id", aid,
            )
            call(
                "external", "--cwd", root, "--task-id", tid,
                "--kind", "github_comment", "--state", "terminal_success",
                "--action-class", "external_non_idempotent", "--identity", "issue:1",
                "--action-id", aid, "--details-json", '{"observed":"present"}',
            )
            dedup, _ = call(
                "external", "--cwd", root, "--task-id", tid,
                "--kind", "github_comment", "--state", "planned",
                "--action-class", "external_non_idempotent", "--identity", "issue:1",
            )
            self.assertEqual(dedup["data"]["action_id"], aid)
            self.assertEqual(dedup["data"]["state"], "terminal_success")
            self.assertEqual(dedup["data"]["requested_state"], "planned")
            self.assertTrue(dedup["data"]["deduplicated"])

    def test_legacy_duplicate_non_idempotent_identity_remains_openable_but_blocks_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            with contextlib.closing(sqlite3.connect(store.path)) as db, db:
                db.execute(
                    "INSERT INTO external_actions(action_id,kind,identity,action_class,state) VALUES(?,?,?,?,?)",
                    ("legacy_a", "github_comment", "issue:1", "external_non_idempotent", "terminal_success"),
                )
                db.execute(
                    "INSERT INTO external_actions(action_id,kind,identity,action_class,state) VALUES(?,?,?,?,?)",
                    ("legacy_b", "github_comment", "issue:1", "external_non_idempotent", "terminal_success"),
                )
            reopened = type(store)(store.path)
            reopened.set_criterion(0, "pass", "objective satisfied")
            decision = assess(root, reopened)
            self.assertEqual(decision.status, CompletionStatus.BLOCKED)
            self.assertEqual(reopened.ambiguous_non_idempotent_identity_count(), 1)
            with self.assertRaisesRegex(RuntimeError, "multiple non-idempotent actions"):
                reopened.record_external(
                    "github_comment", "planned", "issue:1", action_class="external_non_idempotent"
                )

    def test_git_authorization_is_scope_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "a").write_text("a"); subprocess.run(["git", "add", "a"], cwd=root, check=True)
            store = self.make(root)
            (root / "b").write_text("b"); subprocess.run(["git", "add", "b"], cwd=root, check=True)
            first = assess(root, store)
            self.assertEqual(first.status, CompletionStatus.BLOCKED)
            store.set_criterion(0, "pass", "objective rechecked after index update")
            store.mark_reviewed()
            store.authorize_git_mutation("user requested staging this file", index=True)
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_failed_process_blocks_completion_until_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            store.set_criterion(0, "pass", "objective satisfied")
            store.upsert_process("p1", 123, ["echo", "x"], str(root), "failed", 0, "PTY read failed")
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)
            store.resolve_orphaned_process("p1", "host confirmed process exited and no output remains")
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_shell_snapshot_plan_carries_upstream_capture_and_validation_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = capture_plan(Path(tmp), DetectedShell(ShellType.BASH, Path("/bin/bash")))
            self.assertTrue(plan["capture"]["login_shell"])
            self.assertEqual(plan["capture"]["timeout_seconds"], 10)
            self.assertEqual(plan["normalize"]["start_marker"], "# Snapshot file")
            self.assertFalse(plan["validate"]["login_shell"])
            self.assertFalse(plan["storage"]["model_visible"])


if __name__ == "__main__":
    unittest.main()
