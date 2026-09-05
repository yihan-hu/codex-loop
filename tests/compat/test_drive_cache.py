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
    def test_switch_and_registry(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)/"home"
            policy,_ = call(home,"drive-delete-policy")
            self.assertFalse(policy["data"]["delete_enabled"])
            reg,_ = call(home,"drive-cache-register","--folder-path","EpiProse/.runtime/cache")
            self.assertEqual(reg["data"]["folder_paths"],["EpiProse/.runtime/cache"])
            self.assertTrue(reg["data"]["local_only"])

    def test_plan_and_authorize(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)/"home"
            call(home,"drive-cache-register","--folder-path","cache")
            env = os.environ.copy(); env["CODEX_LOOP_HOME"] = str(home)
            code = "from datetime import datetime,timezone; from scripts.codex_loop_runtime.workspace_cache import drive_cache_cleanup_plan; import json; print(json.dumps(drive_cache_cleanup_plan([{'id':'old','name':'old','created_at':'2026-09-01T00:00:00Z','folder_path':'cache','bounded_parent_proven':True,'ownership_proven':True},{'id':'new','name':'new','created_at':'2026-09-04T12:00:00Z','folder_path':'cache','bounded_parent_proven':True,'ownership_proven':True}],now=datetime(2026,9,5,18,tzinfo=timezone.utc))))"
            proc = subprocess.run([sys.executable,"-c",code],cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,check=True)
            plan=json.loads(proc.stdout); self.assertEqual([x["id"] for x in plan["review_candidates"]],["old"])
            pp=Path(td)/"plan.json"; pp.write_text(json.dumps(plan))
            denied,_=call(home,"drive-cache-cleanup-authorize","--plan-json",str(pp),"--llm-review-completed","--llm-confirmed-id","old","--current-user-confirmation-observed","--confirmation-evidence","confirm old")
            self.assertEqual(denied["data"]["status"],"DRIVE_DELETE_DISABLED")
            call(home,"host-config","set","drive.delete_enabled","true")
            ready,_=call(home,"drive-cache-cleanup-authorize","--plan-json",str(pp),"--llm-review-completed","--llm-confirmed-id","old","--current-user-confirmation-observed","--confirmation-evidence","confirm old")
            self.assertTrue(ready["data"]["delete_authorized"])
            self.assertEqual([x["id"] for x in ready["data"]["delete_ready"]],["old"])

if __name__ == "__main__": unittest.main()
