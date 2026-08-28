import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
CLI = SKILL / "scripts" / "codex_loop.py"
sys.path.insert(0, str(SKILL / "scripts"))

from codex_loop_runtime.completion import _objective_audit_state, record_objective_audit
from codex_loop_runtime.state import create_store


def call(root, *args, check=True):
    parts = list(args)
    if "--cwd" not in parts:
        parts = [parts[0], "--cwd", str(root), *parts[1:]]
    proc = subprocess.run(
        [sys.executable, str(CLI), *parts],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )
    return json.loads(proc.stdout or b"{}"), proc


def proven(requirement="finish the requested objective", evidence="authoritative state proves completion"):
    return {
        "requirements": [
            {
                "requirement": requirement,
                "status": "proven",
                "evidence": evidence,
                "authoritative_source": "current authoritative test fixture state",
            }
        ]
    }


class ObjectiveCompletionAuditTests(unittest.TestCase):
    def make_store(self, root, objective="finish the requested objective"):
        store = create_store(root)
        store.configure_task(
            store.path.parent.name,
            objective,
            ["working criterion is satisfied"],
            requires_validation=False,
            no_validation_reason="fixture has no meaningful executable validation",
        )
        store.set_meta("requires_objective_completion_audit", True)
        return store

    def test_cli_working_criteria_pass_is_not_objective_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            call(
                root,
                "bootstrap",
                "--objective",
                "finish the requested objective",
                "--criterion",
                "working criterion is satisfied",
                "--no-validation",
                "--no-validation-reason",
                "fixture has no meaningful executable validation",
            )
            call(
                root,
                "criterion",
                "--index",
                "0",
                "--status",
                "pass",
                "--evidence",
                "working criterion observed satisfied",
            )
            done, _ = call(root, "completion")
            self.assertEqual(done["data"]["status"], "CONTINUE")
            audit = done["data"]["details"]["objective_audit"]
            self.assertTrue(audit["required"])
            self.assertFalse(audit["present"])

    def test_named_workflow_without_completion_evidence_is_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(
                Path(tmp),
                "Use Codex Loop and Epi Prose grant workflow to produce the requested section",
            )
            record_objective_audit(
                store,
                {
                    "requirements": [
                        {
                            "requirement": "Use Epi Prose grant workflow to its required end state",
                            "status": "missing",
                            "evidence": "",
                            "authoritative_source": "",
                        },
                        {
                            "requirement": "produce the requested section",
                            "status": "proven",
                            "evidence": "requested section exists",
                            "authoritative_source": "current deliverable",
                        },
                    ]
                },
            )
            audit = _objective_audit_state(store, store.generation())
            self.assertFalse(audit["pass"])
            self.assertEqual(audit["unresolved"][0]["status"], "missing")

    def test_all_proven_audit_passes_and_is_bound_to_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            record_objective_audit(store, proven())
            self.assertTrue(_objective_audit_state(store, 0)["pass"])
            store.bump_generation()
            audit = _objective_audit_state(store, 1)
            self.assertFalse(audit["fresh"])
            self.assertIn("stale for generation", " ".join(audit["reasons"]))

    def test_later_user_steer_stales_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            record_objective_audit(store, proven())
            store.record_steer("also preserve the public API")
            audit = _objective_audit_state(store, store.generation())
            self.assertFalse(audit["fresh"])
            self.assertIn("plan revision", " ".join(audit["reasons"]))

    def test_proven_item_requires_authoritative_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self.make_store(Path(tmp))
            payload = proven()
            payload["requirements"][0]["authoritative_source"] = ""
            with self.assertRaisesRegex(ValueError, "authoritative source"):
                record_objective_audit(store, payload)


if __name__ == "__main__":
    unittest.main()
