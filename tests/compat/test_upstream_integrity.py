import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from codex_loop_runtime.upstream_verify import verify


class UpstreamIntegrityTests(unittest.TestCase):
    def test_source_audit_rejects_unclassified_runtime_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "codex-loop"
            shutil.copytree(Path(__file__).resolve().parents[2], copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            probe = copy / "scripts" / "codex_loop_runtime" / "unclassified_probe.py"
            probe.write_text("VALUE = 1\n")
            proc = subprocess.run([sys.executable, str(copy / "scripts" / "audit_source_coverage.py")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("unclassified local runtime modules", proc.stdout.decode())

    def test_manifest_resources_match_hashes(self):
        results = verify()
        self.assertTrue(results)
        self.assertTrue(all(item["ok"] for item in results))
        parser = next(item for item in results if item["path"] == "powershell_parser.ps1")
        self.assertEqual(parser["git_blob_sha1"], "92291e7c98467ed67dd386fbee0368a4b595ecd0")


if __name__ == "__main__":
    unittest.main()

class ClassificationConsistencyTests(unittest.TestCase):
    def test_source_audit_rejects_conflicting_port_and_runtime_modes(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'codex-loop'
            shutil.copytree(Path(__file__).resolve().parents[2], copy, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            mapping = copy / 'references' / 'source-map.yaml'
            data = json.loads(mapping.read_text())
            local = data['ports'][0]['local']
            current = data['ports'][0]['mode']
            alternative = next(x for x in data['classification_contract'] if x != current)
            data['runtime_modules'][local] = alternative
            mapping.write_text(json.dumps(data,indent=2)+'\n')
            proc = subprocess.run([sys.executable, str(copy/'scripts'/'audit_source_coverage.py')], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('conflicts with runtime_modules mode',proc.stdout.decode())
