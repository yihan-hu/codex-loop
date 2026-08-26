import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.state import create_store
from codex_loop_runtime.workspace import hash_file
from codex_loop_runtime.write_transaction import guarded_write
class WriteTests(unittest.TestCase):
  def setup(self,root,profile='regular'):
    store=create_store(root); store.configure_task(store.path.parent.name,'change',[],profile=profile); capture_baseline(root,store); return store
  def test_existing_requires_expected_preimage(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); t=root/'a'; t.write_text('a'); s=self.setup(root)
      with self.assertRaises(RuntimeError): guarded_write(root,s,t,b'b')
  def test_stale_preimage_rejected(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); t=root/'a'; t.write_text('a'); s=self.setup(root); h=hash_file(t); t.write_text('user')
      with self.assertRaises(RuntimeError): guarded_write(root,s,t,b'agent',expected_sha256=h)
  @unittest.skipIf(os.name=='nt','symlink semantics differ')
  def test_symlink_component_rejected(self):
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); (root/'link').symlink_to(Path(out),target_is_directory=True); s=self.setup(root)
      with self.assertRaises(RuntimeError): guarded_write(root,s,root/'link'/'x',b'x')
  def test_readonly_profile_rejects_write(self):
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True); s=self.setup(root,'code_review')
      with self.assertRaises(PermissionError): guarded_write(root,s,root/'x',b'x')
if __name__=='__main__': unittest.main()

class WriteRaceTests(unittest.TestCase):
  @unittest.skipIf(os.name=='nt','symlink race test POSIX')
  def test_symlink_swap_during_pre_write_is_rejected(self):
    import shutil
    from unittest import mock
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
      root=Path(tmp); outside=Path(out); subprocess.run(['git','init','-q'],cwd=root,check=True)
      parent=root/'dir'; parent.mkdir(); s=WriteTests().setup(root)
      target=parent/'new.txt'
      import codex_loop_runtime.write_transaction as wt
      original = wt._reject_symlink_components
      calls = {'n': 0}
      def check_then_swap(check_root, check_target):
        calls['n'] += 1
        original(check_root, check_target)
        if calls['n'] == 2:
          shutil.rmtree(parent); parent.symlink_to(outside,target_is_directory=True)
      with mock.patch.object(wt,'_reject_symlink_components',side_effect=check_then_swap):
        with self.assertRaisesRegex(RuntimeError,'symlink path component'):
          guarded_write(root,s,target,b'x')

class AtomicCompareExchangeTests(unittest.TestCase):
  @unittest.skipIf(os.name=='nt','atomic exchange test requires POSIX/Linux')
  def test_concurrent_change_at_commit_is_restored_and_rejected(self):
    from unittest import mock
    import codex_loop_runtime.write_transaction as wt
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); target=root/'a.txt'; target.write_text('base')
      s=WriteTests().setup(root); expected=hash_file(target)
      original=wt._atomic_exchange; calls={'n':0}
      def racing_exchange(left,right):
        calls['n']+=1
        if calls['n']==1:
          Path(right).write_text('concurrent-user-content')
        return original(left,right)
      with mock.patch.object(wt,'_atomic_exchange',side_effect=racing_exchange):
        with self.assertRaisesRegex(RuntimeError,'concurrent modification'):
          guarded_write(root,s,target,b'agent-content',expected_sha256=expected)
      self.assertEqual(target.read_text(),'concurrent-user-content')

  @unittest.skipIf(os.name=='nt','atomic exchange test requires POSIX/Linux')
  def test_rollback_failure_preserves_displaced_user_preimage(self):
    from unittest import mock
    import re
    import codex_loop_runtime.write_transaction as wt
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); target=root/'a.txt'; target.write_text('base')
      s=WriteTests().setup(root); expected=hash_file(target)
      original=wt._atomic_exchange; calls={'n':0}
      def failing_rollback(left,right):
        calls['n']+=1
        if calls['n']==1:
          Path(right).write_text('concurrent-user-content')
          return original(left,right)
        raise OSError('simulated rollback failure')
      with mock.patch.object(wt,'_atomic_exchange',side_effect=failing_rollback):
        with self.assertRaisesRegex(RuntimeError,'preserved at') as ctx:
          guarded_write(root,s,target,b'agent-content',expected_sha256=expected)
      match=re.search(r'preserved at (.+)$',str(ctx.exception))
      self.assertIsNotNone(match)
      recovery=Path(match.group(1))
      self.assertTrue(recovery.exists())
      self.assertEqual(recovery.read_text(),'concurrent-user-content')

class AtomicExchangeBackendTests(unittest.TestCase):
  def test_platform_dispatches_to_darwin_backend(self):
    from unittest import mock
    import codex_loop_runtime.write_transaction as wt
    with mock.patch.object(wt.sys,'platform','darwin'), mock.patch.object(wt,'_renamex_np_exchange') as darwin, mock.patch.object(wt,'_renameat2_exchange') as linux:
      wt._atomic_exchange('left','right')
      darwin.assert_called_once_with('left','right'); linux.assert_not_called()

  def test_platform_dispatches_to_linux_backend(self):
    from unittest import mock
    import codex_loop_runtime.write_transaction as wt
    with mock.patch.object(wt.sys,'platform','linux'), mock.patch.object(wt,'_renamex_np_exchange') as darwin, mock.patch.object(wt,'_renameat2_exchange') as linux:
      wt._atomic_exchange('left','right')
      linux.assert_called_once_with('left','right'); darwin.assert_not_called()

  @unittest.skipUnless(sys.platform=='darwin','real renamex_np swap requires macOS')
  def test_darwin_backend_swaps_real_files_atomically(self):
    import codex_loop_runtime.write_transaction as wt
    with tempfile.TemporaryDirectory() as tmp:
      root=Path(tmp); left=root/'left'; right=root/'right'; left.write_text('left'); right.write_text('right')
      wt._renamex_np_exchange(left,right)
      self.assertEqual(left.read_text(),'right'); self.assertEqual(right.read_text(),'left')
