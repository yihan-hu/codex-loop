import tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.process_manager import run_one_shot

class ProcessLimitTests(unittest.TestCase):
  def test_one_shot_timeout_is_bounded(self):
    with tempfile.TemporaryDirectory() as tmp:
      r=run_one_shot(['sleep','1'],Path(tmp),timeout=0.02)
      self.assertTrue(r.timed_out); self.assertNotEqual(r.exit_code,0)
    with tempfile.TemporaryDirectory() as tmp:
      with self.assertRaises(ValueError): run_one_shot(['true'],Path(tmp),timeout=301)
  def test_private_transcript_is_bounded(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); logs=root/'logs'
      payload=b'abcdef\n'*10000
      r=run_one_shot(['cat'],root,timeout=1.0,transcript_dir=logs,max_transcript_bytes=4096,max_output_bytes=1024,stdin_data=payload)
      self.assertFalse(r.timed_out)
      self.assertGreater(r.transcript_stdout_omitted_bytes,0)
      self.assertLessEqual(Path(r.transcript_stdout).stat().st_size,4096)
if __name__=='__main__': unittest.main()

class ServiceProcessLimitTests(unittest.TestCase):
  @unittest.skipIf(__import__('os').name=='nt','PTY test Unix')
  def test_registry_enforces_active_process_limit(self):
    import os, subprocess
    from unittest import mock
    from codex_loop_runtime.state import create_store
    from codex_loop_runtime.service import ProcessRegistry
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
      store=create_store(root); tid=store.path.parent.name; store.configure_task(tid,'limit',[],requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation')
      reg=ProcessRegistry(root,tid,'token')
      with mock.patch('codex_loop_runtime.service.MAX_MANAGED_PROCESSES',1):
        first=reg.dispatch({'token':'token','task_id':tid,'op':'spawn','argv':['sleep','10'],'cwd':str(root)})
        try:
          with self.assertRaisesRegex(RuntimeError,'process limit'):
            reg.dispatch({'token':'token','task_id':tid,'op':'spawn','argv':['sleep','10'],'cwd':str(root)})
        finally:
          reg.dispatch({'token':'token','task_id':tid,'op':'terminate','handle':first['handle']})
