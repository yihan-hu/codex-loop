"""Local adaptive DAG, stale lease takeover, and Git safety regression tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPT))
from codex_loop_runtime import local_collaboration as c


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


class AdaptiveCollaborationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        prior = os.environ.get('CODEX_LOOP_HOME')
        self.addCleanup(lambda: os.environ.__setitem__('CODEX_LOOP_HOME', prior) if prior is not None else
                        os.environ.pop('CODEX_LOOP_HOME', None))
        os.environ['CODEX_LOOP_HOME'] = str(self.root / 'state')
        self.repo = self.root / 'repo'
        self.parent = self.root / 'workers'
        self.repo.mkdir()
        self.parent.mkdir()
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.email', 'test@example.org')
        git(self.repo, 'config', 'user.name', 'Test')
        (self.repo / 'start.txt').write_text('base\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'start')

    def run_tasks(self, specs=None):
        specs = specs or [{'key': 'A', 'title': 'A', 'instructions': 'produce A'}]
        return c.create_run(str(self.repo), 'main', str(self.parent), specs,
                            goal_key='adaptive-test')['run_id']

    def claim(self, run, worker):
        return c.claim(run, worker, worktree_parent=str(self.parent))

    def commit(self, assignment):
        root = Path(assignment['worktree'])
        (root / f'{assignment["task_key"]}.txt').write_text(assignment['task_id'])
        git(root, 'add', '.')
        git(root, 'commit', '-m', assignment['task_key'])
        return git(root, 'rev-parse', 'HEAD')

    def expire(self, run, task_key='A'):
        with c._connection(write=True) as db:
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=? AND task_key=?',
                       (time.time()-601, run, task_key))

    def test_retired_worker_receives_durable_stop_and_cannot_claim(self):
        run=self.run_tasks([{'key':'A','title':'Model','pool':'model','instructions':'Generate'},
                            {'key':'B','title':'QA','pool':'qa','instructions':'Review'}])
        task=self.claim(run,'old-chat')
        result=c.retire_worker(run,'old-chat','Switch to native generation')
        self.assertTrue(result['new_claims_blocked'])
        self.assertEqual(result['active_task']['task_key'],'A')
        self.assertTrue(c.activity('old-chat')['stop'])
        with self.assertRaises(PermissionError):
            self.claim(run,'old-chat')
        self.assertFalse(c.retire_worker(run,'old-chat','Switch to native generation')['already_retired'] is False)
        c.finish(run,'old-chat',commit_sha=self.commit(task),auto_claim=False,
                 lease_generation=task['lease_generation'])
        with self.assertRaises(PermissionError):
            self.claim(run,'old-chat')
        self.assertEqual(self.claim(run,'other-chat')['pool'],'qa')

    def test_due_review_and_machine_pool_owners(self):
        run=self.run_tasks([{'key':'g','pool':'qwen','title':'Generate','instructions':'G'},
                            {'key':'h','pool':'qa','title':'Inspect','instructions':'H'}])
        c.configure_pool_operators(run,['machine1'],['qwen'])
        c.configure_recurring_review(run,'native-health','health',1200,'Inspect running process')
        reviewer=self.claim(run,'chat1')
        self.assertEqual(reviewer['pool'],'health')
        self.assertEqual(reviewer['isolation_spec']['mutation_policy'],'read_only')
        self.assertEqual(self.claim(run,'chat2')['pool'],'qa')
        self.assertEqual(self.claim(run,'machine1')['pool'],'qwen')
        with c._connection(write=True) as db:
            db.execute('UPDATE recurring_reviews SET last_published=? WHERE run_id=?',
                       (time.time()-1201,run))
        self.assertEqual(c.claim(run,'chat3',worktree_parent=str(self.parent),
                                 wait_if_empty=True)['status'],'waiting')
        self.assertEqual(sum(x['pool_id']=='health' for x in c.status(run)['slots']),1)
        c.finish(run,'chat1',commit_sha=self.commit(reviewer),auto_claim=False,
                 lease_generation=reviewer['lease_generation'])
        self.assertEqual(self.claim(run,'chat4')['pool'],'health')
        self.assertEqual(sum(x['pool_id']=='health' for x in c.status(run)['slots']),2)

    def test_shared_gpu_cap_skips_both_pools_and_dispatches_ready_qa(self):
        run = self.run_tasks([
            {'key':'qwen-1', 'pool':'qwen', 'title':'Qwen 1', 'instructions':'GPU'},
            {'key':'chain-1', 'pool':'chain', 'title':'Chain 1', 'instructions':'GPU'},
            {'key':'qwen-2', 'pool':'qwen', 'title':'Qwen 2', 'instructions':'GPU'},
            {'key':'chain-2', 'pool':'chain', 'title':'Chain 2', 'instructions':'GPU'},
            {'key':'qa-1', 'pool':'qa', 'title':'QA 1', 'instructions':'QA'},
        ])
        with self.assertRaises(ValueError):
            c.set_resource_cap(run, 'local_mlx_gpu', 0, ['qwen','chain'])
        with self.assertRaises(ValueError):
            c.set_resource_cap(run, 'local_mlx_gpu', 2, ['missing'])
        limit = c.set_resource_cap(run, 'local_mlx_gpu', 2, ['qwen','chain'])
        self.assertEqual(limit['claimed'], 0)
        first = self.claim(run, 'gpu-qwen')
        second = self.claim(run, 'gpu-chain')
        self.assertEqual({first['pool'],second['pool']}, {'qwen','chain'})
        self.assertEqual(c.status(run)['resource_caps'][0]['claimed'], 2)
        qa = self.claim(run, 'scientist')
        self.assertEqual(qa['pool'], 'qa')
        idle = c.claim(run, 'gpu-waiter', worktree_parent=str(self.parent),
                       wait_if_empty=True)
        self.assertEqual(idle['status'], 'waiting')
        self.assertEqual(c.status(run)['resource_caps'][0]['claimed'], 2)
        c.finish(run, 'gpu-qwen', commit_sha=self.commit(first), auto_claim=False,
                 lease_generation=first['lease_generation'])
        resumed = self.claim(run, 'gpu-waiter')
        self.assertEqual(resumed['pool'], 'qwen')
        self.assertEqual(c.status(run)['resource_caps'][0]['claimed'], 2)

    def test_waiting_heartbeats_do_not_refresh_the_600_second_claimed_lease(self):
        run = self.run_tasks([
            {'key':'A', 'title':'A', 'instructions':'A'},
            {'key':'B', 'title':'B', 'instructions':'B', 'depends_on':['A']}])
        owner = self.claim(run, 'producer')
        with c._connection() as db:
            original_seen = db.execute(
                "SELECT last_seen FROM slots WHERE run_id=? AND task_id=?",
                (run, 'producer')).fetchone()[0]
        initial = c.claim(run, 'idle', worktree_parent=str(self.parent), wait_if_empty=True)
        self.assertEqual(initial['status'], 'waiting')
        self.assertEqual(len(c.status(run)['waiting_workers']), 1)
        self.assertFalse((self.parent / f'{run}-worker-idle').exists())
        waited = c.wait_claim(run, 'idle', worktree_parent=str(self.parent),
                              poll_interval=0.02, max_wait_seconds=0.08)
        self.assertEqual(waited['status'], 'waiting')
        self.assertTrue(waited['retry_wait'])
        self.assertGreater(waited['heartbeat_at'], initial['heartbeat_at'])
        with c._connection() as db:
            still_seen = db.execute(
                "SELECT last_seen FROM slots WHERE run_id=? AND task_id=?",
                (run, 'producer')).fetchone()[0]
        self.assertEqual(original_seen, still_seen)
        self.assertEqual(c.status(run)['lease_seconds'], 600)
        c.finish(run, 'producer', commit_sha=self.commit(owner), auto_claim=False,
                 lease_generation=owner['lease_generation'])
        claimed = c.wait_claim(run, 'idle', worktree_parent=str(self.parent),
                               poll_interval=0.01, max_wait_seconds=0.1)
        self.assertEqual(claimed['task_key'], 'B')
        self.assertFalse(c.status(run)['waiting_workers'])
        c.finish(run, 'idle', commit_sha=self.commit(claimed),
                 lease_generation=claimed['lease_generation'])
        end = c.wait_claim(run, 'new-idle', worktree_parent=str(self.parent),
                           poll_interval=0.01, max_wait_seconds=0.1)
        self.assertEqual(end['status'], 'done')
        self.assertEqual(end['run_state'], 'integrating')

    def test_two_waiters_claim_distinct_work_after_dependency_unlock(self):
        run = self.run_tasks([
            {'key':'A','title':'foundation','instructions':'A'},
            {'key':'B','title':'parallel-1','instructions':'B','depends_on':['A']},
            {'key':'C','title':'parallel-2','instructions':'C','depends_on':['A']}])
        owner = self.claim(run, 'producer')
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(c.wait_claim, run, worker,
                        worktree_parent=str(self.parent), poll_interval=0.02,
                        max_wait_seconds=2.0) for worker in ('idle-1', 'idle-2')]
            deadline = time.monotonic() + 1.0
            while len(c.status(run)['waiting_workers']) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(c.status(run)['waiting_workers']), 2)
            c.finish(run, 'producer', commit_sha=self.commit(owner), auto_claim=False,
                     lease_generation=owner['lease_generation'])
            outcomes = [f.result(timeout=3) for f in futures]
        self.assertEqual({o['task_key'] for o in outcomes}, {'B','C'})
        self.assertEqual({o['task_id'] for o in outcomes}, {'idle-1','idle-2'})
        self.assertEqual(c.status(run)['waiting_workers'], [])

    def test_1_1_5_1_waiting_pool_fanout_and_final_fanin(self):
        specs = [
            {'key':'foundation', 'title':'foundation', 'instructions':'foundation'},
            {'key':'gate', 'title':'gate', 'instructions':'gate',
             'depends_on':['foundation']}]
        specs += [
            {'key':f'parallel-{i}', 'pool':f'pool-{i}', 'title':f'parallel-{i}',
             'instructions':f'parallel-{i}', 'depends_on':['gate']}
            for i in range(5)]
        specs.append({
            'key':'tail', 'title':'tail', 'instructions':'tail',
            'depends_on':[f'parallel-{i}' for i in range(5)]})
        run=self.run_tasks(specs)
        first=self.claim(run,'main')
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures=[executor.submit(c.wait_claim, run, f'idle-{i}',
                    worktree_parent=str(self.parent), poll_interval=0.025,
                    max_wait_seconds=6.0) for i in range(5)]
            deadline=time.monotonic()+2.0
            while len(c.status(run)['waiting_workers']) < 5 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(c.status(run)['waiting_workers']), 5)
            c.finish(run,'main',commit_sha=self.commit(first),auto_claim=False,
                     lease_generation=first['lease_generation'])
            gate=self.claim(run,'main')
            self.assertEqual(gate['task_key'],'gate')
            c.finish(run,'main',commit_sha=self.commit(gate),auto_claim=False,
                     lease_generation=gate['lease_generation'])
            claims=[f.result(timeout=7) for f in futures]
        self.assertEqual({a['task_key'] for a in claims},
                         {f'parallel-{i}' for i in range(5)})
        self.assertEqual(len({a['task_id'] for a in claims}),5)
        self.assertEqual(c.status(run)['waiting_workers'],[])
        for assignment in claims:
            c.finish(run,assignment['task_id'],commit_sha=self.commit(assignment),
                     auto_claim=False,lease_generation=assignment['lease_generation'])
        tail=self.claim(run,'main')
        self.assertEqual(tail['task_key'],'tail')
        for i in range(5):
            self.assertTrue((Path(tail['worktree'])/f'parallel-{i}.txt').is_file())
        result=c.finish(run,'main',commit_sha=self.commit(tail),
                        lease_generation=tail['lease_generation'])
        self.assertTrue(result['integrate_now'])
        self.assertEqual(c.status(run)['lease_seconds'],600)

    def test_waiter_can_claim_dynamically_published_ready_pool(self):
        run=self.run_tasks([{'key':'A','title':'original','instructions':'original'}])
        owner=self.claim(run,'publisher')
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(c.wait_claim,run,'waiting-reviewer',
                                   worktree_parent=str(self.parent),
                                   poll_interval=0.02,max_wait_seconds=2.0)
            deadline=time.monotonic()+1
            while not c.status(run)['waiting_workers'] and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(c.status(run)['waiting_workers']),1)
            c.publish_task(run,'publisher',
                           {'key':'new-ready','pool':'later','title':'review',
                            'instructions':'review as soon as ready',
                            'exclude_workers':['publisher']},
                           lease_generation=owner['lease_generation'])
            claimed=future.result(timeout=3)
        self.assertEqual(claimed['task_key'],'new-ready')
        self.assertEqual(claimed['pool'],'later')
        self.assertEqual(claimed['task_id'],'waiting-reviewer')
        self.assertEqual(c.status(run)['graph_revision'],2)
        self.assertEqual(c.status(run)['waiting_workers'],[])

    def test_cli_wait_claim_returns_bounded_waiting_response(self):
        run=self.run_tasks([{'key':'A','title':'A','instructions':'A'}])
        self.claim(run, 'owner')
        from codex_loop_runtime.state import create_store
        from codex_loop_runtime.change_tracker import capture_baseline
        store=create_store(self.repo,task_id='idle-cli')
        store.configure_task('idle-cli',request_anchor='Wait for the next Ready task')
        capture_baseline(self.repo,store)
        output=subprocess.run([
            sys.executable, str(SCRIPT / 'codex_loop.py'), 'collab', 'claim',
            '--run-id', run, '--task-id', 'idle-cli',
            '--worktree-parent', str(self.parent), '--wait',
            '--poll-interval', '0.02', '--max-wait-seconds', '0.07'],
            capture_output=True, text=True, check=True)
        result=json.loads(output.stdout)['data']
        self.assertEqual(result['status'], 'waiting')
        self.assertTrue(result['retry_wait'])
        self.assertGreaterEqual(result['waited_seconds'], 0.06)
        self.assertEqual(c.status(run)['waiting_workers'][0]['task_id'], 'idle-cli')

    def test_tool_activity_rate_limits_lease_and_delivers_unread_messages(self):
        run=self.run_tasks([{'key':'A','title':'A','instructions':'A'}])
        owner=self.claim(run,'work')
        before=c.status(run)['slots'][0]['last_seen']
        one=c.activity('work')
        self.assertTrue(one['registered'])
        self.assertFalse(one['refreshed'])
        self.assertFalse(one['stop'])
        with c._connection(write=True) as db:
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=? AND task_id=?',
                       (time.time()-61,run,'work'))
            c._notice(db,run,'coord','work','Review new instructions')
        two=c.activity('work')
        self.assertEqual(two['refreshed'][0]['slot'],owner['slot'])
        self.assertIn('Review',two['messages'][0]['body'])
        three=c.activity('work')
        self.assertEqual(three['refreshed'],[])
        self.assertEqual([m['id'] for m in three['messages']],
                         [m['id'] for m in two['messages']])
        self.assertEqual(c.status(run)['lease_seconds'],600)

    def test_original_verified_finish_preempts_unfinished_successor_and_sends_stop(self):
        run=self.run_tasks([{'key':'A','title':'A','instructions':'A'}])
        old=self.claim(run,'original')
        sha=self.commit(old)
        self.expire(run)
        new=self.claim(run,'replacement')
        self.assertEqual(new['lease_generation'],2)
        (Path(new['worktree'])/'replacement-draft.txt').write_text('preserve partial new work')
        result=c.finish(run,'original',commit_sha=sha,slot_number=old['slot'],
                        lease_generation=old['lease_generation'])
        self.assertEqual(result['status'],'accepted')
        self.assertEqual(result['stopped_worker'],'replacement')
        self.assertTrue(result['integrate_now'])
        status=c.status(run)
        self.assertEqual(status['slots'][0]['task_id'],'original')
        self.assertEqual((Path(new['worktree'])/'replacement-draft.txt').read_text(),
                         'preserve partial new work')
        pulse=c.activity('replacement')
        self.assertTrue(pulse['stop'])
        self.assertEqual(pulse['messages'][0]['control_action'],'stop_task')
        self.assertIn('STOP',c.inbox(run,'replacement')['messages'][0]['body'])
        with self.assertRaisesRegex(PermissionError, 'STOP'):
            self.claim(run,'replacement')
        with self.assertRaises(PermissionError):
            c.finish(run,'replacement',commit_sha=git(new['worktree'],'rev-parse','HEAD'),
                     slot_number=new['slot'],lease_generation=new['lease_generation'])
        again=c.finish(run,'original',commit_sha=sha,slot_number=old['slot'],
                       lease_generation=old['lease_generation'])
        self.assertTrue(again['already_finished'])
        self.assertEqual(c.status(run)['slots'][0]['commit_sha'],sha)
        self.assertEqual(git(self.repo,'rev-parse',
                        f'refs/codex-loop/collab/{run}/slot-{old["slot"]}'),sha)

    def test_cli_activity_returns_worker_heartbeat_status(self):
        run=self.run_tasks()
        owner=self.claim(run,'active-cli')
        with c._connection(write=True) as db:
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=? AND task_id=?',
                       (time.time()-61,run,'active-cli'))
        output=subprocess.run([
            sys.executable,str(SCRIPT/'codex_loop.py'),'collab','activity',
            '--task-id','active-cli','--interval-seconds','60'],
            capture_output=True,text=True,check=True)
        data=json.loads(output.stdout)['data']
        self.assertTrue(data['registered'])
        self.assertEqual(data['refreshed'][0]['slot'],owner['slot'])
        self.assertEqual(data['messages'],[])

    def test_successor_finished_first_preserves_original_result_as_alternative(self):
        run=self.run_tasks([{'key':'A','title':'A','instructions':'A'}])
        old=self.claim(run,'original')
        old_sha=self.commit(old)
        self.expire(run)
        new=self.claim(run,'replacement')
        new_sha=self.commit(new)
        c.finish(run,'replacement',commit_sha=new_sha,
                 slot_number=new['slot'],lease_generation=new['lease_generation'])
        late=c.finish(run,'original',commit_sha=old_sha,
                      slot_number=old['slot'],lease_generation=old['lease_generation'])
        self.assertEqual(late['status'],'preserved')
        self.assertEqual(c.status(run)['slots'][0]['commit_sha'],new_sha)
        self.assertEqual(git(self.repo,'rev-parse',late['late_result_ref']),old_sha)
        self.assertFalse(c.activity('replacement')['stop'])

    def test_late_finish_legacy_unverified_start_preserves_without_override(self):
        run=self.run_tasks([{'key':'A','title':'A','instructions':'A'}])
        old=self.claim(run,'original')
        old_sha=self.commit(old)
        self.expire(run)
        new=self.claim(run,'replacement')
        with c._connection(write=True) as db:
            db.execute('UPDATE reclaims SET old_start_commit=NULL WHERE run_id=?',(run,))
        late=c.finish(run,'original',commit_sha=old_sha,slot_number=old['slot'],
                      lease_generation=old['lease_generation'])
        self.assertEqual(late['status'],'preserved')
        self.assertEqual(c.status(run)['slots'][0]['task_id'],'replacement')
        self.assertFalse(c.activity('replacement')['stop'])
        self.assertEqual(git(self.repo,'rev-parse',late['late_result_ref']),old_sha)

    def test_ten_minute_reclaim_preserves_dirty_old_worktree_and_fences(self):
        run = self.run_tasks()
        old = self.claim(run, 'old')
        (Path(old['worktree']) / 'draft.txt').write_text('not committed')
        self.expire(run)
        new = self.claim(run, 'replacement')
        self.assertNotEqual(old['worktree'], new['worktree'])
        self.assertEqual(new['lease_generation'], 2)
        self.assertEqual(new['recovery']['old_task_id'], 'old')
        self.assertTrue(new['reconcile_external_effects'])
        self.assertEqual((Path(old['worktree']) / 'draft.txt').read_text(), 'not committed')
        self.assertEqual((Path(new['worktree']) / 'draft.txt').read_text(), 'not committed')
        self.assertEqual(new['restored_worktree']['untracked_files'],1)
        with self.assertRaises(PermissionError):
            c.heartbeat(run, 'old', lease_generation=old['lease_generation'])
        sha = self.commit(new)
        with self.assertRaises(PermissionError):
            c.finish(run, 'replacement', commit_sha=sha, slot_number=new['slot'],
                     lease_generation=old['lease_generation'])
        with self.assertRaises(PermissionError):
            c.finish(run, 'replacement', commit_sha=sha, slot_number=new['slot'])
        final = c.finish(run, 'replacement', commit_sha=sha, slot_number=new['slot'],
                         lease_generation=new['lease_generation'])
        self.assertTrue(final['integrate_now'])
        self.assertEqual(len(c.status(run)['reclaims']), 1)

    def test_reclaim_after_unmaterialized_restore_skips_only_empty_lease(self):
        run=self.run_tasks()
        first=self.claim(run,'first')
        self.expire(run)
        # A technical failure after lease adoption but before start_commit
        # persists must not permanently poison all subsequent claims.
        with mock.patch.object(c, '_restore_reclaimed_worktree',
                               side_effect=RuntimeError('simulated interrupted restore')):
            with self.assertRaisesRegex(RuntimeError,'simulated interrupted restore'):
                self.claim(run,'second')
        with c._connection() as db:
            abandoned=db.execute('SELECT worktree,start_commit FROM slots WHERE run_id=?',
                                 (run,)).fetchone()
            self.assertEqual((abandoned['worktree'],abandoned['start_commit']),(None,None))
        self.expire(run)
        third=self.claim(run,'third')
        self.assertEqual(third['lease_generation'],3)
        self.assertEqual(third['restored_worktree']['status'],'skipped_unmaterialized_lease')
        self.assertEqual(third['restored_worktree']['replayed_commits'],0)
        self.assertTrue(third['restored_worktree']['prior_recovery_history_preserved'])
        self.assertTrue(Path(first['worktree']).exists())
        with c._connection() as db:
            older=db.execute('SELECT COUNT(*) FROM reclaims WHERE run_id=?',(run,)).fetchone()[0]
            self.assertEqual(older,2)
        sha=self.commit(third)
        result=c.finish(run,'third',commit_sha=sha,
                        slot_number=third['slot'],lease_generation=third['lease_generation'])
        self.assertTrue(result['integrate_now'])
        self.assertEqual(c.status(run)['slots'][0]['status'], 'done')

    def test_reclaim_without_checkpoint_recovers_git_index_worktree_and_untracked_outputs(self):
        run=self.run_tasks()
        old=self.claim(run,'original')
        old_root=Path(old['worktree'])
        (old_root/'committed.txt').write_text('already committed')
        git(old_root,'add','committed.txt')
        git(old_root,'commit','-m','old intermediate task work')
        old_commit=git(old_root,'rev-parse','HEAD')
        (old_root/'start.txt').write_text('staged state\n')
        git(old_root,'add','start.txt')
        (old_root/'start.txt').write_text('unstaged state\n')
        (old_root/'output').mkdir()
        payload=b'\x00\xffbinary\x00'
        (old_root/'output'/'data.bin').write_bytes(payload)
        (old_root/'output'/'nested.txt').write_text('in progress')
        (old_root/'output'/'link').symlink_to('nested.txt')
        old_state=git(old_root,'status','--porcelain','--untracked-files=all')
        old_index=git(old_root,'diff','--cached')
        old_work=git(old_root,'diff')
        self.expire(run)
        successor=self.claim(run,'successor')
        new_root=Path(successor['worktree'])
        self.assertEqual(successor['restored_worktree']['replayed_commits'],1)
        self.assertTrue(successor['restored_worktree']['staged_changes'])
        self.assertTrue(successor['restored_worktree']['unstaged_changes'])
        self.assertEqual(successor['restored_worktree']['untracked_files'],3)
        self.assertEqual((new_root/'committed.txt').read_text(),'already committed')
        self.assertEqual((new_root/'output'/'data.bin').read_bytes(),payload)
        self.assertTrue((new_root/'output'/'link').is_symlink())
        self.assertEqual(git(new_root,'diff','--cached'),old_index)
        self.assertEqual(git(new_root,'diff'),old_work)
        self.assertEqual(git(new_root,'status','--porcelain','--untracked-files=all'),old_state)
        self.assertIn(old_commit,git(new_root,'log','-1','--format=%B'))
        self.assertEqual(git(old_root,'rev-parse','HEAD'),old_commit)
        self.assertEqual(git(old_root,'status','--porcelain','--untracked-files=all'),old_state)
        # An idempotent claim must not reapply the old commits or patches.
        again=self.claim(run,'successor')
        self.assertEqual(again['worktree'],successor['worktree'])
        self.assertEqual(git(new_root,'status','--porcelain','--untracked-files=all'),old_state)
        git(new_root,'add','-A')
        git(new_root,'commit','-m','finish original partial work')
        result=c.finish(run,'successor',commit_sha=git(new_root,'rev-parse','HEAD'),
                        lease_generation=successor['lease_generation'],slot_number=successor['slot'])
        self.assertTrue(result['integrate_now'])
        ready=c.prepare_integration(run,'successor',integration_worktree=str(self.repo))
        self.assertEqual(ready['status'],'READY_FOR_TEST')
        self.assertEqual((self.repo/'committed.txt').read_text(),'already committed')
        self.assertEqual((self.repo/'start.txt').read_text(),'unstaged state\n')
        self.assertEqual((self.repo/'output'/'data.bin').read_bytes(),payload)
        c.integration_complete(run,'successor',integration_worktree=str(self.repo),
                               test_evidence='recovered commit, index, worktree, and files checked')
        self.assertEqual(c.status(run)['lease_seconds'],600)

    def test_reclaim_dependent_task_replays_only_old_task_own_commits(self):
        run=self.run_tasks([
            {'key':'A','title':'A','instructions':'foundation'},
            {'key':'B','title':'B','instructions':'dependent','depends_on':['A']}])
        producer=self.claim(run,'producer')
        c.finish(run,'producer',commit_sha=self.commit(producer),auto_claim=False,
                 lease_generation=producer['lease_generation'])
        old=self.claim(run,'original')
        self.assertEqual(old['task_key'],'B')
        old_root=Path(old['worktree'])
        self.assertTrue((old_root/'A.txt').is_file())
        (old_root/'b.txt').write_text('B partial result')
        git(old_root,'add','b.txt')
        git(old_root,'commit','-m','partially completed B')
        self.expire(run,'B')
        new=self.claim(run,'successor')
        new_root=Path(new['worktree'])
        self.assertEqual(new['restored_worktree']['replayed_commits'],1)
        self.assertEqual((new_root/'A.txt').read_text(),'producer')
        self.assertEqual((new_root/'b.txt').read_text(),'B partial result')
        self.assertEqual(git(new_root,'rev-list','--count',f"{new['base_commit']}..HEAD"),'2')
        c.finish(run,'successor',commit_sha=git(new_root,'rev-parse','HEAD'),
                 slot_number=new['slot'],lease_generation=new['lease_generation'])
        ready=c.prepare_integration(run,'successor',integration_worktree=str(self.repo))
        self.assertEqual(ready['status'],'READY_FOR_TEST')
        self.assertEqual((self.repo/'b.txt').read_text(),'B partial result')

    def test_reclaim_rebases_absolute_internal_symlinks_into_successor_worktree(self):
        run=self.run_tasks()
        old=self.claim(run,'original')
        old_path=Path(old['worktree'])
        (old_path/'artifacts').mkdir()
        (old_path/'artifacts'/'result.txt').write_text('original data')
        (old_path/'alias.txt').symlink_to(old_path/'artifacts'/'result.txt')
        self.expire(run)
        new=self.claim(run,'successor')
        new_path=Path(new['worktree'])
        alias=new_path/'alias.txt'
        self.assertTrue(alias.is_symlink())
        self.assertFalse(Path(alias.readlink()).is_absolute())
        self.assertEqual(alias.resolve(),new_path/'artifacts'/'result.txt')
        self.assertEqual(alias.read_text(),'original data')
        (new_path/'artifacts'/'result.txt').write_text('successor only')
        self.assertEqual((old_path/'artifacts'/'result.txt').read_text(),'original data')
        self.assertTrue((old_path/'alias.txt').readlink().is_absolute())

    def test_recovery_refuses_untracked_symlink_escaping_old_worktree(self):
        run=self.run_tasks()
        old=self.claim(run,'original')
        (Path(old['worktree'])/'outside').symlink_to(self.root/'private')
        self.expire(run)
        with self.assertRaisesRegex(RuntimeError,'external untracked symlink'):
            self.claim(run,'successor')
        self.assertTrue((Path(old['worktree'])/'outside').is_symlink())
        with c._connection() as db:
            row=db.execute('SELECT status,task_id,start_commit FROM slots WHERE run_id=?',(run,)).fetchone()
            self.assertEqual((row['status'],row['task_id']),('claimed','successor'))
            self.assertIsNone(row['start_commit'])

    def test_recovered_commits_cannot_overwrite_conflicting_completed_worker(self):
        run=self.run_tasks([{'key':'A','title':'A','instructions':'A'},
                            {'key':'B','title':'B','instructions':'B'}])
        old=self.claim(run,'old')
        existing=self.claim(run,'successor')
        old_root=Path(old['worktree'])
        successor_root=Path(existing['worktree'])
        (old_root/'start.txt').write_text('from original task\\n')
        git(old_root,'add','start.txt')
        git(old_root,'commit','-m','original in-flight change')
        (successor_root/'start.txt').write_text('from completed B task\\n')
        git(successor_root,'add','start.txt')
        git(successor_root,'commit','-m','completed B work')
        c.finish(run,'successor',commit_sha=git(successor_root,'rev-parse','HEAD'),
                 auto_claim=False,slot_number=existing['slot'],
                 lease_generation=existing['lease_generation'])
        self.expire(run,'A')
        with self.assertRaisesRegex(RuntimeError,'conflict resolution'):
            self.claim(run,'successor')
        self.assertEqual((old_root/'start.txt').read_text(),'from original task\\n')
        self.assertEqual((successor_root/'start.txt').read_text(),'from completed B task\\n')
        self.assertEqual(git(successor_root,'status','--porcelain','--untracked-files=all'),'')
        self.assertEqual(c.status(run)['slots'][0]['status'],'claimed')

    def test_reclaim_restores_staged_binary_patch(self):
        (self.repo/'bytes.dat').write_bytes(b'\x00before')
        git(self.repo,'add','bytes.dat')
        git(self.repo,'commit','-m','binary fixture')
        run=self.run_tasks()
        old=self.claim(run,'original')
        data=b'\x00\xffafter\x00'
        (Path(old['worktree'])/'bytes.dat').write_bytes(data)
        git(old['worktree'],'add','bytes.dat')
        self.expire(run)
        new=self.claim(run,'successor')
        dest=Path(new['worktree'])
        self.assertEqual((dest/'bytes.dat').read_bytes(),data)
        self.assertTrue(new['restored_worktree']['staged_changes'])
        self.assertEqual(git(dest,'diff','--cached','--numstat'),
                         git(old['worktree'],'diff','--cached','--numstat'))
        self.assertEqual(git(dest,'diff'),'')

    def test_reclaim_cannot_copy_old_worktree_outside_authorized_parent(self):
        run=self.run_tasks()
        old=self.claim(run,'original')
        outside=self.root/'outside-worker'
        git(self.repo,'worktree','add','--detach',str(outside),
            git(self.repo,'rev-parse','HEAD'))
        self.expire(run)
        c.reclaim(run,'A',force=False,reason='expired original')
        with c._connection(write=True) as db:
            db.execute('UPDATE reclaims SET old_worktree=? WHERE run_id=?',
                       (str(outside),run))
        with self.assertRaisesRegex(PermissionError,'outside the run-authorized'):
            self.claim(run,'successor')
        self.assertTrue(outside.is_dir())
        self.assertTrue(Path(old['worktree']).is_dir())

    def test_ignored_cache_is_not_silently_duplicated(self):
        (self.repo/'.gitignore').write_text('.cache/\n')
        git(self.repo,'add','.gitignore')
        git(self.repo,'commit','-m','ignored build data')
        run=self.run_tasks()
        old=self.claim(run,'original')
        cached=Path(old['worktree'])/'.cache'
        cached.mkdir()
        (cached/'token.dat').write_bytes(b'local only')
        self.expire(run)
        next=self.claim(run,'successor')
        self.assertGreaterEqual(next['restored_worktree']['ignored_entries_not_copied'],1)
        self.assertFalse((Path(next['worktree'])/'.cache'/'token.dat').exists())
        self.assertEqual((cached/'token.dat').read_bytes(),b'local only')

    def test_snapshot_detects_concurrent_source_file_mutation(self):
        run=self.run_tasks()
        old=self.claim(run,'original')
        source=Path(old['worktree'])/'draft.txt'
        source.write_text('first version')
        self.expire(run)
        original_copy=c.shutil.copy2
        def race(a,b,*args,**kwargs):
            value=original_copy(a,b,*args,**kwargs)
            if Path(a)==source:
                source.write_text('second version')
            return value
        with mock.patch.object(c.shutil,'copy2',side_effect=race):
            with self.assertRaisesRegex(RuntimeError,'changed during recovery snapshot'):
                self.claim(run,'successor')
        self.assertEqual(source.read_text(),'second version')
        new=Path(self.parent/f'{run}-worker-successor')
        self.assertFalse((new/'draft.txt').exists())

    def test_original_worker_can_resume_after_inactivity_before_any_takeover(self):
        run=self.run_tasks()
        original=self.claim(run,'worker-long-pause')
        draft=Path(original['worktree'])/'partial.txt'
        draft.write_text('unfinished content')
        self.expire(run)
        resumed=self.claim(run,'worker-long-pause')
        self.assertEqual(resumed['lease_generation'],original['lease_generation'])
        self.assertEqual(resumed['worktree'],original['worktree'])
        self.assertEqual(draft.read_text(),'unfinished content')
        self.assertEqual(c.status(run)['reclaims'],[])

    def test_heartbeat_keeps_claim_and_force_reclaim_bypasses_wait(self):
        run = self.run_tasks()
        active = self.claim(run, 'living')
        self.expire(run)
        c.heartbeat(run, 'living', lease_generation=active['lease_generation'])
        with self.assertRaisesRegex(RuntimeError, 'no unclaimed'):
            self.claim(run, 'contender')
        with self.assertRaisesRegex(RuntimeError, 'has not expired'):
            c.reclaim(run, 'A')
        c.reclaim(run, 'A', force=True, reason='authorised forced recovery')
        new = self.claim(run, 'contender')
        self.assertEqual(new['lease_generation'], 2)
        self.assertEqual(new['recovery']['reason'], 'authorised forced recovery')

    def test_publish_revision_and_independent_review_eligibility(self):
        run = self.run_tasks([
            {'key': 'A', 'title': 'producer', 'instructions': 'A'},
            {'key': 'B', 'title': 'consumer', 'instructions': 'B', 'depends_on': ['A']}])
        owner = self.claim(run, 'producer')
        review = c.publish_task(run, 'producer', {
            'key': 'check-A', 'pool': 'review', 'title': 'independent check',
            'instructions': 'check producer without self-review', 'review_of': ['A'],
            'exclude_workers': ['worker3']}, lease_generation=owner['lease_generation'])
        self.assertEqual(review['graph_revision'], 2)
        changed = c.revise_task(run, 'producer', 'B',
            {'depends_on':['check-A'], 'exclude_workers':['worker1']},
            lease_generation=owner['lease_generation'], expected_revision=2)
        self.assertEqual(changed['graph_revision'], 3)
        with self.assertRaisesRegex(RuntimeError, 'revision'):
            c.revise_task(run, 'producer', 'B', {'title':'stale edit'},
                          lease_generation=owner['lease_generation'], expected_revision=2)
        with self.assertRaisesRegex(ValueError, 'self dependency'):
            c.revise_task(run, 'producer', 'B', {'depends_on':['B']},
                          lease_generation=owner['lease_generation'], expected_revision=3)
        c.finish(run, 'producer', commit_sha=self.commit(owner), auto_claim=False,
                 lease_generation=owner['lease_generation'])
        with self.assertRaisesRegex(RuntimeError, 'eligible'):
            self.claim(run, 'producer')
        reviewer = self.claim(run, 'reviewer')
        self.assertEqual(reviewer['task_key'], 'check-A')
        self.assertEqual(reviewer['pool'], 'review')
        self.assertEqual(reviewer['depends_on'], ['A'])
        c.finish(run, 'reviewer', commit_sha=self.commit(reviewer), auto_claim=False,
                 lease_generation=reviewer['lease_generation'])
        b = self.claim(run, 'third')
        self.assertEqual(b['task_key'], 'B')
        self.assertEqual(c.status(run)['graph_revision'], 3)

    def test_publish_entire_pool_atomically_with_internal_dependencies(self):
        run=self.run_tasks()
        owner=self.claim(run,'publisher')
        before=c.status(run)['graph_revision']
        batch=[{'key':'X','pool':'new-pool','title':'X','instructions':'produce X',
                'depends_on':['A']},
               {'key':'Y','pool':'new-pool','title':'Y','instructions':'review X',
                'review_of':['X']}]
        result=c.publish_task(run,'publisher',batch,lease_generation=owner['lease_generation'])
        self.assertEqual(result['graph_revision'],before+1)
        self.assertEqual(result['published'],['X','Y'])
        self.assertEqual(c.status(run)['pools']['new-pool']['waiting'],2)
        with self.assertRaisesRegex(ValueError,'cycle'):
            c.publish_task(run,'publisher',[
                {'key':'P','title':'P','instructions':'P','depends_on':['Q']},
                {'key':'Q','title':'Q','instructions':'Q','depends_on':['P']}],
                lease_generation=owner['lease_generation'])
        self.assertEqual(c.status(run)['graph_revision'],before+1)
        self.assertEqual(len(c.status(run)['slots']),3)

    def test_exclusion_applies_before_claim_and_race_fences_one_owner(self):
        run = self.run_tasks([
            {'key':'A','title':'first','instructions':'produce'},
            {'key':'B','title':'review','instructions':'check',
             'depends_on':['A'], 'exclude_workers':['worker1']}])
        first = self.claim(run, 'first')
        c.finish(run,'first',commit_sha=self.commit(first),auto_claim=False,
                 lease_generation=first['lease_generation'])
        with self.assertRaisesRegex(RuntimeError, 'eligible'):
            self.claim(run, 'first')
        second = self.claim(run, 'second')
        self.assertEqual(second['task_key'], 'B')
        self.expire(run, 'B')
        with ThreadPoolExecutor(max_workers=4) as executor:
            def try_claim(i):
                try:
                    return self.claim(run, f'other{i}')
                except RuntimeError:
                    return None
            outcomes = list(executor.map(try_claim, range(4)))
        assigned = [item for item in outcomes if item]
        self.assertEqual(len(assigned), 1)
        self.assertEqual(assigned[0]['lease_generation'], 2)

    def test_checkpoint_remains_optional_and_committed_delta_is_replayed(self):
        run = self.run_tasks()
        old = self.claim(run, 'writer')
        sha = self.commit(old)
        c.checkpoint(run, 'writer', lease_generation=old['lease_generation'],
                     commit_sha=sha, note='first unit verified')
        self.expire(run)
        new = self.claim(run, 'next')
        self.assertEqual(new['recovery']['checkpoint_sha'], sha)
        self.assertEqual(new['recovery']['checkpoint_note'], 'first unit verified')
        self.assertEqual(git(self.repo, 'rev-parse',
                            f'refs/codex-loop/collab/{run}/checkpoint-1-g1'), sha)
        self.assertEqual((Path(new['worktree']) / 'A.txt').read_text(), 'writer')
        self.assertTrue((Path(old['worktree']) / 'A.txt').exists())
        self.assertEqual(new['restored_worktree']['replayed_commits'],1)

    def test_reclaim_delegations_does_not_leave_dead_sender_as_blocker(self):
        run = self.run_tasks([
            {'key':'A','title':'A','instructions':'A'},
            {'key':'B','title':'B','instructions':'B'}])
        old = self.claim(run, 'old')
        other = self.claim(run, 'other')
        c.delegate(run,'old',request_key='outgoing',title='verify',instructions='independent',
                   recipient_task='other')
        offered = c.delegate(run,'other',request_key='incoming',title='read',instructions='review',
                             recipient_task='old')
        c.accept_delegation(run,'old',delegation_id=offered['id'])
        self.expire(run)
        replacement = self.claim(run, 'replacement')
        self.assertEqual(replacement['task_key'], 'A')
        entries = c.status(run)['delegations']
        self.assertTrue(any(v['request_key']=='outgoing' and v['sender']=='replacement'
                            for v in entries))
        self.assertTrue(any(v['request_key']=='incoming' and v['recipient'] is None
                            and v['status']=='offered' for v in entries))

    def test_unplanned_run_recovers_expired_slot_without_creating_another(self):
        kw=dict(repo=str(self.repo),target_branch='main',worktree_parent=str(self.parent),
                goal_key='same-purpose',title='first',instructions='finish original work')
        old = c.dynamic_join(task_id='old', **kw)
        with c._connection(write=True) as db:
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=?',
                       (time.time()-601,old['run_id']))
        new = c.dynamic_join(task_id='new', **kw)
        self.assertEqual(new['slot'], old['slot'])
        self.assertEqual(new['lease_generation'], 2)
        self.assertEqual(len(c.status(old['run_id'])['slots']),1)


    def test_integrator_expiry_reassigns_without_replaying_git(self):
        run = self.run_tasks()
        original = self.claim(run, 'integrator-old')
        result = c.finish(run,'integrator-old',commit_sha=self.commit(original),
                          lease_generation=original['lease_generation'])
        self.assertTrue(result['integrate_now'])
        with c._connection(write=True) as db:
            db.execute('UPDATE runs SET integrator_last_seen=? WHERE id=?',
                       (time.time()-601,run))
        new = c.reclaim_integrator(run,'integrator-new',integration_worktree=str(self.repo))
        self.assertEqual(new['integrator_generation'],2)
        with self.assertRaises(PermissionError):
            c.prepare_integration(run,'integrator-old',integration_worktree=str(self.repo))
        with self.assertRaises(PermissionError):
            c.heartbeat(run,'integrator-old',lease_generation=1)
        self.assertEqual(c.prepare_integration(run,'integrator-new',
                                               integration_worktree=str(self.repo))['status'],
                         'READY_FOR_TEST')
        with self.assertRaises(RuntimeError):
            c.prepare_integration(run,'integrator-new',integration_worktree=str(self.repo))
        c.integration_complete(run,'integrator-new',integration_worktree=str(self.repo),
                               test_evidence='merge verified')

    def test_integrator_takeover_requires_clean_target(self):
        run=self.run_tasks()
        original=self.claim(run,'owner')
        c.finish(run,'owner',commit_sha=self.commit(original))
        with c._connection(write=True) as db:
            db.execute('UPDATE runs SET integrator_last_seen=? WHERE id=?',
                       (time.time()-601,run))
        (self.repo/'untracked.txt').write_text('preserve')
        with self.assertRaisesRegex(RuntimeError,'dirty'):
            c.reclaim_integrator(run,'replacement',integration_worktree=str(self.repo))
        self.assertEqual((self.repo/'untracked.txt').read_text(),'preserve')

    def test_serial_tail_takeover_after_verified_integration(self):
        run=c.create_run(str(self.repo),'main',str(self.parent),
                         [{'key':'A','title':'A','instructions':'produce'}],
                         goal_key='serial-resume',serial_tail='run final review')['run_id']
        old=self.claim(run,'old-owner')
        c.finish(run,'old-owner',commit_sha=self.commit(old))
        c.prepare_integration(run,'old-owner',integration_worktree=str(self.repo))
        c.integration_complete(run,'old-owner',integration_worktree=str(self.repo),
                               test_evidence='post merge checked')
        with c._connection(write=True) as db:
            db.execute('UPDATE runs SET integrator_last_seen=? WHERE id=?',
                       (time.time()-601,run))
        moved=c.reclaim_integrator(run,'serial-rescuer',integration_worktree=str(self.repo))
        self.assertTrue(moved['serial_tail_active'])
        self.assertTrue(moved['reconcile_git_before_replay'])
        with self.assertRaises(PermissionError):
            c.serial_complete(run,'old-owner',integration_worktree=str(self.repo),
                              evidence='stale')
        done=c.serial_complete(run,'serial-rescuer',integration_worktree=str(self.repo),
                               evidence='verified final gates')
        self.assertEqual(done['serial_tail']['status'],'complete')

    def test_cli_publish_revise_heartbeat_and_checkpoint(self):
        run = self.run_tasks()
        old = self.claim(run, 'owner')
        task_file = self.root / 'next.json'
        task_file.write_text(json.dumps({'key':'B','pool':'qa','title':'review',
                                         'instructions':'check outcome','review_of':['A']}))
        cli = SCRIPT / 'codex_loop.py'
        def call(*argv):
            proc = subprocess.run([sys.executable,str(cli),'collab',*argv],
                                  text=True,capture_output=True,env=os.environ.copy())
            self.assertEqual(proc.returncode,0,proc.stderr)
            return json.loads(proc.stdout)['data']
        common=('--run-id',run,'--task-id','owner','--lease-generation',str(old['lease_generation']))
        result=call('publish',*common,'--task-file',str(task_file))
        changes=self.root / 'change.json'
        changes.write_text(json.dumps({'pool':'second-review'}))
        call('revise',*common,'--task-key','B','--expected-revision',
             str(result['graph_revision']),'--updates-file',str(changes))
        self.assertEqual(call('heartbeat',*common)['task_key'],'A')
        sha = self.commit(old)
        self.assertEqual(call('checkpoint',*common,'--commit-sha',sha,
                              '--note','verified initial output')['checkpoint_sha'],sha)


if __name__ == '__main__':
    unittest.main()

# Resource feedback is exercised at the SQLite boundary; the Logical Isolation
# abort is separately verified by the existing isolation integration surface.
def _test_resource_feedback(self):
    run = self.run_tasks([
        {'key':'gpu1','pool':'gpu','title':'GPU 1','instructions':'GPU'},
        {'key':'gpu2','pool':'gpu','title':'GPU 2','instructions':'GPU'},
        {'key':'gpu3','pool':'gpu','title':'GPU 3','instructions':'GPU'},
        {'key':'cpu1','pool':'cpu','title':'CPU','instructions':'CPU'},
        {'key':'cpu2','pool':'cpu','title':'CPU 2','instructions':'CPU'}])
    one = self.claim(run,'first')
    cpu = self.claim(run,'cpu-owner')
    two = self.claim(run,'second')
    self.assertEqual(one['pool'],'gpu')
    self.assertEqual(cpu['pool'],'cpu')
    self.assertEqual(two['pool'],'gpu')
    with mock.patch('codex_loop_runtime.collab_isolation.abort_resource_isolation'):
        released = c.resource_blocked(run,'second',slot_number=two['slot'],
            lease_generation=two['lease_generation'],resource_key='gpu',reason='GPU busy')
    self.assertEqual(released['observed_active'],1)
    self.assertEqual(released['learned_capacity'],1)
    other = self.claim(run,'second')
    self.assertEqual(other['pool'],'cpu')
    (Path(one['worktree']) / 'untracked').write_text('work in progress')
    with self.assertRaises(RuntimeError):
        c.resource_blocked(run,'first',slot_number=one['slot'],
            lease_generation=one['lease_generation'],resource_key='gpu',reason='dirty')
    (Path(one['worktree']) / 'untracked').unlink()
    c.finish(run,'first',commit_sha=self.commit(one),auto_claim=False,
             lease_generation=one['lease_generation'])
    next_gpu = self.claim(run,'third')
    self.assertEqual(next_gpu['pool'],'gpu')

AdaptiveCollaborationTest.test_resource_feedback_requeues_and_claims_other_pool = _test_resource_feedback


def _test_zero_peer_backoff(self):
    run = self.run_tasks([
        {'key':'gpu','pool':'gpu','title':'GPU','instructions':'GPU'}])
    assignment = self.claim(run,'owner')
    with mock.patch('codex_loop_runtime.collab_isolation.abort_resource_isolation'):
        report = c.resource_blocked(run,'owner',slot_number=assignment['slot'],
            lease_generation=assignment['lease_generation'],resource_key='gpu',reason='external GPU occupied')
    self.assertEqual(report['observed_active'],0)
    self.assertEqual(report['retry_after_seconds'],60)
    idle = c.claim(run,'other',worktree_parent=str(self.parent),wait_if_empty=True)
    self.assertEqual(idle['status'],'waiting')
    with c._connection(write=True) as db:
        db.execute('UPDATE resource_blocks SET retry_after=? WHERE run_id=?',
                   (time.time()-1,run))
    reclaimed = self.claim(run,'other')
    self.assertEqual(reclaimed['task_key'],'gpu')

AdaptiveCollaborationTest.test_zero_peer_resource_busy_uses_backoff = _test_zero_peer_backoff
