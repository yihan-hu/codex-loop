import os, stat, tempfile, unittest
from pathlib import Path
from unittest import mock
import subprocess, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime import workspace

class GitProbeTimeoutTests(unittest.TestCase):
  @unittest.skipIf(os.name=='nt','shell helper test POSIX')
  def test_run_git_has_bounded_timeout(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); fake=root.parent/f'fake-git-{root.name}.sh'
      fake.write_text('#!/bin/sh\nsleep 2\n'); fake.chmod(0o700)
      try:
        with mock.patch.object(workspace,'_git_executable',return_value=str(fake)), mock.patch.object(workspace,'GIT_PROBE_TIMEOUT_SECONDS',0.03):
          with self.assertRaises(subprocess.TimeoutExpired):
            workspace.run_git(root,['status'])
      finally:
        fake.unlink(missing_ok=True)

  @unittest.skipIf(os.name=='nt','shell helper test POSIX')
  def test_streaming_git_hash_times_out_to_degraded_none(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); fake=root.parent/f'fake-git-{root.name}.sh'
      fake.write_text('#!/bin/sh\nprintf partial\nsleep 2\n'); fake.chmod(0o700)
      try:
        with mock.patch.object(workspace,'_git_executable',return_value=str(fake)), mock.patch.object(workspace,'GIT_PROBE_TIMEOUT_SECONDS',0.03):
          self.assertIsNone(workspace._git_output_sha256(root,['diff']))
      finally:
        fake.unlink(missing_ok=True)
if __name__=='__main__': unittest.main()


class DegradedFingerprintTests(unittest.TestCase):
 def test_failed_diff_probe_falls_back_to_file_content(self):
  from unittest.mock import patch
  from codex_loop_runtime import workspace as ws
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a.txt').write_text('one'); subprocess.run(['git','add','a.txt'],cwd=root,check=True)
   with patch.object(ws,'_git_output_sha256',return_value=None):
    first=ws.workspace_fingerprint(root); (root/'a.txt').write_text('two'); second=ws.workspace_fingerprint(root)
   self.assertNotEqual(first,second)

class GitStatusFailClosedTests(unittest.TestCase):
 def test_baseline_refuses_unobservable_git_status(self):
  from unittest.mock import patch
  from codex_loop_runtime.change_tracker import capture_baseline
  from codex_loop_runtime.state import create_store
  from codex_loop_runtime import workspace as ws
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a.txt').write_text('one')
   store=create_store(root); store.configure_task(store.path.parent.name,'objective',[],requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation')
   with patch.object(ws,'git_status_porcelain_z',return_value=None):
    with self.assertRaisesRegex(RuntimeError,'safe baseline'):
     capture_baseline(root,store)

 def test_status_probe_failure_fingerprint_tracks_file_changes(self):
  from unittest.mock import patch
  from codex_loop_runtime import workspace as ws
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a.txt').write_text('one')
   with patch.object(ws,'git_status_porcelain_z',return_value=None):
    first=ws.workspace_fingerprint(root); (root/'a.txt').write_text('two'); second=ws.workspace_fingerprint(root)
   self.assertNotEqual(first,second)

class GitRepoIdentityFailClosedTests(unittest.TestCase):
 def test_baseline_refuses_git_marker_when_repo_probe_unavailable(self):
  from unittest.mock import patch
  from codex_loop_runtime.change_tracker import capture_baseline
  from codex_loop_runtime.state import create_store
  from codex_loop_runtime import workspace as ws
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a.txt').write_text('one')
   store=create_store(root); store.configure_task(store.path.parent.name,'objective',[],requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation')
   with patch.object(ws,'git_repo_probe',return_value=None):
    with self.assertRaisesRegex(RuntimeError,'safe baseline'):
     capture_baseline(root,store)
 def test_git_probe_degraded_fingerprint_still_tracks_files(self):
  from unittest.mock import patch
  from codex_loop_runtime import workspace as ws
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a.txt').write_text('one')
   with patch.object(ws,'git_repo_probe',return_value=None):
    first=ws.workspace_fingerprint(root); (root/'a.txt').write_text('two'); second=ws.workspace_fingerprint(root)
   self.assertNotEqual(first,second)

class GitIdentityProbeFailureTests(unittest.TestCase):
 def test_baseline_refuses_head_probe_transport_failure(self):
  from unittest.mock import patch
  from codex_loop_runtime.change_tracker import capture_baseline
  from codex_loop_runtime.state import create_store
  from codex_loop_runtime import workspace as ws
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'a').write_text('a'); subprocess.run(['git','add','a'],cwd=root,check=True)
   store=create_store(root); store.configure_task(store.path.parent.name,'objective',[],requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation')
   with patch.object(ws,'_git_head_probe',return_value=(None, True)):
    with self.assertRaisesRegex(RuntimeError,'safe baseline'):
     capture_baseline(root,store)

 def test_unborn_head_and_attached_branch_are_legitimate(self):
  from codex_loop_runtime import workspace as ws
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
   state=ws.git_state(root)
   self.assertTrue(state['is_git'])
   self.assertIsNone(state['head'])
   self.assertFalse(state['head_probe_failed'])
   self.assertFalse(state['branch_probe_failed'])

 def test_detached_head_is_legitimate_branch_absence(self):
  from codex_loop_runtime import workspace as ws
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
   (root/'a').write_text('a'); subprocess.run(['git','add','a'],cwd=root,check=True)
   subprocess.run(['git','-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','init'],cwd=root,check=True)
   head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
   subprocess.run(['git','checkout','--detach','-q',head],cwd=root,check=True)
   state=ws.git_state(root)
   self.assertEqual(state['head'],head)
   self.assertIsNone(state['branch'])
   self.assertFalse(state['branch_probe_failed'])
