import os, stat, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.command_identity import canonicalize, identify
from codex_loop_runtime.command_safety import SafetyClass, assess
from codex_loop_runtime.process_manager import run_one_shot
class CommandTests(unittest.TestCase):
  def test_wrapped_forced_rm_is_dangerous(self):
    self.assertEqual(assess(['sudo','env','X=1','rm','-rf','/tmp/x']).classification,SafetyClass.DANGEROUS)
    self.assertEqual(assess(['bash','-lc','echo ok; rm --force /tmp/x']).classification,SafetyClass.DANGEROUS)
  def test_shell_wrapper_always_host_visible(self):
    self.assertEqual(assess(['bash','-lc','echo hi >/tmp/x']).classification,SafetyClass.OPAQUE)
    self.assertEqual(assess(['bash','-c','echo hi']).classification,SafetyClass.OPAQUE)
  def test_git_only_version_is_local(self):
    self.assertEqual(assess(['git','--version']).classification,SafetyClass.SAFE_KNOWN)
    for cmd in (['git','status'],['git','--help'],['git','reset','--hard'],['git','clean','-fd']): self.assertNotEqual(assess(cmd).classification,SafetyClass.SAFE_KNOWN)
  def test_stdin_filters_do_not_open_files(self):
    self.assertEqual(assess(['cat']).classification,SafetyClass.SAFE_KNOWN)
    self.assertEqual(assess(['cat','-']).classification,SafetyClass.SAFE_KNOWN)
    self.assertNotEqual(assess(['cat','--','-secret']).classification,SafetyClass.SAFE_KNOWN)
    self.assertNotEqual(assess(['wc','--files0-from=list']).classification,SafetyClass.SAFE_KNOWN)
  def test_which_type_and_path_qualified_are_host_visible(self):
    for cmd in (['which','python'],['type','python'],['/bin/echo','x']): self.assertNotEqual(assess(cmd).classification,SafetyClass.SAFE_KNOWN)
  def test_identity_shell_command_substitution_is_opaque(self):
    c,opaque=canonicalize(['bash','-lc','echo $(date)']); self.assertTrue(opaque)
  def test_identity_shell_trailing_argv_is_preserved(self):
    a=identify(['bash','-lc','printf %s "$0"','alpha'],Path.cwd())
    b=identify(['bash','-lc','printf %s "$0"','beta'],Path.cwd())
    self.assertNotEqual(a.digest,b.digest); self.assertTrue(a.opaque); self.assertIn('alpha',a.canonical_argv)
  def test_identity_powershell_token_boundaries_do_not_collide(self):
    a=identify(['pwsh','-Command','Write-Output','a b'],Path.cwd())
    b=identify(['pwsh','-Command','Write-Output a','b'],Path.cwd())
    self.assertNotEqual(a.digest,b.digest)
  def test_local_exec_ignores_caller_path(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); fake=root/'bin'; fake.mkdir(); p=fake/'echo'; p.write_text('#!/bin/sh\necho PWNED\n'); p.chmod(0o755)
      old=os.environ.get('PATH',''); os.environ['PATH']=str(fake)+os.pathsep+old
      try:
        result=run_one_shot(['echo','ok'],root); self.assertIn('ok',result.stdout); self.assertNotIn('PWNED',result.stdout)
      finally: os.environ['PATH']=old
if __name__=='__main__': unittest.main()
