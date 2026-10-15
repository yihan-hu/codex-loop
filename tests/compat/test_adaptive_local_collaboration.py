"""Local adaptive DAG, stale lease takeover, and Git safety regression tests."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
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

    def test_checkpoint_survives_takeover_and_is_not_silently_replayed(self):
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
        self.assertFalse((Path(new['worktree']) / 'A.txt').exists())
        self.assertTrue((Path(old['worktree']) / 'A.txt').exists())

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
