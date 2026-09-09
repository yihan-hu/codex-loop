import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "prepare_codex_loop_download.py"


class CodexLoopDownloadHandoffTests(unittest.TestCase):
    def test_helper_copies_skill_zip_byte_for_byte_to_codex_loop_zip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "skill.zip"
            output = root / "codex-loop.zip"
            payload = b"PK\x03\x04codex-loop-test-bytes\x00\xff"
            source.write_bytes(payload)

            proc = subprocess.run(
                [sys.executable, str(HELPER), "--source", str(source), "--output", str(output)],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["byte_identical"])
            self.assertFalse(data["recompressed"])
            self.assertEqual(output.read_bytes(), payload)
            expected = hashlib.sha256(payload).hexdigest()
            self.assertEqual(data["source_sha256"], expected)
            self.assertEqual(data["download_sha256"], expected)

    def test_helper_rejects_noncanonical_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad_source = root / "other.zip"
            bad_source.write_bytes(b"x")
            proc = subprocess.run(
                [sys.executable, str(HELPER), "--source", str(bad_source), "--output", str(root / "codex-loop.zip")],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(proc.returncode, 0)

            source = root / "skill.zip"
            source.write_bytes(b"x")
            proc = subprocess.run(
                [sys.executable, str(HELPER), "--source", str(source), "--output", str(root / "wrong.zip")],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertNotEqual(proc.returncode, 0)

    def test_docs_define_official_package_and_chat_download_as_distinct_names(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        deployment = (ROOT / "references" / "skill-deployment.md").read_text(encoding="utf-8")
        runtime = (ROOT / "references" / "runtime-protocol.md").read_text(encoding="utf-8")
        for text in (skill, readme, deployment, runtime):
            self.assertIn("skill.zip", text)
            self.assertIn("codex-loop.zip", text)
        self.assertIn("expose only that exact `codex-loop.zip`", skill)
        self.assertIn("byte-for-byte", readme)
        self.assertIn("never recompress", deployment)
        self.assertIn("identical SHA-256", runtime)


if __name__ == "__main__":
    unittest.main()
