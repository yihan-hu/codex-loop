import json, subprocess, sys, tempfile, unittest
from pathlib import Path
SKILL=Path(__file__).resolve().parents[2]; CLI=SKILL/'scripts'/'codex_loop.py'
def call(root,*args,check=True,input_bytes=None):
    parts=list(args)
    if '--cwd' not in parts:
        parts=[parts[0],'--cwd',str(root),*parts[1:]]
    cmd=[sys.executable,str(CLI),*parts]
    p=subprocess.run(cmd,input=input_bytes,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=check)
    return json.loads(p.stdout or b'{}'),p
class CliSmokeTests(unittest.TestCase):
  def test_end_to_end_host_validation_gate(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a.txt').write_text('a')
      b,_=call(root,'bootstrap','--objective','change a to b','--criterion','a is b'); tid=b['data']['task_id']
      h,_=call(root,'hash','--path','a.txt'); expected=h['data']['sha256']
      content=root/'payload'; content.write_text('b')
      call(root,'write','--path','a.txt','--content-file',str(content),'--expected-sha256',expected,'--allow-protected','--protected-override-reason','user explicitly requested changing preexisting content')
      call(root,'criterion','--index','0','--status','pass','--evidence','observed a.txt contains b')
      plan,_=call(root,'validate','--','pytest','-q'); self.assertNotIn('generation',plan['data']); self.assertNotIn('plan_id',plan['data'])
      recorded,_=call(root,'validation-record','--command-json','["pytest","-q"]','--exit-code','0','--evidence','host-visible pytest exited 0')
      self.assertTrue(recorded['data']['bookkeeping_inferred'])
      call(root,'changes','--review')
      done,_=call(root,'completion'); self.assertEqual(done['data']['status'],'PASS'); self.assertEqual(tid,done['data']['details']['changes']['generation'] and tid)
  @unittest.skipIf(sys.platform.startswith('win'),'workspace alias test requires symlinks')
  def test_content_file_accepts_workspace_alias_without_losing_symlink_checks(self):
    with tempfile.TemporaryDirectory() as tmp:
      parent=Path(tmp); root=parent/'repo'; root.mkdir(); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a.txt').write_text('a')
      alias=parent/'repo-alias'; alias.symlink_to(root,target_is_directory=True)
      call(alias,'bootstrap','--objective','alias write','--criterion','a is b')
      h,_=call(alias,'hash','--path','a.txt'); payload=alias/'payload'; payload.write_text('b')
      call(alias,'write','--path','a.txt','--content-file',str(payload),'--expected-sha256',h['data']['sha256'],'--allow-protected','--protected-override-reason','test intentionally changes the baseline file')
      self.assertEqual((root/'a.txt').read_text(),'b')

  def test_unknown_exec_is_not_nested(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); call(root,'bootstrap','--objective','inspect')
      out,_=call(root,'exec','--','python3','-c','print(1)'); self.assertFalse(out['data']['executed']); self.assertTrue(out['data']['requires_host_visible_execution'])
  def test_validation_record_rejects_non_array(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); call(root,'bootstrap','--objective','x')
      out,p=call(root,'validation-record','--plan-id','fake','--command-json','"pytest"','--generation','0','--exit-code','0','--evidence','x',check=False); self.assertNotEqual(p.returncode,0); self.assertFalse(out['ok'])
  def test_host_validation_plan_cannot_be_forged_or_reused(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); call(root,'bootstrap','--objective','plan guard')
      plan,_=call(root,'validate','--debug-bookkeeping','--','pytest','-q'); gen=str(plan['data']['generation']); pid=plan['data']['plan_id']
      out,p=call(root,'validation-record','--plan-id','deadbeef','--command-json','["pytest","-q"]','--generation',gen,'--exit-code','0','--evidence','forged',check=False)
      self.assertNotEqual(p.returncode,0); self.assertIn('does not exist',out['error']['message'])
      call(root,'validation-record','--plan-id',pid,'--command-json','["pytest","-q"]','--generation',gen,'--exit-code','0','--evidence','real observation')
      out,p=call(root,'validation-record','--plan-id',pid,'--command-json','["pytest","-q"]','--generation',gen,'--exit-code','0','--evidence','reuse',check=False)
      self.assertNotEqual(p.returncode,0); self.assertIn('already been consumed',out['error']['message'])
  def test_host_validation_generation_is_cas_bound(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); call(root,'bootstrap','--objective','validate x')
      plan,_=call(root,'validate','--debug-bookkeeping','--','pytest','-q'); gen=str(plan['data']['generation']); pid=plan['data']['plan_id']
      (root/'changed-after-validation.txt').write_text('later')
      out,p=call(root,'validation-record','--plan-id',pid,'--command-json','["pytest","-q"]','--generation',gen,'--exit-code','0','--evidence','host-visible pytest exited 0 before later edit',check=False)
      self.assertNotEqual(p.returncode,0); self.assertFalse(out['ok']); self.assertIn('stale',out['error']['message'])
  def test_workspace_release_and_publish_facade(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); subprocess.run(['git','config','user.name','Test User'],cwd=root,check=True); subprocess.run(['git','config','user.email','test@example.com'],cwd=root,check=True)
      (root/'a.txt').write_text('base'); subprocess.run(['git','add','a.txt'],cwd=root,check=True); subprocess.run(['git','commit','-qm','base'],cwd=root,check=True)
      base=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(); base_tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=root,text=True).strip()
      call(root,'bootstrap','--objective','release flow')
      binding,_=call(root,'workspace-binding'); self.assertTrue(binding['data']['matches']); self.assertEqual(binding['data']['binding']['base_commit'],base)
      (root/'a.txt').write_text('target'); subprocess.run(['git','add','a.txt'],cwd=root,check=True); subprocess.run(['git','commit','-qm','target'],cwd=root,check=True)
      plan,_=call(root,'release-plan','--artifact-name','skill.zip','--archive-prefix','codex-loop'); target=plan['data']['source']['commit']; target_tree=plan['data']['source']['tree']; self.assertEqual(plan['data']['archive']['argv'][-1],target)
      receipt,_=call(root,'release-record','--artifact-name','skill.zip','--artifact-sha256','a'*64,'--evidence','verified artifact bytes')
      v,_=call(root,'validate','--','pytest','-q'); call(root,'validation-record','--command-json','["pytest","-q"]','--exit-code','0','--evidence','host pytest passed'); call(root,'changes','--review')
      pub,_=call(root,'publish-plan','--repository','owner/repo','--branch','main','--remote-head',base,'--remote-tree',base_tree,'--release-id',receipt['data']['release_id']); action=pub['data']['action_id']; self.assertEqual(pub['data']['transport_order'],['git']); self.assertEqual(pub['data']['host_executor'],'remote_desktop_commander'); self.assertIsNone(pub['data']['fallback_transport'])
      call(root,'publish-dispatch','--action-id',action,'--transport','git')
      out,_=call(root,'publish-record','--action-id',action,'--state','terminal_success','--transport','git','--remote-commit',target,'--remote-tree',target_tree,'--evidence','native git remote commit/tree readback matched'); self.assertEqual(out['data']['state'],'terminal_success')

  def test_connector_publish_commands_are_not_exposed(self):
    for command in (
      "publish-transfer-start", "publish-transfer-status", "publish-transfer-ack", "publish-transfer-tree-ack",
      "publish-stable-start", "publish-stable-next", "publish-stable-status", "publish-stable-ack", "publish-stable-reconcile",
      "publish-stable-export", "publish-stable-portable-start", "publish-stable-portable-ack",
    ):
      p=subprocess.run([sys.executable,str(CLI),command,"--help"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
      self.assertNotEqual(p.returncode,0,command)

  def test_repeated_validate_reuses_unconsumed_plan_and_inference_stays_unambiguous(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); call(root,'bootstrap','--objective','deduplicated plans')
      first,_=call(root,'validate','--debug-bookkeeping','--','pytest','-q')
      second,_=call(root,'validate','--debug-bookkeeping','--','pytest','-q')
      self.assertEqual(first['data']['plan_id'],second['data']['plan_id']); self.assertFalse(first['data']['plan_reused']); self.assertTrue(second['data']['plan_reused'])
      out,_=call(root,'validation-record','--command-json','["pytest","-q"]','--exit-code','0','--evidence','host observation')
      self.assertTrue(out['data']['bookkeeping_inferred'])

if __name__=='__main__': unittest.main()
