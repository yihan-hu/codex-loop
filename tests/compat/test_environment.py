import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.environment import build_exec_env,build_internal_git_env
class EnvTests(unittest.TestCase):
 def test_secret_patterns_are_case_insensitive(self):
  env=build_exec_env(base={'foo_token':'x','ApiKey':'y','NORMAL':'z'}); self.assertNotIn('foo_token',env); self.assertNotIn('ApiKey',env); self.assertEqual(env['NORMAL'],'z')
 def test_git_redirect_vars_removed(self):
  env=build_internal_git_env({'GIT_DIR':'/tmp/x','GIT_WORK_TREE':'/tmp/y','PATH':'/bin'}); self.assertNotIn('GIT_DIR',env); self.assertEqual(env['GIT_OPTIONAL_LOCKS'],'0')
if __name__=='__main__': unittest.main()

class CookieEnvTests(unittest.TestCase):
  def test_cookie_named_environment_is_filtered(self):
    from codex_loop_runtime.environment import build_exec_env
    env=build_exec_env(base={'SESSION_COOKIE':'supersecret','PATH':'/bin'})
    self.assertNotIn('SESSION_COOKIE',env)

class DeterministicLocaleTests(unittest.TestCase):
  def test_deterministic_locale_and_noninteractive_env_override_inherited_and_overlay(self):
    env=build_exec_env(base={'LC_ALL':'C','LANG':'C'},overlay={'LC_CTYPE':'C','GH_PAGER':'less'})
    self.assertEqual(env['LANG'],'C.UTF-8')
    self.assertEqual(env['LC_CTYPE'],'C.UTF-8')
    self.assertEqual(env['LC_ALL'],'C.UTF-8')
    self.assertEqual(env['GH_PAGER'],'cat')
    self.assertEqual(env['CODEX_CI'],'1')
