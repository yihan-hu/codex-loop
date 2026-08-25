import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
CLI = SKILL / 'scripts' / 'codex_loop.py'
sys.path.insert(0, str(SKILL / 'scripts'))

from codex_loop_runtime.change_tracker import capture_baseline, sync_generation
from codex_loop_runtime.state import active_task_id, create_store, open_store, root_state_dir
from codex_loop_runtime.workspace import hash_file
from codex_loop_runtime.write_transaction import guarded_write

def host_validation(store, argv, exit_code, *, cwd, evidence):
    plan=store.create_validation_plan(store.generation(),argv,cwd=cwd)
    return store.record_host_validation(plan['plan_id'],store.generation(),argv,exit_code,cwd=cwd,evidence=evidence)


def call(root, *args, check=True, input_bytes=None):
    parts = list(args)
    if '--cwd' not in parts:
        if parts and parts[0] not in {'bootstrap','command-check','source-verify'} and '--task-id' not in parts:
            parts = [parts[0], '--cwd', str(root), '--use-active-task', *parts[1:]]
        else:
            parts = [parts[0], '--cwd', str(root), *parts[1:]]
    p = subprocess.run(
        [sys.executable, str(CLI), *parts], input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
    )
    return json.loads(p.stdout or b'{}'), p


class AuditBoundaryTests(unittest.TestCase):
    def test_failed_bootstrap_does_not_replace_active_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            first, _ = call(root, 'bootstrap', '--task-id', 'good', '--objective', 'good', '--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            self.assertEqual(first['data']['task_id'], 'good')
            out, proc = call(root, 'bootstrap', '--task-id', 'bad', '--objective', 'bad', '--profile', 'no_such_profile', check=False)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(out['ok'])
            self.assertEqual(active_task_id(root), 'good')
            self.assertFalse((root_state_dir(root) / 'tasks' / 'bad').exists())

    def test_repo_local_hook_file_is_not_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            cfg = root / '.codex-loop' / 'hooks.json'
            cfg.parent.mkdir()
            cfg.write_text(json.dumps({'pre_write': [['false']]}))
            call(root, 'bootstrap', '--objective', 'write', '--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            payload = root / 'payload'; payload.write_text('ok')
            out, proc = call(root, 'write', '--path', 'new.txt', '--content-file', str(payload), check=True)
            self.assertTrue(out['ok'])
            self.assertTrue((root / 'new.txt').exists())

    def test_protected_preexisting_file_needs_explicit_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            target = root / 'user.txt'; target.write_text('user work')
            store = create_store(root); store.configure_task(store.path.parent.name, 'change', [], requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); capture_baseline(root, store)
            old = hash_file(target)
            with self.assertRaises(PermissionError):
                guarded_write(root, store, target, b'agent', expected_sha256=old)
            result = guarded_write(root, store, target, b'agent', expected_sha256=old, allow_protected=True,protected_override_reason='user explicitly requested changing preexisting content')
            self.assertEqual(result.pre_sha256, old)

    @unittest.skipIf(os.name == 'nt', 'mode-bit test is POSIX-specific')
    def test_non_git_mode_only_change_invalidates_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'script'; target.write_text('x')
            store = create_store(root); store.configure_task(store.path.parent.name, 'x', [], requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); capture_baseline(root, store)
            self.assertEqual(store.generation(), 0)
            target.chmod(0o755)
            self.assertTrue(sync_generation(root, store))
            self.assertEqual(store.generation(), 1)

    @unittest.skipIf(os.name == 'nt', 'symlink fingerprint test is POSIX-specific')
    def test_non_git_directory_symlink_change_invalidates_generation(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as ext:
            root = Path(tmp); outside = Path(ext)
            (outside / 'a').mkdir(); (outside / 'b').mkdir()
            link = root / 'linked-dir'; link.symlink_to(outside / 'a', target_is_directory=True)
            store = create_store(root); store.configure_task(store.path.parent.name, 'x', [], requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); capture_baseline(root, store)
            link.unlink(); link.symlink_to(outside / 'b', target_is_directory=True)
            self.assertTrue(sync_generation(root, store)); self.assertEqual(store.generation(), 1)

    def test_git_ignored_small_file_is_protected_and_invalidates_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            (root/'.gitignore').write_text('local.env\n'); (root/'local.env').write_text('one')
            store=create_store(root); store.configure_task(store.path.parent.name,'ignored freshness',[],requires_validation=False,no_validation_reason='fixture')
            capture_baseline(root,store)
            self.assertIn('local.env',store.protected_paths())
            self.assertIn('local.env',store.get_meta('ignored_watch')['watched_paths'])
            before=store.generation(); (root/'local.env').write_text('two')
            self.assertTrue(sync_generation(root,store)); self.assertEqual(store.generation(),before+1)

    def test_persisted_secret_like_text_is_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root)
            store.configure_task(store.path.parent.name, 'fix token=abcDEF123456789 secret=topsecret123', [], requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation')
            text = store.get_meta('objective')
            self.assertIn('[redacted]', text)
            self.assertNotIn('abcDEF123456789', text)
            self.assertNotIn('topsecret123', text)

    def test_external_state_machine_rejects_terminal_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root); store.configure_task(store.path.parent.name, 'x', [], requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation')
            aid = store.record_external('github_comment', 'planned', 'issue:1', action_class='external_non_idempotent')
            store.record_external('github_comment', 'dispatched', 'issue:1', action_class='external_non_idempotent', action_id=aid)
            store.record_external('github_comment', 'terminal_success', 'issue:1', {'observed':'comment present'}, action_class='external_non_idempotent', action_id=aid)
            with self.assertRaises(ValueError):
                store.record_external('github_comment', 'dispatched', 'issue:1', action_class='external_non_idempotent', action_id=aid)

    def test_external_terminal_failure_blocks_until_evidence_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root); store.configure_task(store.path.parent.name, 'x', [], requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation'); capture_baseline(root, store); store.set_criterion(0, 'pass', 'objective checked')
            aid = store.record_external('github_comment', 'planned', 'issue:1', action_class='external_non_idempotent')
            store.record_external('github_comment', 'dispatched', 'issue:1', action_class='external_non_idempotent', action_id=aid)
            store.record_external('github_comment', 'terminal_failure', 'issue:1', {'observed':'API returned 500'}, action_class='external_non_idempotent', action_id=aid)
            from codex_loop_runtime.completion import CompletionStatus, assess
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)
            store.resolve_external_failure(aid, 'failure was recovered by a later host-visible action; original comment was not created')
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_external_terminal_states_require_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); store = create_store(root); store.configure_task(store.path.parent.name, 'x', [], requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation')
            with self.assertRaises(ValueError): store.record_external('x', 'terminal_success', 'id', action_class='recheckable')
            with self.assertRaises(ValueError): store.record_external('x', 'planned', None, action_class='external_non_idempotent')

    def test_baseline_unrelated_failure_needs_evidence_and_does_not_cancel_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root); store.configure_task(store.path.parent.name, 'x', [], requires_validation=True); capture_baseline(root, store)
            fail = host_validation(store, ['lint'], 1, cwd=root, evidence='host lint exit 1; same baseline failure reproduced before edits')
            store.resolve_validation(fail, 'baseline_unrelated', 'reproduced unchanged against baseline before task edits')
            host_validation(store, ['targeted-test'], 0, cwd=root, evidence='host targeted test exit 0')
            state = store.validation_state_for_generation(0)
            self.assertEqual(state['passed_count'], 1)
            self.assertEqual(state['failed_count'], 0)
            self.assertEqual(state['nonblocking_count'], 1)

    def test_unknown_task_service_lookup_does_not_create_task_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            call(root, 'bootstrap', '--objective', 'x', '--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            missing = root_state_dir(root) / 'tasks' / 'does_not_exist'
            out, proc = call(root, 'service-start', '--task-id', 'does_not_exist', check=False)
            self.assertNotEqual(proc.returncode, 0); self.assertFalse(out['ok']); self.assertFalse(missing.exists())

    def test_cancel_then_cleanup_is_explicit_and_does_not_revert_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            b, _ = call(root, 'bootstrap', '--objective', 'x', '--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid = b['data']['task_id']
            (root / 'user.txt').write_text('keep')
            call(root, 'cancel', '--reason', 'user stopped')
            out, _ = call(root, 'cleanup')
            self.assertTrue(out['data']['cleaned'])
            self.assertEqual((root / 'user.txt').read_text(), 'keep')
            self.assertFalse((root_state_dir(root) / 'tasks' / tid).exists())


if __name__ == '__main__':
    unittest.main()

class HiddenReadBoundaryTests(unittest.TestCase):
    def test_hash_refuses_workspace_external_path(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            root=Path(tmp); outside=Path(out)/'secret.txt'; outside.write_text('secret')
            subprocess.run(['git','init','-q'],cwd=root,check=True); call(root,'bootstrap','--objective','hash guard','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            result, proc = call(root,'hash','--path',str(outside),check=False)
            self.assertNotEqual(proc.returncode,0); self.assertFalse(result['ok']); self.assertIn('outside workspace',result['error']['message'])

    def test_write_content_file_refuses_arbitrary_external_file(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            root=Path(tmp); outside=Path(out)/'secret.txt'; outside.write_text('secret')
            subprocess.run(['git','init','-q'],cwd=root,check=True); call(root,'bootstrap','--objective','write guard','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            result, proc = call(root,'write','--path','x.txt','--content-file',str(outside),check=False)
            self.assertNotEqual(proc.returncode,0); self.assertFalse(result['ok']); self.assertIn('must be inside the workspace',result['error']['message'])


    def test_write_content_file_refuses_task_private_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            boot,_=call(root,'bootstrap','--objective','private read guard','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            store=open_store(root, boot['data']['task_id'])
            private_file=store.path.parent/'private-payload.txt'; private_file.write_text('runtime-private')
            result, proc=call(root,'write','--path','leak.txt','--content-file',str(private_file),check=False)
            self.assertNotEqual(proc.returncode,0); self.assertFalse(result['ok'])
            self.assertIn('must be inside the workspace',result['error']['message'])
            self.assertFalse((root/'leak.txt').exists())

    def test_external_kind_is_scrubbed_before_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); store=create_store(root); store.configure_task(store.path.parent.name,'x',[],requires_validation=False,no_validation_reason='test fixture has no meaningful executable validation')
            aid=store.record_external('token=supersecret12345','planned','id',action_class='recheckable')
            row=next(x for x in store.external_actions() if x['action_id']==aid)
            self.assertNotIn('supersecret12345',row['kind']); self.assertIn('[redacted]',row['kind'])

class ValidationDispositionBoundaryTests(unittest.TestCase):
    def test_post_edit_failure_cannot_be_relabelled_as_baseline_unrelated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); store=create_store(root); store.configure_task(store.path.parent.name,'x',[],requires_validation=True); capture_baseline(root,store)
            store.record_mutation('x.py','external_workspace_change','a','b')
            vid=host_validation(store,['test'],1,cwd=root,evidence='host test exit 1 after edit')
            with self.assertRaisesRegex(ValueError,'baseline generation 0'):
                store.resolve_validation(vid,'baseline_unrelated','looks unrelated')

class CancelledTaskBoundaryTests(unittest.TestCase):

    def test_cancelled_write_rejects_before_payload_file_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            call(root,'bootstrap','--objective','cancel write boundary','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            call(root,'cancel','--reason','stop')
            out, proc=call(root,'write','--path','late.txt','--content-file','missing-payload.txt',check=False)
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('not active',out['error']['message'])
            self.assertNotIn('content file',out['error']['message'])

    def test_cancelled_task_rejects_progress_state_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            call(root,'bootstrap','--objective','cancel state boundary','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            call(root,'cancel','--reason','stop')
            for args in [
                ('criterion','--index','0','--status','pass','--evidence','late'),
                ('steer','--text','late steer'),
                ('git-authorize','--reason','late auth'),
            ]:
                out, proc=call(root,*args,check=False)
                self.assertNotEqual(proc.returncode,0, args)
                self.assertIn('not active',out['error']['message'])
    def test_cancelled_task_cannot_plan_validation_or_start_new_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            call(root,'bootstrap','--objective','cancel boundary','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            call(root,'cancel','--reason','stop')
            out, proc=call(root,'validate','--','pytest','-q',check=False)
            self.assertNotEqual(proc.returncode,0); self.assertIn('not active',out['error']['message'])
            out, proc=call(root,'service-start',check=False)
            self.assertNotEqual(proc.returncode,0); self.assertIn('not active',out['error']['message'])


    def test_cancelled_task_rejects_review_checkpoint_snapshot_and_validation_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            call(root,'bootstrap','--objective','cancel progress boundary','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            call(root,'cancel','--reason','stop')
            for args in [
                ('changes','--review'),
                ('checkpoint','--next-action','late work'),
                ('checkpoint-restore',),
                ('shell-snapshot',),
                ('validation-resolve','--validation-id','1','--evidence','late resolution'),
            ]:
                out, proc=call(root,*args,check=False)
                self.assertNotEqual(proc.returncode,0,args)
                self.assertIn('not active',out['error']['message'])

    def test_cancelled_task_allows_only_already_dispatched_external_outcome_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            call(root,'bootstrap','--objective','cancel external boundary','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            planned,_=call(root,'external','--kind','github_comment','--state','planned','--identity','issue:1','--action-class','external_non_idempotent')
            aid=planned['data']['action_id']
            call(root,'external','--kind','github_comment','--state','dispatched','--identity','issue:1','--action-class','external_non_idempotent','--action-id',aid)
            call(root,'cancel','--reason','stop')
            terminal,_=call(root,'external','--kind','github_comment','--state','terminal_success','--identity','issue:1','--action-class','external_non_idempotent','--action-id',aid,'--details-json','{"observed":"comment present"}')
            self.assertEqual(terminal['data']['state'],'terminal_success')
            out, proc=call(root,'external','--kind','github_comment','--state','planned','--identity','issue:2','--action-class','external_non_idempotent',check=False)
            self.assertNotEqual(proc.returncode,0); self.assertIn('cannot create external action',out['error']['message'])

    def test_cancel_is_not_a_progress_mutation_after_cancellation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            call(root,'bootstrap','--objective','cancel once','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            call(root,'cancel','--reason','first')
            out, proc=call(root,'cancel','--reason','second',check=False)
            self.assertNotEqual(proc.returncode,0); self.assertIn('not active',out['error']['message'])


    def test_cancel_closes_planned_but_not_dispatched_external_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            call(root,'bootstrap','--objective','cancel planned external','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation')
            planned,_=call(root,'external','--kind','future_comment','--state','planned','--identity','issue:2','--action-class','external_non_idempotent')
            planned_id=planned['data']['action_id']
            dispatched,_=call(root,'external','--kind','live_comment','--state','planned','--identity','issue:3','--action-class','external_non_idempotent')
            dispatched_id=dispatched['data']['action_id']
            call(root,'external','--kind','live_comment','--state','dispatched','--identity','issue:3','--action-class','external_non_idempotent','--action-id',dispatched_id)
            call(root,'cancel','--reason','stop')
            store=open_store(root,active_task_id(root)); rows={x['action_id']:x for x in store.external_actions()}
            self.assertEqual(rows[planned_id]['state'],'cancelled_before_dispatch'); self.assertEqual(rows[planned_id]['failure_resolved'],1)
            self.assertEqual(rows[dispatched_id]['state'],'dispatched'); self.assertEqual(store.unresolved_external_count(),1)


class ModifiedDesignBoundaryTests(unittest.TestCase):
    def test_task_scoped_cli_requires_explicit_identity_unless_human_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            boot,_=call(root,'bootstrap','--objective','identity','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'); tid=boot['data']['task_id']
            proc=subprocess.run([sys.executable,str(CLI),'snapshot','--cwd',str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            out=json.loads(proc.stdout); self.assertNotEqual(proc.returncode,0); self.assertIn('explicit --task-id',out['error']['message'])
            proc=subprocess.run([sys.executable,str(CLI),'snapshot','--cwd',str(root),'--task-id',tid],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
            self.assertTrue(json.loads(proc.stdout)['ok'])

    def test_windows_managed_session_capability_is_host_visible_fallback(self):
        from codex_loop_runtime.process_manager import managed_session_capability
        cap=managed_session_capability('nt'); self.assertFalse(cap['supported']); self.assertIn('host-visible',cap['reason'])


class BootstrapIdentityBoundaryTests(unittest.TestCase):
    def test_bootstrap_refuses_existing_explicit_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); subprocess.run(['git','init','-q'],cwd=root,check=True)
            first=subprocess.run([sys.executable,str(CLI),'bootstrap','--cwd',str(root),'--task-id','fixed_task','--objective','first','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
            self.assertTrue(json.loads(first.stdout)['ok'])
            second=subprocess.run([sys.executable,str(CLI),'bootstrap','--cwd',str(root),'--task-id','fixed_task','--objective','second','--no-validation','--no-validation-reason','test fixture has no meaningful executable validation'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            out=json.loads(second.stdout); self.assertNotEqual(second.returncode,0); self.assertIn('already exists',out['error']['message'])
            store=open_store(root,'fixed_task'); self.assertEqual(store.get_meta('objective'),'first')
