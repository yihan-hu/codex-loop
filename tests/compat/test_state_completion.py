import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.change_tracker import capture_baseline, sync_generation
from codex_loop_runtime.completion import CompletionStatus, assess
from codex_loop_runtime.state import create_store, open_store, root_state_dir, state_dir_for

def host_validation(store, argv, exit_code, *, cwd, evidence):
  plan=store.create_validation_plan(store.generation(),argv,cwd=cwd)
  return store.record_host_validation(plan['plan_id'],store.generation(),argv,exit_code,cwd=cwd,evidence=evidence)
class CompletionTests(unittest.TestCase):
  def make(self,root,**kw):
    s=create_store(root); s.configure_task(s.path.parent.name,'objective',kw.pop('criteria',[]),**kw); capture_baseline(root,s); return s
  def test_empty_criteria_becomes_objective_and_needs_evidence(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); s=self.make(root,requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); self.assertEqual(len(s.criteria()),1)
      with self.assertRaises(ValueError): s.set_criterion(0,'pass')
  def test_host_validation_evidence_and_review_gate(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); s=self.make(root,requires_validation=True); s.set_criterion(0,'pass','observed objective satisfied')
      host_validation(s,['pytest'],0,cwd=root,evidence='host pytest exit 0')
      self.assertEqual(assess(root,s).status,CompletionStatus.PASS)
  def test_validation_stales_after_external_change(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); s=self.make(root); s.set_criterion(0,'pass','ok'); host_validation(s,['pytest'],0,cwd=root,evidence='pass'); self.assertEqual(assess(root,s).status,CompletionStatus.PASS); (root/'new.txt').write_text('b'); sync_generation(root,s); self.assertEqual(assess(root,s).status,CompletionStatus.CONTINUE)
  def test_host_validation_plan_is_one_time_and_identity_bound(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); s=self.make(root)
      plan=s.create_validation_plan(0,['pytest','-q'],cwd=root)
      with self.assertRaisesRegex(ValueError,'command identity'):
        s.record_host_validation(plan['plan_id'],0,['pytest','-x'],0,cwd=root,evidence='wrong command')
      vid=s.record_host_validation(plan['plan_id'],0,['pytest','-q'],0,cwd=root,evidence='host pytest exited 0')
      self.assertGreater(vid,0)
      with self.assertRaisesRegex(ValueError,'already been consumed'):
        s.record_host_validation(plan['plan_id'],0,['pytest','-q'],0,cwd=root,evidence='duplicate')
      with self.assertRaisesRegex(ValueError,'must consume a validation plan'):
        s.record_validation(0,['pytest'],0,cwd=root,source='host_observed',evidence='bypass')
  def test_unresolved_external_blocks(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); s=self.make(root,requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); s.set_criterion(0,'pass','ok'); s.record_external('github_comment','dispatched','issue1',action_class='external_non_idempotent'); self.assertEqual(assess(root,s).status,CompletionStatus.CONTINUE)
  def test_pending_steer_blocks_and_ack_needs_evidence(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); s=self.make(root,requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); s.set_criterion(0,'pass','ok'); sid=s.record_steer('do not change API'); self.assertEqual(assess(root,s).status,CompletionStatus.CONTINUE); 
      with self.assertRaises(ValueError): s.ack_steer(sid,'')
      s.ack_steer(sid,'replanned to preserve public API'); self.assertEqual(assess(root,s).status,CompletionStatus.PASS)
  def test_readonly_profile_host_change_blocks(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a').write_text('a'); s=self.make(root,profile='code_review',requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); s.set_criterion(0,'pass','review complete'); (root/'a').write_text('b'); self.assertEqual(assess(root,s).status,CompletionStatus.BLOCKED)
  def test_git_index_mutation_requires_authorization(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a').write_text('a'); subprocess.run(['git','add','a'],cwd=root,check=True); s=self.make(root,requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); s.set_criterion(0,'pass','ok'); (root/'b').write_text('b'); subprocess.run(['git','add','b'],cwd=root,check=True); self.assertEqual(assess(root,s).status,CompletionStatus.BLOCKED)
  def test_task_id_isolation_and_unknown_does_not_create(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); a=create_store(root,task_id='task_a'); a.configure_task('task_a','a',[]); b=create_store(root,task_id='task_b'); b.configure_task('task_b','b',[]); self.assertEqual(open_store(root,'task_a').get_meta('objective'),'a');
      target=root_state_dir(root)/'tasks'/'missing'; self.assertFalse(target.exists());
      with self.assertRaises(RuntimeError): state_dir_for(root,'missing',create=False)
      self.assertFalse(target.exists())
  @unittest.skipIf(os.name=='nt','POSIX mode check')
  def test_state_directory_private(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); s=create_store(root); self.assertEqual(s.path.parent.stat().st_mode & 0o777,0o700); self.assertEqual(s.path.stat().st_mode & 0o777,0o600)
if __name__=='__main__': unittest.main()

class FreshnessAndValidationIdentityTests(unittest.TestCase):
  def make(self,root,**kw):
    s=create_store(root); s.configure_task(s.path.parent.name,'objective',kw.pop('criteria',[]),**kw); capture_baseline(root,s); return s
  def test_opaque_ignored_input_blocks_until_explicit_current_waiver(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
      (root/'.gitignore').write_text('big.dat\n')
      (root/'big.dat').write_bytes(b'x'*(1024*1024+1))
      s=self.make(root,requires_validation=False,no_validation_reason='fixture')
      s.set_criterion(0,'pass','objective observed')
      decision=assess(root,s)
      self.assertEqual(decision.status,CompletionStatus.BLOCKED)
      opaque=decision.details['changes']['ignored_watch']['opaque_paths']
      self.assertIn('big.dat',opaque)
      s.set_freshness_waiver(opaque,'fixture explicitly accepts opaque ignored input uncertainty')
      self.assertEqual(assess(root,s).status,CompletionStatus.PASS)

  @unittest.skipIf(os.name=='nt','POSIX executable mode test')
  def test_core_filemode_false_does_not_hide_mode_change_from_generation(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
      t=root/'script.sh'; t.write_text('#!/bin/sh\nexit 0\n'); os.chmod(t,0o644)
      subprocess.run(['git','add','script.sh'],cwd=root,check=True)
      subprocess.run(['git','config','core.filemode','false'],cwd=root,check=True)
      s=self.make(root,requires_validation=False,no_validation_reason='fixture')
      os.chmod(t,0o755)
      self.assertTrue(sync_generation(root,s))
      self.assertEqual(s.generation(),1)

  def test_validation_identity_does_not_collapse_shell_wrapper_with_direct_command(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
      s=self.make(root,requires_validation=True)
      host_validation(s,['bash','-lc','echo hi'],1,cwd=root,evidence='wrapped command failed')
      host_validation(s,['echo','hi'],0,cwd=root,evidence='direct command passed')
      state=s.validation_state_for_generation(0)
      self.assertEqual(state['failed_count'],1)
      self.assertEqual(state['passed_count'],1)
