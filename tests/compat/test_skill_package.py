import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "build_skill_zip.py"
SPEC = importlib.util.spec_from_file_location("build_skill_zip", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class SkillPackageTests(unittest.TestCase):
    def _build(self, path: Path):
        return MODULE.build_skill_zip(ROOT, path)

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
            with zipfile.ZipFile(package) as archive:
                modes = {((info.external_attr >> 16) & 0xFFFF) for info in archive.infolist() if not info.is_dir()}
            self.assertEqual(modes, {0o100644})
            for forbidden in ("/.github/", "/tests/", "/tools/", "/README.md", "/.gitignore", "__pycache__", ".pyc"):
                self.assertFalse(any(forbidden in name or name.endswith(forbidden) for name in names), forbidden)
            self.assertEqual(result["file_count"], len(names))

    def test_runtime_manifest_matches_current_allowlist(self):
        expected = []
        for name in MODULE.ROOT_FILES:
            expected.append(f"codex-loop/{name}")
        for dirname in MODULE.RUNTIME_DIRS:
            for path in (ROOT / dirname).rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(ROOT)
                if any(part in MODULE.IGNORED_PARTS for part in rel.parts):
                    continue
                if path.suffix in MODULE.IGNORED_SUFFIXES:
                    continue
                expected.append(f"codex-loop/{rel.as_posix()}")
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "skill.zip"
            self._build(package)
            with zipfile.ZipFile(package) as archive:
                actual = [name for name in archive.namelist() if not name.endswith("/")]
        self.assertEqual(sorted(actual), sorted(expected))

    def test_install_verified_metadata_is_enforced(self):
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('icon_small: "./assets/icon.svg"', metadata)
        self.assertIn('icon_large: "./assets/icon.svg"', metadata)
        self.assertNotIn("products:", metadata)


if __name__ == "__main__":
    unittest.main()

class DeploymentProvenanceTests(unittest.TestCase):
    def test_package_can_embed_exact_non_sensitive_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            package=Path(td)/'skill.zip'
            result=MODULE.build_skill_zip(ROOT,package,repository='yihan-hu/codex-loop',commit='a'*40,tree='b'*40)
            with zipfile.ZipFile(package) as archive:
                import json
                manifest=json.loads(archive.read('codex-loop/references/deployment-manifest.json'))
            self.assertEqual(manifest['source']['commit'],'a'*40)
            self.assertEqual(manifest['source']['tree'],'b'*40)
            self.assertFalse(manifest['privacy']['contains_host_profile'])
            self.assertNotIn('package_sha256',manifest['bundle'])
