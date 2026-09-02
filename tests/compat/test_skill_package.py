import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.codex_loop_runtime.deployment_manifest import DEPLOYMENT_MANIFEST_REL, git_tree_sha

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "build_skill_zip.py"
SPEC = importlib.util.spec_from_file_location("build_skill_zip", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SkillPackageTests(unittest.TestCase):
    def setUp(self):
        self._source_tmp = tempfile.TemporaryDirectory()
        self.source = Path(self._source_tmp.name) / "repo"
        self.source_commit, self.source_tree = self._copy_git_fixture(self.source)

    def tearDown(self):
        self._source_tmp.cleanup()

    def _copy_git_fixture(self, destination: Path) -> tuple[str, str]:
        shutil.copytree(
            ROOT,
            destination,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache"),
        )
        subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
        subprocess.run(["git", "add", "."], cwd=destination, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"],
            cwd=destination,
            check=True,
        )
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=destination, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
        tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=destination, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()
        return head, tree

    def _build(self, path: Path):
        return MODULE.build_skill_zip(
            self.source,
            path,
            repository="yihan-hu/codex-loop",
            commit=self.source_commit,
            tree=self.source_tree,
        )

    def test_runtime_package_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            first = Path(td) / "first.zip"
            second = Path(td) / "second.zip"
            self._build(first)
            self._build(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_runtime_package_excludes_development_only_files(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "skill.zip"
            result = self._build(package)
            with zipfile.ZipFile(package) as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
            self.assertEqual({name.split("/", 1)[0] for name in names}, {"codex-loop"})
            self.assertEqual(names.count("codex-loop/SKILL.md"), 1)
            self.assertIn(f"codex-loop/{DEPLOYMENT_MANIFEST_REL.as_posix()}", names)
            with zipfile.ZipFile(package) as archive:
                modes = {((info.external_attr >> 16) & 0xFFFF) for info in archive.infolist() if not info.is_dir()}
            self.assertEqual(modes, {0o100644})
            for forbidden in ("/.github/", "/tests/", "/tools/", "/README.md", "/.gitignore", "__pycache__", ".pyc", "host.json"):
                self.assertFalse(any(forbidden in name or name.endswith(forbidden) for name in names), forbidden)
            self.assertEqual(result["file_count"], len(names))

    def test_runtime_manifest_matches_current_allowlist_plus_generated_provenance(self):
        expected = []
        for name in MODULE.ROOT_FILES:
            expected.append(f"codex-loop/{name}")
        for dirname in MODULE.RUNTIME_DIRS:
            for path in (self.source / dirname).rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(self.source)
                if rel == DEPLOYMENT_MANIFEST_REL:
                    continue
                if any(part in MODULE.IGNORED_PARTS for part in rel.parts):
                    continue
                if path.suffix in MODULE.IGNORED_SUFFIXES:
                    continue
                expected.append(f"codex-loop/{rel.as_posix()}")
        expected.append(f"codex-loop/{DEPLOYMENT_MANIFEST_REL.as_posix()}")
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "skill.zip"
            self._build(package)
            with zipfile.ZipFile(package) as archive:
                actual = [name for name in archive.namelist() if not name.endswith("/")]
        self.assertEqual(sorted(actual), sorted(expected))

    def test_package_provenance_has_exact_source_identity_but_no_package_self_hash(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "skill.zip"
            result = self._build(package)
            with zipfile.ZipFile(package) as archive:
                payload = archive.read(f"codex-loop/{DEPLOYMENT_MANIFEST_REL.as_posix()}")
            manifest = json.loads(payload)
            self.assertEqual(manifest["source"]["repository"], "yihan-hu/codex-loop")
            self.assertEqual(manifest["source"]["commit"], self.source_commit)
            self.assertEqual(manifest["source"]["tree"], self.source_tree)
            self.assertEqual(manifest["bundle"]["manifest_sha256"], result["bundle_manifest_sha256"])
            self.assertNotIn("package_sha256", payload.decode("utf-8"))


    def test_git_tracked_projection_ignores_untracked_runtime_and_cache_files(self):
        (self.source / "scripts" / "untracked-runtime-note.txt").write_text("scratch\n", encoding="utf-8")
        cache = self.source / "scripts" / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "ignored.cpython-313.pyc").write_bytes(b"cache")
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "skill.zip"
            result = self._build(package)
            self.assertEqual(result["source"]["tree"], self.source_tree)
            self.assertEqual(git_tree_sha(self.source), self.source_tree)
            with zipfile.ZipFile(package) as archive:
                names = set(archive.namelist())
        self.assertNotIn("codex-loop/scripts/untracked-runtime-note.txt", names)
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))

    def test_git_tracked_dirty_source_fails_closed_before_packaging(self):
        readme = self.source / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\ndirty\n", encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "tracked source is dirty"):
                self._build(Path(td) / "skill.zip")

    def test_install_verified_metadata_is_enforced(self):
        metadata = (self.source / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('icon_small: "./assets/icon.svg"', metadata)
        self.assertIn('icon_large: "./assets/icon.svg"', metadata)
        self.assertNotIn("products:", metadata)


if __name__ == "__main__":
    unittest.main()
