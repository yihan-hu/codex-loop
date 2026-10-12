"""Same-host Worktree Collaboration: executable behavior and failure boundaries."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPT))
from codex_loop_runtime import local_collaboration as c
from codex_loop_runtime.repository_continuity import repository_enter


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(f"git {args} failed: {proc.stderr}")
    return proc.stdout.strip()


class CollaborationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        old = os.environ.get('CODEX_LOOP_HOME')
        self.addCleanup(lambda: os.environ.__setitem__('CODEX_LOOP_HOME', old) if old is not None else os.environ.pop('CODEX_LOOP_HOME', None))
        os.environ['CODEX_LOOP_HOME'] = str(self.root / 'state')
        self.repo = self.root / 'source'
        self.parent = self.root / 'workers'
        self.parent.mkdir()
        self.repo.mkdir()
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.name', 'Test')
        git(self.repo, 'config', 'user.email', 'test@example.org')
        git(self.repo, 'remote', 'add', 'origin', 'https://github.com/yihan-hu/fixture.git')
        (self.repo / 'shared.txt').write_text('start\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'initial')

    def create(self, n=2, strategy='detached'):
        tasks = [{'title': f'work {i}', 'instructions': f'Create file {i} and test'} for i in range(1, n+1)]
        return c.create_run(str(self.repo), 'main', str(self.parent), tasks,
                            strategy=strategy, goal_key='shared-engine')

    def commit(self, claimed, contents=None):
        root = Path(claimed['worktree'])
        (root / (f'slot-{claimed["slot"]}.txt')).write_text(contents or claimed['title'])
        git(root, 'add', '.')
        git(root, 'commit', '-m', f'slot {claimed["slot"]}')
        return git(root, 'rev-parse', 'HEAD')

    def test_planned_concurrent_claim_messages_and_last_finisher_integration(self):
        r = self.create(3)
        run = r['run_id']
        with ThreadPoolExecutor(max_workers=3) as executor:
            claimed = list(executor.map(lambda x: c.claim(run, f'task-{x}',worktree_parent=str(self.parent)), (1,2,3)))
        self.assertEqual({x['slot'] for x in claimed}, {1,2,3})
        with self.assertRaises(RuntimeError):
            c.claim(run,'task-4',worktree_parent=str(self.parent))
        ids={x['slot']:x for x in claimed}
        a=ids[1];b=ids[2];d=ids[3]
        repeated=c.claim(run,a['task_id'],worktree_parent=str(self.parent))
        self.assertEqual(a['slot'],repeated['slot'])
        mid=c.post_message(run,a['task_id'],'shared interface moved')['message_id']
        self.assertEqual([m['body'] for m in c.inbox(run,b['task_id'])['messages']], ['shared interface moved'])
        self.assertEqual([m['id'] for m in c.inbox(run,b['task_id'],ack=[mid])['messages']], [])
        self.assertEqual(len(c.inbox(run,d['task_id'])['messages']),1)
        commits={x['slot']:self.commit(x) for x in claimed}
        self.assertFalse(c.finish(run,a['task_id'],commit_sha=commits[1])['integrate_now'])
        self.assertFalse(c.finish(run,b['task_id'],commit_sha=commits[2])['integrate_now'])
        self.assertIsNone(c.completion_obstacle(a['task_id']))
        final=c.finish(run,d['task_id'],commit_sha=commits[3])
        self.assertTrue(final['integrate_now'])
        self.assertIn('integrator',c.completion_obstacle(d['task_id']))
        response=c.prepare_integration(run,d['task_id'],integration_worktree=str(self.repo))
        self.assertEqual(response['status'],'READY_FOR_TEST')
        for i in range(1,4):
            self.assertEqual((self.repo / f'slot-{i}.txt').read_text(),f'work {i}')
        done=c.integration_complete(run,d['task_id'],integration_worktree=str(self.repo),test_evidence='3 files checked')
        self.assertEqual(done['state'],'integrated')
        self.assertIsNone(c.completion_obstacle(d['task_id']))
        for i in range(1,4):
            self.assertEqual(git(self.repo,'rev-parse',f'refs/codex-loop/collab/{run}/slot-{i}'),commits[i])

    def test_all_slots_must_exist_before_election(self):
        run=self.create(2)['run_id']
        a=c.claim(run,'task-A',worktree_parent=str(self.parent))
        status=c.finish(run,'task-A',commit_sha=git(Path(a['worktree']),'rev-parse','HEAD'))
        self.assertFalse(status['integrate_now'])
        self.assertEqual(status['counts']['available'],1)
        self.assertEqual(c.status(run)['state'],'open')

    def test_simultaneous_finishes_only_elect_one(self):
        run=self.create(2)['run_id']
        a=c.claim(run,'task-A',worktree_parent=str(self.parent));b=c.claim(run,'task-B',worktree_parent=str(self.parent))
        sha_a=self.commit(a);sha_b=self.commit(b)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(c.finish,run,tid,commit_sha=sha) for tid,sha in [('task-A',sha_a),('task-B',sha_b)]]
            results=[f.result() for f in futures]
        self.assertEqual(sum(bool(x['integrate_now']) for x in results),1)
        self.assertEqual(c.status(run)['state'],'integrating')

    def test_dynamic_join_closed_cohort_and_idempotent_resume(self):
        kwargs=dict(repo=str(self.repo),target_branch='main',worktree_parent=str(self.parent),goal_key='same-goal',instructions='edit and commit')
        a=c.dynamic_join(task_id='dyn-A',title='A',**kwargs)
        b=c.dynamic_join(task_id='dyn-B',title='B',**kwargs)
        self.assertEqual(a['run_id'],b['run_id'])
        run=a['run_id']
        c.finish(run,a['task_id'],commit_sha=self.commit(a))
        self.assertTrue(c.finish(run,b['task_id'],commit_sha=self.commit(b))['integrate_now'])
        resumed=c.dynamic_join(task_id='dyn-A',title='A',**kwargs)
        self.assertEqual(resumed['run_id'],run)
        newer=c.dynamic_join(task_id='dyn-C',title='C',**kwargs)
        self.assertNotEqual(newer['run_id'],run)

    def test_private_branches(self):
        run=self.create(2,strategy='branches')['run_id']
        a=c.claim(run,'branch-A',worktree_parent=str(self.parent))
        b=c.claim(run,'branch-B',worktree_parent=str(self.parent))
        self.assertEqual(git(Path(a['worktree']),'symbolic-ref','--short','HEAD'),f'codex-loop/{run}/slot-1')
        self.assertEqual(git(Path(b['worktree']),'symbolic-ref','--short','HEAD'),f'codex-loop/{run}/slot-2')
        self.assertEqual(git(self.repo,'symbolic-ref','--short','HEAD'),'main')

    def test_dirty_worker_or_dirty_integration_target_stops_mutation(self):
        run=self.create(1)['run_id']
        a=c.claim(run,'task-A',worktree_parent=str(self.parent))
        (Path(a['worktree'])/'dirty.txt').write_text('do not erase')
        with self.assertRaises(RuntimeError):
            c.finish(run,a['task_id'],commit_sha=git(Path(a['worktree']),'rev-parse','HEAD'))
        git(Path(a['worktree']),'add','dirty.txt');git(Path(a['worktree']),'commit','-m','save')
        c.finish(run,a['task_id'],commit_sha=git(Path(a['worktree']),'rev-parse','HEAD'))
        (self.repo/'untracked.txt').write_text('protected')
        with self.assertRaises(RuntimeError):
            c.prepare_integration(run,a['task_id'],integration_worktree=str(self.repo))
        self.assertEqual((self.repo/'untracked.txt').read_text(),'protected')
        (self.repo/'untracked.txt').unlink()
        self.assertEqual(c.prepare_integration(run,a['task_id'],integration_worktree=str(self.repo))['status'],'READY_FOR_TEST')

    def test_conflict_requires_resolution_and_no_replay(self):
        run=self.create(2)['run_id']
        a=c.claim(run,'task-A',worktree_parent=str(self.parent));b=c.claim(run,'task-B',worktree_parent=str(self.parent))
        for work,text in [(a,'alpha\n'),(b,'beta\n')]:
            path=Path(work['worktree'])
            (path/'shared.txt').write_text(text)
            git(path,'add','shared.txt');git(path,'commit','-m',text.strip())
        c.finish(run,a['task_id'],commit_sha=git(Path(a['worktree']),'rev-parse','HEAD'))
        c.finish(run,b['task_id'],commit_sha=git(Path(b['worktree']),'rev-parse','HEAD'))
        result=c.prepare_integration(run,b['task_id'],integration_worktree=str(self.repo))
        self.assertEqual(result['status'],'CONFLICT_OR_INTERRUPTED')
        with self.assertRaises(RuntimeError):
            c.prepare_integration(run,b['task_id'],integration_worktree=str(self.repo))
        (self.repo/'shared.txt').write_text('alpha\nbeta\n')
        git(self.repo,'add','shared.txt');git(self.repo,'cherry-pick','--continue')
        ok=c.integration_resolved(run,b['task_id'],integration_worktree=str(self.repo),resolution_evidence='both lines preserved and cherry-pick completed')
        self.assertEqual(ok['status'],'READY_FOR_TEST')
        c.integration_complete(run,b['task_id'],integration_worktree=str(self.repo),test_evidence='resolved text checked')
        self.assertEqual((self.repo/'shared.txt').read_text(),'alpha\nbeta\n')

    def test_cli_create_claim_inbox_finish_elect_and_integrate(self):
        import json
        cli=SCRIPT/'codex_loop.py'
        tasks_file=self.root/'tasks.json'
        tasks_file.write_text(json.dumps([{'title':'add minimal task','instructions':'Verify git status and submit'}]))
        def call(*args):
            p=subprocess.run([sys.executable,str(cli),'collab',*args],capture_output=True,text=True,env=os.environ.copy())
            if p.returncode:
                raise AssertionError(f'CLI {args} failed: {p.stderr} {p.stdout}')
            return json.loads(p.stdout)['data']
        result=call('create','--repo',str(self.repo),'--branch','main','--goal-key','cli-demo',
                    '--worktree-parent',str(self.parent),'--tasks-file',str(tasks_file))
        run=result['run_id']
        worker=call('claim','--run-id',run,'--task-id','cli-worker',
                    '--worktree-parent',str(self.parent))
        self.assertEqual(worker['title'],'add minimal task')
        self.assertIsNotNone(worker['source_provenance'])
        self.assertEqual(call('inbox','--run-id',run,'--task-id','cli-worker')['messages'],[])
        result=call('finish','--run-id',run,'--task-id','cli-worker','--commit-sha',
                    git(Path(worker['worktree']),'rev-parse','HEAD'))
        self.assertTrue(result['integrate_now'])
        self.assertEqual(call('integrate','--run-id',run,'--task-id','cli-worker',
                              '--integration-worktree',str(self.repo))['status'],'READY_FOR_TEST')
        result=call('integration-complete','--run-id',run,'--task-id','cli-worker',
                    '--integration-worktree',str(self.repo),'--test-evidence','clean git tree')
        self.assertEqual(result['state'],'integrated')

    def test_manual_resolution_rejects_missing_later_worker(self):
        run=self.create(3)['run_id']
        workers=[c.claim(run,f'job-{i}',worktree_parent=str(self.parent)) for i in range(1,4)]
        for w,text in [(workers[0],'A\n'),(workers[1],'B\n')]:
            root=Path(w['worktree']);(root/'shared.txt').write_text(text)
            git(root,'add','shared.txt');git(root,'commit','-m',f'different-{w["slot"]}')
        self.commit(workers[2])
        for w in workers:
            c.finish(run,w['task_id'],commit_sha=git(Path(w['worktree']),'rev-parse','HEAD'))
        r=c.prepare_integration(run,workers[2]['task_id'],integration_worktree=str(self.repo))
        self.assertEqual(r['status'],'CONFLICT_OR_INTERRUPTED')
        (self.repo/'shared.txt').write_text('A\nB\n')
        git(self.repo,'add','shared.txt');git(self.repo,'cherry-pick','--continue')
        with self.assertRaisesRegex(RuntimeError,'worker commits not yet merged'):
            c.integration_resolved(run,workers[2]['task_id'],integration_worktree=str(self.repo),
                                   resolution_evidence='conflict resolved but third worker omitted')
        third_sha=git(Path(workers[2]['worktree']),'rev-parse','HEAD')
        git(self.repo,'cherry-pick','-x',third_sha)
        result=c.integration_resolved(run,workers[2]['task_id'],integration_worktree=str(self.repo),
                                     resolution_evidence='both changed lines plus third worker checked')
        self.assertEqual(result['status'],'READY_FOR_TEST')

    def test_detached_continuity_requires_verified_target_provenance(self):
        run=self.create(1)['run_id'];worker=c.claim(run,'worker-A',worktree_parent=str(self.parent))
        root=Path(worker['worktree'])
        base=git(root,'rev-parse','HEAD');tree=git(root,'rev-parse','HEAD^{tree}')
        result=repository_enter(root,repository='yihan-hu/fixture',branch='main',remote_head=base,remote_tree=tree)
        self.assertNotEqual(result['status'],'HOT_REUSE')
        provenance={'kind':'codex_loop_source_provenance','schema_version':1,'verified':True,
                    'path_bound':False,'repository':'yihan-hu/fixture','origin_hint':'github.com/yihan-hu/fixture',
                    'branch':'main','base_commit':base,'base_tree':tree}
        result=repository_enter(root,repository='yihan-hu/fixture',branch='main',source_provenance=provenance,remote_head=base,remote_tree=tree)
        self.assertEqual(result['status'],'HOT_REUSE')
        self.assertTrue(result['workspace_lease']['detached_worker'])
        self.assertIsNone(result['workspace_lease']['checked_out_branch'])


    def test_delegation_directed_accept_complete_idempotent_and_election(self):
        run=self.create(2)['run_id']
        a=c.claim(run,'task-A',worktree_parent=str(self.parent))
        b=c.claim(run,'task-B',worktree_parent=str(self.parent))
        item=c.delegate(run,'task-A',request_key='share-1',title='training interface',
                        instructions='Implement a compatible training adapter',recipient_task='task-B')
        self.assertEqual(item['status'],'offered')
        self.assertEqual(c.delegate(run,'task-A',request_key='share-1',title='training interface',
                        instructions='Implement a compatible training adapter',recipient_task='task-B')['id'],item['id'])
        with self.assertRaises(RuntimeError):
            c.delegate(run,'task-A',request_key='share-1',title='changed work',instructions='different')
        self.assertEqual(c.inbox(run,'task-B')['delegations'][0]['id'],item['id'])
        self.assertEqual(c.accept_delegation(run,'task-B',delegation_id=item['id'])['status'],'accepted')
        self.assertEqual(c.accept_delegation(run,'task-B',delegation_id=item['id'])['status'],'accepted')
        with self.assertRaises(RuntimeError):
            c.finish(run,'task-B',commit_sha=git(Path(b['worktree']),'rev-parse','HEAD'))
        self.assertIn('await completion',c.completion_obstacle('task-A'))
        self.assertFalse(c.finish(run,'task-A',commit_sha=self.commit(a))['integrate_now'])
        sha=self.commit(b)
        self.assertEqual(c.complete_delegation(run,'task-B',delegation_id=item['id'],
                                              result='adapter committed',commit_sha=sha)['status'],'completed')
        self.assertEqual(c.complete_delegation(run,'task-B',delegation_id=item['id'],
                                              result='adapter committed',commit_sha=sha)['status'],'completed')
        self.assertIsNone(c.completion_obstacle('task-A'))
        self.assertTrue(c.finish(run,'task-B',commit_sha=sha)['integrate_now'])
        self.assertTrue(c.inbox(run,'task-A')['messages'])
        self.assertEqual(c.status(run)['state'],'integrating')

    def test_delegation_reject_reoffer_then_cancel_after_finished_slots_elects(self):
        run=self.create(2)['run_id']
        a=c.claim(run,'task-A',worktree_parent=str(self.parent))
        b=c.claim(run,'task-B',worktree_parent=str(self.parent))
        item=c.delegate(run,'task-A',request_key='share-rej',title='analyze issue',
                        instructions='Inspect source and report',recipient_task='task-B')
        did=item['id']
        self.assertEqual(c.reject_delegation(run,'task-B',delegation_id=did,reason='wrong expertise')['status'],'rejected')
        with self.assertRaises(PermissionError):
            c.reoffer_delegation(run,'task-B',delegation_id=did)
        self.assertEqual(c.reoffer_delegation(run,'task-A',delegation_id=did)['status'],'offered')
        with self.assertRaises(PermissionError):
            c.cancel_delegation(run,'task-B',delegation_id=did,reason='not needed')
        self.assertEqual(c.accept_delegation(run,'task-B',delegation_id=did)['status'],'accepted')
        self.assertEqual(c.reject_delegation(run,'task-B',delegation_id=did,reason='cannot finish')['status'],'rejected')
        c.finish(run,'task-A',commit_sha=self.commit(a))
        outcome=c.finish(run,'task-B',commit_sha=self.commit(b))
        self.assertFalse(outcome['integrate_now'])
        self.assertEqual(c.status(run)['state'],'open')
        self.assertTrue(outcome['pending_delegations'])
        withdrawn=c.cancel_delegation(run,'task-A',delegation_id=did,reason='not necessary')
        self.assertEqual(withdrawn['status'],'cancelled')
        self.assertTrue(withdrawn['election']['integrate_now'])
        self.assertEqual(c.status(run)['integrator_task'],'task-A')
        self.assertIn('integrator has not completed', c.completion_obstacle('task-A'))

    def test_pool_delegate_claims_new_worktree_after_planned_slots_taken(self):
        run=self.create(1)['run_id']
        a=c.claim(run,'task-A',worktree_parent=str(self.parent))
        item=c.delegate(run,'task-A',request_key='pool-1',title='second worker',
                        instructions='Separate test or source change')
        self.assertIsNone(item['recipient'])
        result=c.finish(run,'task-A',commit_sha=self.commit(a))
        self.assertFalse(result['integrate_now'])
        b=c.claim(run,'task-B',worktree_parent=str(self.parent))
        self.assertEqual(b['title'],'second worker')
        self.assertNotEqual(b['worktree'],a['worktree'])
        self.assertEqual(c.status(run)['delegations'][0]['recipient'],'task-B')
        self.assertEqual(c.status(run)['delegations'][0]['status'],'accepted')
        self.assertTrue(c.inbox_for_task('task-B')[0]['delegations'])
        sha=self.commit(b)
        c.complete_delegation(run,'task-B',delegation_id=item['id'],result='done',commit_sha=sha)
        self.assertTrue(c.finish(run,'task-B',commit_sha=sha)['integrate_now'])

    def test_delegation_concurrent_claim_one_winner_and_auth_boundary(self):
        run=self.create(3)['run_id']
        a,b,cc=[c.claim(run,k,worktree_parent=str(self.parent)) for k in ('task-A','task-B','task-C')]
        item=c.delegate(run,'task-A',request_key='race',title='test race',instructions='Review')
        did=item['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            fs=[pool.submit(c.accept_delegation,run,k,delegation_id=did) for k in ('task-B','task-C')]
            outcomes=[]
            for f in fs:
                try: outcomes.append(f.result())
                except (RuntimeError,PermissionError): pass
        self.assertEqual(len(outcomes),1)
        owner=outcomes[0]['recipient']
        other='task-C' if owner=='task-B' else 'task-B'
        with self.assertRaises(PermissionError):
            c.complete_delegation(run,other,delegation_id=did,result='fraud')
        with self.assertRaises(RuntimeError):
            c.complete_delegation(run,owner,delegation_id=did,result='fraud',commit_sha='f'*40)
        with self.assertRaises(KeyError):
            c.delegate(run,'task-A',request_key='different-recipient',title='work',
                       instructions='Read',recipient_task='not-in-run')

    def test_completed_delegation_commit_must_survive_worker_finish(self):
        run=self.create(2)['run_id']
        a=c.claim(run,'task-A',worktree_parent=str(self.parent))
        b=c.claim(run,'task-B',worktree_parent=str(self.parent))
        offer=c.delegate(run,'task-A',request_key='must-survive',title='create artifact',
                         instructions='Write and commit an artifact',recipient_task='task-B')
        c.accept_delegation(run,'task-B',delegation_id=offer['id'])
        reported=self.commit(b)
        c.complete_delegation(run,'task-B',delegation_id=offer['id'],result='finished',commit_sha=reported)
        git(Path(b['worktree']),'reset','--hard',git(self.repo,'rev-parse','main'))
        with self.assertRaisesRegex(RuntimeError,'missing from final worker HEAD'):
            c.finish(run,'task-B',commit_sha=git(Path(b['worktree']),'rev-parse','HEAD'))

    def test_delegation_cli_end_to_end(self):
        import json
        cli=SCRIPT/'codex_loop.py'
        def call(*args):
            p=subprocess.run([sys.executable,str(cli),'collab',*args],capture_output=True,text=True,env=os.environ.copy())
            if p.returncode:
                raise AssertionError(f'CLI {args} failed: {p.stderr} {p.stdout}')
            return json.loads(p.stdout)['data']
        run=self.create(2)['run_id']
        a=call('claim','--run-id',run,'--task-id','task-A','--worktree-parent',str(self.parent))
        b=call('claim','--run-id',run,'--task-id','task-B','--worktree-parent',str(self.parent))
        item=call('delegate','--run-id',run,'--task-id','task-A','--request-key','cli-job',
                  '--title','update code','--instructions','Implement and test','--to-task','task-B')
        self.assertEqual(call('delegation-accept','--run-id',run,'--task-id','task-B',
                              '--delegation-id',str(item['id']))['status'],'accepted')
        sha=self.commit(b)
        self.assertEqual(call('delegation-complete','--run-id',run,'--task-id','task-B',
                              '--delegation-id',str(item['id']),'--result','committed',
                              '--commit-sha',sha)['status'],'completed')
        self.assertEqual(call('status','--run-id',run)['delegations'][0]['status'],'completed')
        self.assertTrue(call('inbox','--run-id',run,'--task-id','task-A')['messages'])


if __name__=='__main__':
    unittest.main()
