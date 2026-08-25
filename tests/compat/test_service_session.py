import json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
SKILL=Path(__file__).resolve().parents[2]; CLI=SKILL/'scripts'/'codex_loop.py'
sys.path.insert(0,str(SKILL/'scripts'))
def call(root,*args,check=True):
 parts=list(args);
 if parts and parts[0] not in {'bootstrap','command-check','source-verify'} and '--task-id' not in parts: parts=[parts[0],'--cwd',str(root),'--use-active-task',*parts[1:]]
 else: parts=[parts[0],'--cwd',str(root),*parts[1:]]
 p=subprocess.run([sys.executable,str(CLI),*parts],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=check); return json.loads(p.stdout or b'{}'),p
class ServiceTests(unittest.TestCase):
 @unittest.skipIf(os.name=='nt','PTY test Unix')
 def test_spawn_poll_terminate_and_private_endpoint(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); b,_=call(root,'bootstrap','--objective','process test','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid=b['data']['task_id']; call(root,'service-start')
   try:
    r,_=call(root,'spawn','--','sleep','10'); h=r['data']['handle']; endpoint=Path(tempfile.gettempdir())/'codex-loop'; matches=list(endpoint.glob(f'*/tasks/{tid}/service.json')); self.assertEqual(len(matches),1)
    if os.name!='nt': self.assertEqual(matches[0].stat().st_mode & 0o777,0o600)
    call(root,'terminate',h); p,_=call(root,'poll',h); self.assertTrue(p['data']['has_exited']); self.assertTrue(p['data']['output_drained'])
   finally:
    try: call(root,'service-stop')
    except Exception: pass
 @unittest.skipIf(os.name=='nt','PTY test Unix')
 def test_reader_drains_tail_after_short_process(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); call(root,'bootstrap','--objective','drain','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); call(root,'service-start')
   try:
    r,_=call(root,'spawn','--','echo','tail-marker'); h=r['data']['handle']; deadline=time.time()+3; out=None
    while time.time()<deadline:
     out,_=call(root,'poll',h); out=out['data'];
     if out['has_exited'] and out['output_drained']: break
     time.sleep(.03)
    self.assertTrue(out['output_drained']); self.assertIn('tail-marker',out['output'])
   finally:
    try: call(root,'service-stop')
    except Exception: pass
 @unittest.skipIf(os.name=='nt','Unix service test')
 def test_service_spawn_cwd_cannot_escape_workspace(self):
  from codex_loop_runtime.service import request as service_request
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); b,_=call(root,'bootstrap','--objective','cwd guard','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid=b['data']['task_id']; call(root,'service-start')
   try:
    response=service_request(root,tid,{"op":"spawn","argv":["pwd"],"cwd":"/tmp"})
    self.assertFalse(response['ok']); self.assertIn('outside workspace',response['error']['message'])
   finally:
    call(root,'service-stop')
 @unittest.skipIf(os.name=='nt','PTY test Unix')
 def test_spawn_preserves_calling_subdirectory_cwd(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); sub=root/'nested'; sub.mkdir()
   b,_=call(root,'bootstrap','--objective','cwd fidelity','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid=b['data']['task_id']
   call(root,'service-start','--task-id',tid)
   try:
    proc=subprocess.run([sys.executable,str(CLI),'spawn','--cwd',str(sub),'--task-id',tid,'--','pwd'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    data=json.loads(proc.stdout)['data']; h=data['handle']; deadline=time.time()+3; out=None
    while time.time()<deadline:
     pol=subprocess.run([sys.executable,str(CLI),'poll','--cwd',str(root),'--task-id',tid,h],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
     out=json.loads(pol.stdout)['data']
     if out['has_exited'] and out['output_drained']: break
     time.sleep(.03)
    self.assertIn(str(sub),out['output'])
   finally:
    try: call(root,'service-stop','--task-id',tid)
    except Exception: pass

 @unittest.skipIf(os.name=='nt','Unix service wire-budget test')
 def test_service_wire_budget_handles_json_expansion_over_old_one_mib_limit(self):
  from codex_loop_runtime.service import MAX_REQUEST_WIRE_BYTES, MAX_RESPONSE_WIRE_BYTES, request as service_request
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
   b,_=call(root,'bootstrap','--objective','wire budget','--no-validation','--no-validation-reason','fixture'); tid=b['data']['task_id']; call(root,'service-start')
   try:
    argv=['echo', *(['\\'*(60*1024)]*10)]
    encoded=json.dumps({'op':'spawn','argv':argv,'cwd':str(root),'task_id':tid,'token':'x'},ensure_ascii=True).encode('ascii')
    self.assertGreater(len(encoded),1024*1024); self.assertLess(len(encoded),MAX_REQUEST_WIRE_BYTES)
    spawned=service_request(root,tid,{'op':'spawn','argv':argv,'cwd':str(root)},timeout=15)
    response_size=len(json.dumps(spawned,ensure_ascii=True).encode('ascii'))
    self.assertTrue(spawned['ok']); self.assertGreater(response_size,1024*1024); self.assertLess(response_size,MAX_RESPONSE_WIRE_BYTES)
    h=spawned['data']['handle']; service_request(root,tid,{'op':'terminate','handle':h})
   finally:
    try: call(root,'service-stop')
    except Exception: pass


if __name__=='__main__': unittest.main()

class ServiceStartFailClosedTests(unittest.TestCase):
 @unittest.skipIf(os.name=='nt','Unix endpoint test')
 def test_live_unresponsive_helper_metadata_refuses_duplicate_start(self):
  from codex_loop_runtime.service import start as service_start
  from codex_loop_runtime.state import state_dir_for
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
   b,_=call(root,'bootstrap','--objective','duplicate guard','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid=b['data']['task_id']
   directory=state_dir_for(root,tid,create=False)
   endpoint=directory/'service.json'
   endpoint.write_text(json.dumps({'kind':'unix','path':str(directory/'runtime.sock'),'pid':os.getpid(),'task_id':tid,'token':'x'}))
   endpoint.chmod(0o600)
   with self.assertRaisesRegex(RuntimeError,'still alive.*refusing to start a duplicate'):
    service_start(root,tid,CLI)

class ServiceOwnerLockTests(unittest.TestCase):
 @unittest.skipIf(os.name=='nt','Unix lock test')
 def test_owner_lock_blocks_restart_even_when_endpoint_metadata_is_missing(self):
  from codex_loop_runtime.service import _acquire_owner_lock, _release_owner_lock, start as service_start
  from codex_loop_runtime.state import state_dir_for
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
   b,_=call(root,'bootstrap','--objective','owner lock','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid=b['data']['task_id']
   directory=state_dir_for(root,tid,create=False)
   fd=_acquire_owner_lock(directory,nonblocking=True); self.assertIsNotNone(fd)
   try:
    with self.assertRaisesRegex(RuntimeError,'holds task ownership'):
     service_start(root,tid,CLI)
   finally:
    _release_owner_lock(fd)

class ProcessGroupTerminationTests(unittest.TestCase):
 @unittest.skipIf(os.name=='nt','POSIX process-group semantics')
 def test_terminate_group_after_leader_exit(self):
  import signal
  from codex_loop_runtime.process_manager import _process_group_exists, _terminate_process
  proc=subprocess.Popen(['/bin/sh','-c','sleep 30 &'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  try:
   proc.wait(timeout=2)
   self.assertTrue(_process_group_exists(proc.pid))
   self.assertTrue(_terminate_process(proc,grace=0.3,kill_group_if_leader_exited=True))
   self.assertFalse(_process_group_exists(proc.pid))
  finally:
   try: os.killpg(proc.pid,signal.SIGKILL)
   except (ProcessLookupError,OSError): pass

class ServiceDefenseInDepthTests(unittest.TestCase):
 @unittest.skipIf(os.name=='nt','Unix managed-session service is disabled on Windows')
 def test_direct_service_spawn_rechecks_command_safety(self):
  from codex_loop_runtime.service import request as service_request
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
   b,_=call(root,'bootstrap','--objective','service safety','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid=b['data']['task_id']; call(root,'service-start')
   try:
    response=service_request(root,tid,{"op":"spawn","argv":[sys.executable,"-c","print('hidden')"],"cwd":str(root)})
    self.assertFalse(response['ok']); self.assertIn('safe_known',response['error']['message'])
   finally:
    call(root,'service-stop')

 @unittest.skipIf(os.name=='nt','Unix managed-session service is disabled on Windows')
 def test_cancelled_task_service_rejects_spawn_and_stdin_but_allows_terminate(self):
  from codex_loop_runtime.service import request as service_request
  from codex_loop_runtime.state import open_store
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
   b,_=call(root,'bootstrap','--objective','cancelled helper safety','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid=b['data']['task_id']; call(root,'service-start')
   try:
    spawned=service_request(root,tid,{"op":"spawn","argv":["cat"],"cwd":str(root)})
    self.assertTrue(spawned['ok']); handle=spawned['data']['handle']
    open_store(root,tid).cancel('test cancellation without shutting helper')
    denied=service_request(root,tid,{"op":"stdin","handle":handle,"data":"late work\n"})
    self.assertFalse(denied['ok']); self.assertIn('not active',denied['error']['message'])
    denied_spawn=service_request(root,tid,{"op":"spawn","argv":["echo","late"],"cwd":str(root)})
    self.assertFalse(denied_spawn['ok']); self.assertIn('not active',denied_spawn['error']['message'])
    terminated=service_request(root,tid,{"op":"terminate","handle":handle})
    self.assertTrue(terminated['ok']); self.assertTrue(terminated['data']['has_exited'])
   finally:
    try: call(root,'service-stop')
    except Exception: pass

def test_cancelled_service_start_does_not_touch_stale_endpoint_metadata():
    from codex_loop_runtime.state import open_store
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        boot, _ = call(root, 'bootstrap', '--objective', 'cancelled service metadata', '--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
        task_id = boot['data']['task_id']
        call(root, 'cancel', '--task-id', task_id, '--reason', 'stop')
        store = open_store(root, task_id)
        endpoint = store.path.parent / 'service.json'
        sentinel = '{"sentinel":true}\n'
        endpoint.write_text(sentinel, encoding='utf-8')
        proc = subprocess.run(
            [sys.executable, str(CLI), 'service-start', '--cwd', str(root), '--task-id', task_id],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        assert proc.returncode != 0
        assert 'not active' in json.loads(proc.stdout)['error']['message']
        assert endpoint.read_text(encoding='utf-8') == sentinel

class ProcessRetentionBoundTests(unittest.TestCase):
 @unittest.skipIf(os.name=='nt','Unix managed-session service is disabled on Windows')
 def test_many_short_processes_release_heavy_objects_and_bound_success_history(self):
  from codex_loop_runtime.change_tracker import capture_baseline
  from codex_loop_runtime.service import ProcessRegistry
  from codex_loop_runtime.state import create_store
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
   store=create_store(root); store.configure_task(store.path.parent.name,'retention',[],requires_validation=False,no_validation_reason='fixture'); capture_baseline(root,store)
   reg=ProcessRegistry(root,store.task_id,'token')
   for _ in range(80):
    spawned=reg.dispatch({'token':'token','task_id':store.task_id,'op':'spawn','argv':['true'],'cwd':str(root)})
    handle=spawned['handle']; deadline=time.time()+3
    while handle in reg.processes and time.time()<deadline:
     reg.dispatch({'token':'token','task_id':store.task_id,'op':'poll','handle':handle})
     time.sleep(.005)
   self.assertEqual(len(reg.processes),0)
   self.assertLessEqual(len(reg.completed),64)
   exited=[row for row in store.process_rows() if row['state']=='exited']
   self.assertLessEqual(len(exited),64)
