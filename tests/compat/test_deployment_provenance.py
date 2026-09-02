import importlib.util
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.codex_loop_runtime.deployment_manifest import (
    DEPLOYMENT_MANIFEST_REL,
    build_deployment_manifest,
    git_tree_sha,
    verify_installed_skill,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "build_skill_zip.py"
SPEC = importlib.util.spec_from_file_location("build_skill_zip_for_provenance", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DeploymentProvenanceTests(unittest.TestCase):
    def setUp(self):
        self._source_tmp = tempfile.TemporaryDirectory()
        self.source = Path(self._source_tmp.name) / "repo"
        shutil.copytree(
            ROOT,
            self.source,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache"),
        )
        subprocess.run(["git", "init", "-q"], cwd=self.source, check=True)
        subprocess.run(["git", "add", "."], cwd=self.source, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"],
            cwd=self.source,
            check=True,
        )
        self.source_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.source, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
        self.source_tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=self.source, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()

    def tearDown(self):
        self._source_tmp.cleanup()

    def test_source_deployment_manifest_is_never_committed(self):
        self.assertFalse((ROOT / DEPLOYMENT_MANIFEST_REL).exists())

    def test_wrong_tree_is_rejected_before_packaging(self):
        with self.assertRaisesRegex(ValueError, "source tree mismatch"):
            build_deployment_manifest(
                self.source,
                repository="yihan-hu/codex-loop",
                commit=self.source_commit,
                tree="b" * 40,
            )

    def test_invalid_commit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "commit"):
            build_deployment_manifest(
                self.source,
                repository="yihan-hu/codex-loop",
                commit="short",
                tree=self.source_tree,
            )

    def test_unzipped_package_verifies_and_tamper_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            package = tmp / "skill.zip"
            MODULE.build_skill_zip(
                self.source,
                package,
                repository="yihan-hu/codex-loop",
                commit=self.source_commit,
                tree=self.source_tree,
            )
            install = tmp / "install"
            with zipfile.ZipFile(package) as archive:
                archive.extractall(install)
            skill = install / "codex-loop"
            result = verify_installed_skill(skill)
            self.assertTrue(result["valid"])
            self.assertEqual(result["source"]["commit"], self.source_commit)
            (skill / "SKILL.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest hash"):
                verify_installed_skill(skill)

    def test_provenance_schema_cannot_carry_private_host_fields(self):
        manifest = build_deployment_manifest(
            self.source,
            repository="yihan-hu/codex-loop",
            commit=self.source_commit,
            tree=self.source_tree,
        )
        text = repr(manifest)
        for forbidden in ("Drive", "staging_folder_id", "default_local_workspace", "OAuth", "conversation_id", "host.json"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
