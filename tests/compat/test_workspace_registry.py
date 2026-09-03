import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"


def call(home: Path, tmpdir: Path, *args: str, check: bool = True):
    env = os.environ.copy()
    env["CODEX_LOOP_HOME"] = str(home)
    env["TMPDIR"] = str(tmpdir)
    proc = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    if check and proc.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout={proc.stdout}\nstderr={proc.stderr}")
    return payload, proc


class WorkspaceRegistryTests(unittest.TestCase):
    def test_known_granted_and_host_authorized_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            session_tmp = root / "tmp"
            session_tmp.mkdir()
            repo = root / "EpiAgent"
            repo.mkdir()

            registered, _ = call(
                home,
                session_tmp,
                "workspace-register",
                "--name",
                " EpiAgent ",
                "--path",
                str(repo),
                "--kind",
                "repository",
            )
            self.assertEqual(registered["data"]["name"], "epiagent")
            self.assertFalse(registered["data"]["granted"])

            registry = json.loads((home / "workspace-registry.json").read_text())
            self.assertEqual(set(registry), {"version", "workspaces"})
            self.assertEqual(set(registry["workspaces"]["epiagent"]), {"path", "kind"})
            self.assertNotIn("authorized", (home / "workspace-registry.json").read_text().lower())

            known, _ = call(
                home,
                session_tmp,
                "workspace-resolve",
                "EPIAGENT",
                "--host-authorized-root",
                str(repo),
            )
            self.assertTrue(known["data"]["registered"])
            self.assertFalse(known["data"]["granted"])
            self.assertTrue(known["data"]["host_authorized"])
            self.assertFalse(known["data"]["accessible"])

            granted, _ = call(
                home,
                session_tmp,
                "workspace-grant",
                "epiagent",
                "--authorization-evidence",
                "user explicitly granted EpiAgent path access in this conversation",
                "--current-user-authorization-observed",
            )
            session_id = granted["data"]["session_id"]
            self.assertTrue(granted["data"]["granted"])

            access, _ = call(
                home,
                session_tmp,
                "workspace-resolve",
                "epiagent",
                "--session-id",
                session_id,
                "--host-authorized-root",
                str(repo),
                "--require-access",
            )
            self.assertTrue(access["data"]["accessible"])

            new_conversation, _ = call(
                home,
                session_tmp,
                "workspace-resolve",
                "epiagent",
                "--session-id",
                "different-conversation-0001",
                "--host-authorized-root",
                str(repo),
            )
            self.assertFalse(new_conversation["data"]["granted"])
            self.assertFalse(new_conversation["data"]["accessible"])

    def test_grant_requires_explicit_authorization_evidence_and_does_not_store_raw_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            session_tmp = root / "tmp"
            session_tmp.mkdir()
            repo = root / "repo"
            repo.mkdir()
            call(home, session_tmp, "workspace-register", "--name", "repo", "--path", str(repo), "--kind", "repository")

            failed, proc = call(
                home,
                session_tmp,
                "workspace-grant",
                "repo",
                "--authorization-evidence",
                "",
                "--current-user-authorization-observed",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(failed["ok"])
            self.assertIn("explicit authorization evidence", failed["error"]["message"])

            evidence = "EXPLICIT-USER-GRANT-RAW-TEXT"
            granted, _ = call(home, session_tmp, "workspace-grant", "repo", "--authorization-evidence", evidence, "--current-user-authorization-observed")
            session_id = granted["data"]["session_id"]
            files = list((session_tmp / "codex-loop" / "workspace-sessions").glob("*.json"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertNotIn(evidence, text)
            self.assertNotIn(str(repo), text)
            grants, _ = call(home, session_tmp, "workspace-grants", "--session-id", session_id)
            self.assertEqual(grants["data"]["granted"], ["repo"])

    def test_grant_evidence_alone_cannot_mint_conversation_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            session_tmp = root / "tmp"
            session_tmp.mkdir()
            repo = root / "repo"
            repo.mkdir()
            call(home, session_tmp, "workspace-register", "--name", "repo", "--path", str(repo), "--kind", "repository")
            failed, proc = call(
                home, session_tmp, "workspace-grant", "repo",
                "--authorization-evidence", "project history says this path was allowed",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(failed["ok"])
            self.assertIn("host-observed explicit current-conversation", failed["error"]["message"])

    def test_registry_update_invalidates_existing_session_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            session_tmp = root / "tmp"
            session_tmp.mkdir()
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            call(home, session_tmp, "workspace-register", "--name", "epiagent", "--path", str(first), "--kind", "repository")
            granted, _ = call(home, session_tmp, "workspace-grant", "epiagent", "--authorization-evidence", "explicit user grant", "--current-user-authorization-observed")
            session_id = granted["data"]["session_id"]

            call(
                home,
                session_tmp,
                "workspace-register",
                "--name",
                "EpiAgent",
                "--path",
                str(second),
                "--kind",
                "repository",
                "--update",
            )
            grants, _ = call(home, session_tmp, "workspace-grants", "--session-id", session_id)
            self.assertEqual(grants["data"]["granted"], [])
            self.assertEqual(grants["data"]["stale"], ["epiagent"])
            resolved, _ = call(
                home,
                session_tmp,
                "workspace-resolve",
                "epiagent",
                "--session-id",
                session_id,
                "--host-authorized-root",
                str(second),
            )
            self.assertFalse(resolved["data"]["granted"])
            self.assertIn("session_grant_stale_registry_changed", resolved["data"]["reasons"])

    def test_missing_path_and_symlinked_registry_path_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            session_tmp = root / "tmp"
            session_tmp.mkdir()
            parent = root / "projects"
            parent.mkdir()
            repo = parent / "repo"
            repo.mkdir()
            call(home, session_tmp, "workspace-register", "--name", "repo", "--path", str(repo), "--kind", "repository")
            granted, _ = call(home, session_tmp, "workspace-grant", "repo", "--authorization-evidence", "explicit user grant", "--current-user-authorization-observed")
            session_id = granted["data"]["session_id"]
            repo.rmdir()

            missing, _ = call(
                home,
                session_tmp,
                "workspace-resolve",
                "repo",
                "--session-id",
                session_id,
                "--host-authorized-root",
                str(parent),
            )
            self.assertFalse(missing["data"]["path_valid"])
            self.assertIn("registered_path_missing", missing["data"]["reasons"])
            denied, proc = call(
                home,
                session_tmp,
                "workspace-resolve",
                "repo",
                "--session-id",
                session_id,
                "--host-authorized-root",
                str(parent),
                "--require-access",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(denied["ok"])

            outside = root / "outside"
            outside.mkdir()
            link = parent / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            registry_path = home / "workspace-registry.json"
            registry = json.loads(registry_path.read_text())
            registry["workspaces"]["repo"]["path"] = str(link)
            registry_path.write_text(json.dumps(registry))
            symlinked, _ = call(home, session_tmp, "workspace-resolve", "repo")
            self.assertFalse(symlinked["data"]["path_valid"])
            self.assertIn("registered_realpath_changed_or_symlinked", symlinked["data"]["reasons"])

    def test_host_denial_and_sibling_grants_do_not_broaden_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            session_tmp = root / "tmp"
            session_tmp.mkdir()
            projects = root / "projects"
            projects.mkdir()
            a = projects / "a"
            b = projects / "b"
            other = root / "other"
            a.mkdir()
            b.mkdir()
            other.mkdir()
            call(home, session_tmp, "workspace-register", "--name", "a", "--path", str(a), "--kind", "repository")
            call(home, session_tmp, "workspace-register", "--name", "b", "--path", str(b), "--kind", "repository")
            granted, _ = call(home, session_tmp, "workspace-grant", "a", "--authorization-evidence", "explicit user grant", "--current-user-authorization-observed")
            session_id = granted["data"]["session_id"]

            denied, _ = call(home, session_tmp, "workspace-resolve", "a", "--session-id", session_id, "--host-authorized-root", str(other))
            self.assertTrue(denied["data"]["granted"])
            self.assertFalse(denied["data"]["host_authorized"])
            self.assertFalse(denied["data"]["accessible"])

            sibling, _ = call(home, session_tmp, "workspace-resolve", "b", "--session-id", session_id, "--host-authorized-root", str(projects))
            self.assertFalse(sibling["data"]["granted"])
            self.assertFalse(sibling["data"]["accessible"])

            parent, _ = call(home, session_tmp, "workspace-resolve", "a", "--session-id", session_id, "--host-authorized-root", str(projects))
            self.assertTrue(parent["data"]["accessible"])

    def test_alias_conflict_relative_path_and_corrupt_registry_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            session_tmp = root / "tmp"
            session_tmp.mkdir()
            repo = root / "repo"
            repo.mkdir()
            call(home, session_tmp, "workspace-register", "--name", "EpiAgent", "--path", str(repo), "--kind", "repository")

            conflict, proc = call(
                home,
                session_tmp,
                "workspace-register",
                "--name",
                "epiagent",
                "--path",
                str(repo),
                "--kind",
                "repository",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("already registered", conflict["error"]["message"])

            relative, proc = call(
                home,
                session_tmp,
                "workspace-register",
                "--name",
                "relative",
                "--path",
                "../repo",
                "--kind",
                "repository",
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("absolute", relative["error"]["message"])

            registry_path = home / "workspace-registry.json"
            registry_path.write_text("{not-json")
            corrupt, proc = call(home, session_tmp, "workspace-registry-list", check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("was not reset", corrupt["error"]["message"])
            self.assertEqual(registry_path.read_text(), "{not-json")

    def test_development_root_and_repository_can_both_be_granted_in_one_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            session_tmp = root / "tmp"
            session_tmp.mkdir()
            piwork = root / "PiWork"
            epiagent = root / "EpiAgent"
            piwork.mkdir()
            epiagent.mkdir()
            call(home, session_tmp, "workspace-register", "--name", "PiWork", "--path", str(piwork), "--kind", "development_root")
            call(home, session_tmp, "workspace-register", "--name", "EpiAgent", "--path", str(epiagent), "--kind", "repository")
            listed, _ = call(home, session_tmp, "workspace-registry-list")
            kinds = {item["name"]: item["kind"] for item in listed["data"]["workspaces"]}
            self.assertEqual(kinds, {"epiagent": "repository", "piwork": "development_root"})
            self.assertFalse(listed["data"]["authorization_persisted"])

            first, _ = call(home, session_tmp, "workspace-grant", "piwork", "--authorization-evidence", "explicit user grant", "--current-user-authorization-observed")
            session_id = first["data"]["session_id"]
            call(home, session_tmp, "workspace-grant", "epiagent", "--session-id", session_id, "--authorization-evidence", "explicit user grant", "--current-user-authorization-observed")
            grants, _ = call(home, session_tmp, "workspace-grants", "--session-id", session_id)
            self.assertEqual(grants["data"]["granted"], ["epiagent", "piwork"])

            removed, _ = call(home, session_tmp, "workspace-remove", "PIWORK")
            self.assertTrue(removed["data"]["removed"])
            grants, _ = call(home, session_tmp, "workspace-grants", "--session-id", session_id)
            self.assertEqual(grants["data"]["granted"], ["epiagent"])
            self.assertEqual(grants["data"]["stale"], ["piwork"])

    def test_contract_docs_keep_known_granted_bound_and_rdc_layers_separate(self):
        skill = (ROOT / "SKILL.md").read_text()
        readme = (ROOT / "README.md").read_text()
        setup = (ROOT / "references" / "local-mode-setup.md").read_text()
        boundary = (ROOT / "references" / "remote-desktop-boundary.md").read_text()
        registry = (ROOT / "references" / "workspace-registry.md").read_text()
        protocol = (ROOT / "references" / "runtime-protocol.md").read_text()

        self.assertIn("KNOWN, not GRANTED", skill)
        self.assertIn("KNOWN != GRANTED", registry)
        self.assertIn("GRANTED != BOUND", registry)
        self.assertIn("Primary Local Root + Session Granted Roots = Effective Local Roots", setup)
        self.assertIn("REGISTERED + GRANTED THIS CONVERSATION + HOST/RDC AUTHORIZED = ACCESSIBLE", boundary)
        self.assertIn("workspace-registry.json", readme)
        self.assertIn("workspace-grant epiagent", protocol)
        self.assertIn("never stores authorization", registry)
        self.assertIn("never search the whole home directory or disk", boundary)


if __name__ == "__main__":
    unittest.main()
