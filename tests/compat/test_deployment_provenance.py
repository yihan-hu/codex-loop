import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.codex_loop_runtime.deployment_manifest import (
    DEPLOYMENT_MANIFEST_REL,
    build_deployment_manifest,
    validate_deployment_manifest,
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
        self.source_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.source, check=True, text=True, stdout=subprocess.PIPE
        ).stdout.strip()
        self.source_tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=self.source, check=True, text=True, stdout=subprocess.PIPE
        ).stdout.strip()

    def tearDown(self):
        self._source_tmp.cleanup()

    def test_source_deployment_manifest_is_never_committed(self):
        self.assertFalse((ROOT / DEPLOYMENT_MANIFEST_REL).exists())

    def test_consumer_manifest_has_no_repository_identity(self):
        manifest = build_deployment_manifest(self.source)
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["distribution"], {"profile": "consumer", "repository_binding": "none"})
        self.assertNotIn("source", manifest)
        self.assertNotIn("yihan-hu/codex-loop", json.dumps(manifest))

    def test_consumer_manifest_rejects_repository_arguments(self):
        with self.assertRaisesRegex(ValueError, "must not carry"):
            build_deployment_manifest(self.source, repository="yihan-hu/codex-loop")

    def test_maintainer_wrong_tree_is_rejected_before_packaging(self):
        with self.assertRaisesRegex(ValueError, "source tree mismatch"):
            build_deployment_manifest(
                self.source,
                distribution_profile="maintainer",
                repository="yihan-hu/codex-loop",
                commit=self.source_commit,
                tree="b" * 40,
            )

    def test_maintainer_invalid_commit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "commit"):
            build_deployment_manifest(
                self.source,
                distribution_profile="maintainer",
                repository="yihan-hu/codex-loop",
                commit="short",
                tree=self.source_tree,
            )

    def test_unzipped_consumer_package_verifies_and_tamper_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            package = tmp / "skill.zip"
            MODULE.build_skill_zip(self.source, package)
            install = tmp / "install"
            with zipfile.ZipFile(package) as archive:
                archive.extractall(install)
            skill = install / "codex-loop"
            result = verify_installed_skill(skill)
            self.assertTrue(result["valid"])
            self.assertEqual(result["distribution"]["profile"], "consumer")
            self.assertEqual(result["distribution"]["repository_binding"], "none")
            self.assertIsNone(result["source"])
            self.assertFalse(result["repository_binding_required"])
            (skill / "SKILL.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest hash"):
                verify_installed_skill(skill)

    def test_maintainer_package_retains_provenance_only_source(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "skill.zip"
            MODULE.build_skill_zip(
                self.source,
                package,
                distribution_profile="maintainer",
                repository="yihan-hu/codex-loop",
                commit=self.source_commit,
                tree=self.source_tree,
            )
            install = Path(td) / "install"
            with zipfile.ZipFile(package) as archive:
                archive.extractall(install)
            result = verify_installed_skill(install / "codex-loop")
            self.assertEqual(result["distribution"]["repository_binding"], "provenance_only")
            self.assertEqual(result["source"]["repository"], "yihan-hu/codex-loop")
            self.assertEqual(result["source"]["commit"], self.source_commit)

    def test_legacy_v1_manifest_remains_readable(self):
        manifest = {
            "schema_version": 1,
            "skill_name": "codex-loop",
            "source": {
                "repository": "owner/repo",
                "commit": "a" * 40,
                "tree": "b" * 40,
            },
            "bundle": {
                "profile": "chatgpt-runtime",
                "file_count": 1,
                "manifest_sha256": "c" * 64,
            },
        }
        self.assertEqual(validate_deployment_manifest(manifest), manifest)

    def test_manifest_schema_cannot_carry_private_host_fields(self):
        for manifest in (
            build_deployment_manifest(self.source),
            build_deployment_manifest(
                self.source,
                distribution_profile="maintainer",
                repository="yihan-hu/codex-loop",
                commit=self.source_commit,
                tree=self.source_tree,
            ),
        ):
            text = repr(manifest)
            for forbidden in ("Drive", "staging_folder_id", "default_local_workspace", "OAuth", "conversation_id", "host.json"):
                self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
