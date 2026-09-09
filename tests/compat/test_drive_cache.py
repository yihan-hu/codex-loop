import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "codex_loop.py"

def call(home, *args, check=True):
    env = os.environ.copy(); env["CODEX_LOOP_HOME"] = str(home); env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    if check and proc.returncode != 0: raise AssertionError(f"{args}\n{proc.stdout}\n{proc.stderr}")
    return payload, proc

class DriveCachePolicyTests(unittest.TestCase):
    def test_registry(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)/"home"
            reg,_ = call(home,"drive-cache-register","--folder-path","EpiProse/.runtime/cache")
            self.assertEqual(reg["data"]["folder_paths"],["EpiProse/.runtime/cache"])
            self.assertTrue(reg["data"]["local_only"])

    def test_plan_returns_exact_owned_expired_objects_delete_ready(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)/"home"
            call(home,"drive-cache-register","--folder-path","cache")
            env = os.environ.copy(); env["CODEX_LOOP_HOME"] = str(home)
            code = "from datetime import datetime,timezone; from scripts.codex_loop_runtime.workspace_cache import drive_cache_cleanup_plan; import json; print(json.dumps(drive_cache_cleanup_plan([{'id':'old','name':'old','created_at':'2026-09-01T00:00:00Z','folder_path':'cache','bounded_parent_proven':True,'ownership_proven':True},{'id':'new','name':'new','created_at':'2026-09-04T12:00:00Z','folder_path':'cache','bounded_parent_proven':True,'ownership_proven':True}],now=datetime(2026,9,5,18,tzinfo=timezone.utc))))"
            proc = subprocess.run([sys.executable,"-c",code],cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,check=True)
            plan=json.loads(proc.stdout)
            self.assertEqual(plan["status"],"DRIVE_CACHE_DELETE_READY")
            self.assertEqual([x["id"] for x in plan["delete_ready"]],["old"])
            self.assertTrue(plan["delete_authorized"])
            self.assertEqual([x["id"] for x in plan["retained"]],["new"])


if __name__ == "__main__": unittest.main()
