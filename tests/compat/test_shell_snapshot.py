import shutil, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.shell import DetectedShell,ShellType
from codex_loop_runtime.shell_snapshot import capture_plan
class SnapshotTests(unittest.TestCase):
  @unittest.skipUnless(shutil.which('bash'),'bash unavailable')
  def test_snapshot_is_host_visible_plan(self):
    with tempfile.TemporaryDirectory() as tmp:
      plan=capture_plan(Path(tmp),DetectedShell(ShellType.BASH,Path(shutil.which('bash')))); self.assertTrue(plan['requires_host_execution']); self.assertTrue(plan['script_path'].endswith('bash_snapshot.sh'))
  def test_powershell_snapshot_is_reference_only_until_upstream_core_enables_it(self):
    with tempfile.TemporaryDirectory() as tmp:
      with self.assertRaisesRegex(RuntimeError,'not enabled by the audited upstream Codex core'):
        capture_plan(Path(tmp),DetectedShell(ShellType.POWERSHELL,Path('pwsh')))
if __name__=='__main__': unittest.main()
