import tempfile, subprocess, unittest, uuid
from pathlib import Path
from scripts.codex_loop_runtime.routing_state import route_init, record_permission_observation
from scripts.codex_loop_runtime.state import StateStore
from scripts.codex_loop_runtime.web_publish import build_web_publish_archive, web_publish_plan


def git(root,*args): return subprocess.run(["git",*args],cwd=root,text=True,stdout=subprocess.PIPE,check=True).stdout.strip()
def init_repo(root):
    subprocess.run(["git","init","-q"],cwd=root,check=True); subprocess.run(["git","config","user.email","t@e"],cwd=root,check=True); subprocess.run(["git","config","user.name","t"],cwd=root,check=True)
    (root/'tracked.txt').write_text('x\n'); subprocess.run(["git","add","."],cwd=root,check=True); subprocess.run(["git","commit","-qm","init"],cwd=root,check=True)
    return git(root,'rev-parse','HEAD'),git(root,'rev-parse','HEAD^{tree}')
def ready_store(root):
    store=StateStore(root.parent/(root.name+'-state.sqlite3')); store.configure_task(root.name,'publish',['publish'],requires_validation=False,no_validation_reason='test fixture uses no executable workload'); store.set_meta('changes_reviewed_generation',0); return store
def scopes(): return {'github_push':'repo:owner/repo','github_actions':'actions:owner/repo:download','google_drive_write':'drive:staging'}

class FastPublishTests(unittest.TestCase):
    def route(self): return route_init(session_id='fast-'+uuid.uuid4().hex,host_surface='chatgpt_web')
    def cleanup(self,r):
        p=Path(r['state_path'])
        for x in (p,p.with_suffix('.capabilities.json')):
            try:x.unlink()
            except FileNotFoundError:pass
    def caps(self,sid):
        for c,scope in scopes().items(): record_permission_observation(session_id=sid,capability=c,scope=scope,evidence='live probe')
    def test_fast_publish_reuses_fresh_observations(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); h,tr=init_repo(root); store=ready_store(root); r=self.route(); self.caps(r['session_id'])
            try:
                plan=web_publish_plan(root,store,session_id=r['session_id'],repository='owner/repo',branch='main',remote_head=h,remote_tree='0'*40,capability_scopes=scopes(),verified_tree_fast_path=True)
                self.assertEqual(plan['mode'],'FAST_PUBLISH'); self.assertTrue(plan['validation_reused']); self.assertEqual(len(plan['capability_observations_reused']),3)
            finally:self.cleanup(r)
    def test_dirty_workspace_falls_back(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); h,tr=init_repo(root); store=ready_store(root); r=self.route(); self.caps(r['session_id']); (root/'tracked.txt').write_text('dirty\n')
            try:
                plan=web_publish_plan(root,store,session_id=r['session_id'],repository='owner/repo',branch='main',remote_head=h,remote_tree=tr,capability_scopes=scopes(),verified_tree_fast_path=True)
                self.assertEqual(plan['mode'],'FULL_VERIFIED_PUBLISH'); self.assertIn('workspace_not_clean',plan['fallback_reasons'])
            finally:self.cleanup(r)
    def test_archive_receipt_reuse_is_exact(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); h,tr=init_repo(root); store=ready_store(root); r=self.route(); self.caps(r['session_id']); archive=root.parent/'fast-publish-test.tar.gz'
            try:
                receipt=build_web_publish_archive(root,store,output=archive,top_level='repo')
                plan=web_publish_plan(root,store,session_id=r['session_id'],repository='owner/repo',branch='main',remote_head=h,remote_tree='0'*40,capability_scopes=scopes(),verified_tree_fast_path=True)
                self.assertEqual(plan['archive_action'],'reuse'); self.assertEqual(plan['archive']['sha256'],receipt['sha256'])
            finally:
                self.cleanup(r)
                try: archive.unlink()
                except FileNotFoundError:pass
    def test_remote_tree_equality_short_circuits_transport(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); h,tr=init_repo(root); store=ready_store(root); r=self.route(); self.caps(r['session_id'])
            try:
                plan=web_publish_plan(root,store,session_id=r['session_id'],repository='owner/repo',branch='main',remote_head=h,remote_tree=tr,capability_scopes=scopes(),verified_tree_fast_path=True)
                self.assertTrue(plan['already_published_by_tree']); self.assertIn('skip transport',plan['next'])
            finally:self.cleanup(r)
if __name__=='__main__': unittest.main()
