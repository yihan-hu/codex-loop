import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.checkpoint import create, restore
from codex_loop_runtime.state import create_store
class CheckpointTests(unittest.TestCase):
 def test_checkpoint_contains_validation_and_restore_reconciles(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'AGENTS.md').write_text('rules'); s=create_store(root); s.configure_task(s.path.parent.name,'x',[],requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); capture_baseline(root,s); cp=create(root,root,s,key_findings=['fact'],next_action='next'); self.assertIn('validation',cp); (root/'AGENTS.md').write_text('changed'); restored=restore(root,root,s); self.assertTrue(restored['instruction_drift']); self.assertTrue(restored['reconciled_external_workspace_change'])
if __name__=='__main__': unittest.main()
