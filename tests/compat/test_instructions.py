import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.instructions import discover
class InstructionTests(unittest.TestCase):
  def test_root_to_cwd_and_override_precedence(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'AGENTS.md').write_text('root'); child=root/'a'/'b'; child.mkdir(parents=True); (root/'a'/'AGENTS.md').write_text('normal'); (root/'a'/'AGENTS.override.md').write_text('override')
      self.assertEqual([e.contents for e in discover(child)],['root','override'])
  @unittest.skipIf(os.name=='nt','symlink semantics differ')
  def test_outside_symlink_rejected(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); target=Path(out)/'x'; target.write_text('evil'); (root/'AGENTS.md').symlink_to(target)
      with self.assertRaises((PermissionError,ValueError)): discover(root)
  @unittest.skipIf(os.name=='nt','symlink semantics differ')
  def test_inside_symlink_keeps_lexical_provenance(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'rules.md').write_text('ok'); (root/'AGENTS.md').symlink_to(root/'rules.md'); e=discover(root)[0]; self.assertEqual(Path(e.path).name,'AGENTS.md'); self.assertEqual(e.contents,'ok')
  def test_fallback_must_be_filename(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
      with self.assertRaises(ValueError): discover(root,fallback_filenames=('../x',))
if __name__=='__main__': unittest.main()
