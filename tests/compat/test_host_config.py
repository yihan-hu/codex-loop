import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; CLI=ROOT/'scripts'/'codex_loop.py'
def call(home,*args,check=True):
    env=os.environ.copy(); env['CODEX_LOOP_HOME']=str(home); env['PYTHONDONTWRITEBYTECODE']='1'
    p=subprocess.run([sys.executable,str(CLI),*args],cwd=ROOT,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    data=json.loads(p.stdout) if p.stdout.strip() else None
    if check and p.returncode: raise AssertionError((p.stdout,p.stderr))
    return data,p
class HostConfigTests(unittest.TestCase):
    def test_defaults_and_cloud_browser_route(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)/'home'
            shown,_=call(home,'host-config','show'); self.assertEqual(shown['data']['schema_version'],2); self.assertEqual(shown['data']['browser']['preferred_target'],'cloud_browser')
            route,_=call(home,'interaction-route'); self.assertEqual(route['data']['target'],'cloud_browser'); self.assertFalse(route['data']['requires_current_task_computer_use_authorization'])
            local,_=call(home,'interaction-route','--requires-user-session'); self.assertEqual(local['data']['target'],'local_chrome'); self.assertTrue(local['data']['requires_current_task_computer_use_authorization'])
    def test_v1_migrates_on_write_and_unknown_keys_fail(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)/'home'; home.mkdir(); path=home/'host.json'; path.write_text(json.dumps({'schema_version':1,'default_local_workspace':'piwork'})); os.chmod(path,0o600)
            saved,_=call(home,'host-config','set','browser.preferred_target','cloud_browser'); raw=json.loads(path.read_text()); self.assertEqual(raw['schema_version'],2); self.assertEqual(raw['workspace']['default_local_workspace'],'piwork'); self.assertNotIn('default_local_workspace',raw)
            _,bad=call(home,'host-config','set','browser.unknown','x',check=False); self.assertNotEqual(bad.returncode,0)
    def test_wrong_permissions_fall_back_on_read_and_fail_on_write(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td)/'home'; home.mkdir(); path=home/'host.json'; path.write_text('{}'); os.chmod(path,0o644)
            shown,_=call(home,'host-config','show'); self.assertEqual(shown['data']['source'],'default')
            _,p=call(home,'host-config','set','browser.preferred_target','cloud_browser',check=False); self.assertNotEqual(p.returncode,0)
