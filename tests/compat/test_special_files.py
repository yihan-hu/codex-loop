import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.workspace import hash_file,snapshot_files
from codex_loop_runtime.state import create_store
from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.write_transaction import guarded_write
class SpecialFiles(unittest.TestCase):
 @unittest.skipIf(os.name=='nt','FIFO Unix')
 def test_fifo_not_read_or_replaced(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); fifo=root/'pipe'; os.mkfifo(fifo); self.assertIsNone(hash_file(fifo)); self.assertNotIn('pipe',[x.path for x in snapshot_files(root)]); s=create_store(root); s.configure_task(s.path.parent.name,'x',[],requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); capture_baseline(root,s)
   with self.assertRaises(RuntimeError): guarded_write(root,s,fifo,b'x')
if __name__=='__main__': unittest.main()
