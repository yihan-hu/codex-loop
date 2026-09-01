import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.codex_loop_runtime.persistence import (
    build_state_manifest,
    cleanup_decision,
    persistence_policy,
    validate_state_manifest,
)
from scripts.codex_loop_runtime.state import StateStore


class PersistenceTests(unittest.TestCase):
    def make_store(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "state.sqlite3"
        store = StateStore(path)
        store.configure_task("a" * 32, "Recover this objective", ["Do the thing"], profile="feature", requires_validation=False, no_validation_reason="test")
        store.set_meta("workspace_binding", {"base_commit": "1" * 40, "base_tree": "2" * 40, "canonical_root": "/secret/path"})
        return tmp, store

    def test_default_policy_is_off_and_credentials_are_host_owned(self):
        policy = persistence_policy()
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["default_backend"], "off")
        self.assertEqual(policy["credentials_owner"], "host")

    def test_manifest_is_state_only_and_omits_local_path_and_raw_action_identity(self):
        tmp, store = self.make_store()
        self.addCleanup(tmp.cleanup)
        store.record_external("github_push", "planned", "https://signed.example/?token=secret", action_class="external_non_idempotent")
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        manifest = build_state_manifest(Path("/repo"), Path("/repo"), store, repository="owner/repo", now=now)
        text = str(manifest)
        self.assertNotIn("/secret/path", text)
        self.assertNotIn("signed.example", text)
        self.assertNotIn("token=secret", text)
        self.assertTrue(manifest["privacy"]["external_action_identity_is_hashed"])
        self.assertEqual(manifest["workspace"]["repository"], "owner/repo")
        self.assertEqual(manifest["expires_at"], "2026-10-01T00:00:00Z")
        validate_state_manifest(manifest)

    def test_cleanup_trashes_expired_clean_manifest_but_retains_unresolved_action(self):
        tmp, store = self.make_store()
        self.addCleanup(tmp.cleanup)
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        clean = build_state_manifest(Path("/repo"), Path("/repo"), store, ttl_days=1, now=now)
        later = now + timedelta(days=2)
        self.assertEqual(cleanup_decision(clean, now=later)["action"], "trash")
        action_id = store.record_external("upload", "planned", "opaque-id", action_class="external_non_idempotent")
        store.record_external("upload", "dispatched", "opaque-id", action_class="external_non_idempotent", action_id=action_id)
        store.record_external("upload", "outcome_unknown", "opaque-id", details={"observed": "ambiguous"}, action_class="external_non_idempotent", action_id=action_id)
        unresolved = build_state_manifest(Path("/repo"), Path("/repo"), store, ttl_days=1, now=now)
        self.assertEqual(cleanup_decision(unresolved, now=later)["action"], "retain_for_reconciliation")

    def test_validation_rejects_schema_extra_fields(self):
        tmp, store = self.make_store()
        self.addCleanup(tmp.cleanup)
        manifest = build_state_manifest(Path("/repo"), Path("/repo"), store)
        manifest["credential_blob"] = "must-not-pass"
        with self.assertRaises(ValueError):
            validate_state_manifest(manifest)

    def test_validation_rejects_forbidden_private_content_flags(self):
        tmp, store = self.make_store()
        self.addCleanup(tmp.cleanup)
        manifest = build_state_manifest(Path("/repo"), Path("/repo"), store)
        manifest["privacy"]["contains_credentials"] = True
        with self.assertRaises(ValueError):
            validate_state_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
