import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "skills" / "codex-loop-install"
VALIDATOR = INSTALLER / "scripts" / "validate_handoff.py"


class FixedInstallerTests(unittest.TestCase):
    def make_package(self, root: Path, *, commit: str, tree: str) -> tuple[Path, str]:
        package = root / "skill.zip"
        manifest = {
            "schema_version": 2,
            "skill_name": "codex-loop",
            "distribution": {"profile": "maintainer", "repository_binding": "provenance_only"},
            "bundle": {"profile": "chatgpt-runtime", "file_count": 1, "manifest_sha256": "0" * 64},
            "source": {"repository": "yihan-hu/codex-loop", "commit": commit, "tree": tree},
        }
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("codex-loop/SKILL.md", "---\nname: codex-loop\ndescription: test\n---\n")
            archive.writestr("codex-loop/references/deployment-manifest.json", json.dumps(manifest))
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        return package, digest

    def make_handoff(self, root: Path, *, commit: str, tree: str, digest: str) -> Path:
        path = root / "handoff.json"
        path.write_text(json.dumps({
            "version": 1,
            "installer_skill": "codex-loop-install",
            "skill_name": "codex-loop",
            "repository": "yihan-hu/codex-loop",
            "source_state": "SOURCE_PUSHED",
            "deployment_target": "chatgpt_web_skill",
            "source_commit": commit,
            "source_tree": tree,
            "package_sha256": digest,
        }), encoding="utf-8")
        return path

    def run_validator(self, handoff: Path, package: Path):
        proc = subprocess.run(
            [sys.executable, str(VALIDATOR), "--handoff", str(handoff), "--package", str(package)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return proc, json.loads(proc.stdout)

    def test_installer_is_fixed_narrowly_implicit_and_handoff_validated(self):
        skill = (INSTALLER / "SKILL.md").read_text(encoding="utf-8")
        metadata = (INSTALLER / "agents" / "openai.yaml").read_text(encoding="utf-8")
        contract = (INSTALLER / "references" / "handoff-contract.md").read_text(encoding="utf-8")
        self.assertIn("name: codex-loop-install", skill)
        self.assertIn("fixed terminal installer", skill.lower())
        self.assertIn("Never install a Skill whose name is not exactly `codex-loop`", skill)
        self.assertIn("allow_implicit_invocation: true", metadata)
        self.assertIn('"repository": "yihan-hu/codex-loop"', contract)
        self.assertIn('"package_sha256"', contract)
        self.assertIn("install, update, or reinstall Codex Loop", skill)
        self.assertIn("present that exact package through the host-native Skill update surface", skill)
        self.assertIn("Do not invoke Codex Loop and do not edit, repackage, rename, or substitute the canonical package", skill)
        self.assertIn("Do not substitute a sandbox/download link", skill)
        self.assertIn("Generic Skill installation must not route to this installer", contract)

    def test_validator_accepts_exact_bound_package(self):
        commit = "a" * 40
        tree = "b" * 40
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package, digest = self.make_package(root, commit=commit, tree=tree)
            handoff = self.make_handoff(root, commit=commit, tree=tree, digest=digest)
            proc, payload = self.run_validator(handoff, package)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["source_commit"], commit)
            self.assertEqual(payload["source_tree"], tree)
            self.assertEqual(payload["package_sha256"], digest)
            self.assertEqual(payload["installer_invocation_mode"], "implicit_exact_codex_loop_intent_or_explicit_skill")
            self.assertEqual(payload["terminal_surface_contract"], "present_exact_canonical_package_through_host_native_skill_update_surface")
            self.assertFalse(payload["attachment_only_install_allowed"])
            self.assertFalse(payload["bridge_required"])

    def test_validator_rejects_package_hash_mismatch(self):
        commit = "c" * 40
        tree = "d" * 40
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package, digest = self.make_package(root, commit=commit, tree=tree)
            handoff = self.make_handoff(root, commit=commit, tree=tree, digest="0" * 64)
            proc, payload = self.run_validator(handoff, package)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("SHA-256", payload["error"])
            self.assertNotEqual(digest, "0" * 64)

    def test_validator_rejects_manifest_identity_mismatch(self):
        commit = "e" * 40
        tree = "f" * 40
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package, digest = self.make_package(root, commit=commit, tree=tree)
            handoff = self.make_handoff(root, commit=commit, tree="1" * 40, digest=digest)
            proc, payload = self.run_validator(handoff, package)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertIn("source binding", payload["error"])


if __name__ == "__main__":
    unittest.main()
