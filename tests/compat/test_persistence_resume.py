import json, tempfile, unittest
from pathlib import Path
from scripts.codex_loop_runtime.persistence import build_state_manifest, resume_plan, resume_state
from scripts.codex_loop_runtime.state import create_store
from scripts.codex_loop_runtime.change_tracker import capture_baseline
from scripts.codex_loop_runtime.release_lineage import capture_workspace_binding

class PersistenceResumeTests(unittest.TestCase):
    def _manifest(self,root):
        store=create_store(root); tid=store.path.parent.name; store.configure_task(tid,'resume me',['tests pass'],profile='feature'); store.set_meta('workspace_binding',capture_workspace_binding(root)); capture_baseline(root,store); store.set_criterion(0,'pass','historical proof'); aid=store.record_external('publish','planned','stable-x',action_class='external_non_idempotent'); store.record_external('publish','dispatched','stable-x',action_class='external_non_idempotent',action_id=aid); return build_state_manifest(root,root,store,backend='google_drive',repository='yihan-hu/codex-loop')
    def test_resume_invalidates_freshness_and_reconciles_action(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'x.txt').write_text('x'); m=self._manifest(root); plan=resume_plan(m); self.assertIn('external_action_states',plan['required_observations']); h=m['external_actions'][0]['identity_sha256']; obs={'workspace_presence':True,'repository_head':None,'repository_tree':None,'external_action_states':{h:'terminal_success'}}; result=resume_state(root,m,obs); self.assertTrue(result['resumed']); self.assertEqual(result['freshness']['validation'],'historical')
            from scripts.codex_loop_runtime.state import open_store
            resumed=open_store(root,result['task_id']); self.assertEqual(resumed.criteria()[0]['status'],'pending')
    def test_unresolved_action_stays_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/'x').write_text('x'); m=self._manifest(root); h=m['external_actions'][0]['identity_sha256']; result=resume_state(root,m,{'workspace_presence':True,'repository_head':None,'repository_tree':None,'external_action_states':{h:'outcome_unknown'}}); self.assertEqual(result['status'],'EXTERNAL_ACTION_UNRESOLVED')
