"""End-to-end Local Slot logical isolation through the real Codex Loop CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from codex_loop_runtime import local_collaboration as collab, collab_isolation
from codex_loop_runtime.state import create_store,open_store
from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.write_transaction import guarded_write


def git(root,*args):
    p=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True)
    if p.returncode:raise RuntimeError(p.stderr)
    return p.stdout.strip()


class SlotLogicalIsolationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.repo=self.root/'repo'
        self.repo.mkdir()
        self.parent=self.root/'workers'
        self.parent.mkdir()
        self.home=self.root/'state'
        old=os.environ.get('CODEX_LOOP_HOME')
        os.environ['CODEX_LOOP_HOME']=str(self.home)
        self.addCleanup(lambda: os.environ.pop('CODEX_LOOP_HOME',None) if old is None
                        else os.environ.__setitem__('CODEX_LOOP_HOME',old))
        git(self.repo,'init','-b','main')
        git(self.repo,'config','user.name','Test')
        git(self.repo,'config','user.email','test@example.org')
        (self.repo/'start.txt').write_text('baseline')
        git(self.repo,'add','.')
        git(self.repo,'commit','-m','baseline')

    def worker(self,marker: str):
        tid=marker*32
        store=create_store(self.repo,task_id=tid)
        store.configure_task(tid,request_anchor='Process the assigned collaboration task')
        capture_baseline(self.repo,store)
        return tid,store

    def cli(self,action,*opts,expect_ok=True,stdin=None):
        proc=subprocess.run([sys.executable,str(ROOT/'scripts'/'codex_loop.py'),
                             'collab',action,*[str(x) for x in opts]],
                            input=stdin,text=True,capture_output=True)
        try:
            data=json.loads(proc.stdout)
        except Exception as exc:
            raise AssertionError(f'bad CLI output: {proc.stdout}\n{proc.stderr}') from exc
        if expect_ok:
            self.assertEqual(proc.returncode,0,repr(data))
            self.assertTrue(data['ok'],repr(data))
            return data['data']
        self.assertNotEqual(proc.returncode,0,repr(data))
        self.assertFalse(data['ok'],repr(data))
        return data['error']

    def claim(self,run,tid):
        return self.cli('claim','--run-id',run,'--task-id',tid,
                        '--worktree-parent',str(self.parent))

    def new_run(self,tasks):
        return collab.create_run(str(self.repo),'main',str(self.parent),tasks,
                                 goal_key='slot-iso-tests')['run_id']

    def commit(self,assignment):
        wt=Path(assignment['worktree'])
        (wt/f"{assignment['task_key']}.txt").write_text(assignment['task_key'])
        git(wt,'add','.')
        git(wt,'commit','-m',assignment['task_key'])
        return git(wt,'rev-parse','HEAD')

    def finish(self,run,tid,assignment,sha):
        return self.cli('finish','--run-id',run,'--task-id',tid,
                        '--slot',assignment['slot'],
                        '--lease-generation',assignment['lease_generation'],
                        '--commit-sha',sha)

    def test_claim_finish_auto_claim_reuses_original_logical_isolation(self):
        run=self.new_run([{'key':'A','title':'Foundation','instructions':'Produce A'},
                          {'key':'B','title':'Followup','instructions':'Produce B','depends_on':['A']}])
        tid,store=self.worker('a')
        first=self.claim(run,tid)
        iso=first['logical_isolation']
        self.assertEqual(iso['executor']['kind'],'logical_isolation')
        self.assertEqual(iso['mutation_policy'],'workspace_write')
        self.assertEqual(iso['collaboration']['slot'],first['slot'])
        self.assertFalse(iso['executor']['physical_context_isolation'])
        self.assertEqual(store.active_isolation()['isolation_id'],iso['isolation_id'])
        retry=self.claim(run,tid)
        self.assertEqual(retry['logical_isolation']['isolation_id'],iso['isolation_id'])
        self.assertTrue(retry['logical_isolation']['reused'])
        self.assertEqual(len(store.isolation_history()),1)
        receipt=self.finish(run,tid,first,self.commit(first))
        self.assertTrue(receipt['continue_now'])
        nxt=receipt['next_task']
        self.assertEqual(nxt['task_key'],'B')
        self.assertNotEqual(nxt['logical_isolation']['isolation_id'],iso['isolation_id'])
        self.assertEqual(nxt['task_id'],tid)
        self.assertEqual(nxt['worktree'],first['worktree'])
        statuses=[r['status'] for r in store.isolation_history()]
        self.assertEqual(statuses,['active','finished'])
        self.assertEqual(self.claim(run,tid)['logical_isolation']['isolation_id'],
                         nxt['logical_isolation']['isolation_id'])
        finished=self.finish(run,tid,nxt,self.commit(nxt))
        self.assertTrue(finished['integrate_now'])
        self.assertIsNone(store.active_isolation())
        self.assertEqual([x['status'] for x in store.isolation_history()],
                         ['finished','finished'])

    def test_writable_slot_guarded_write_is_limited_to_its_assigned_worktree(self):
        run=self.new_run([{'key':'W','title':'Writable','instructions':'Produce result'}])
        tid,store=self.worker('w')
        a=self.claim(run,tid)
        with self.assertRaisesRegex(PermissionError,'own worktree'):
            guarded_write(self.repo,store,self.repo/'unexpected.txt',b'wrong location')
        path=Path(a['worktree'])/'allowed.txt'
        result=guarded_write(Path(a['worktree']),store,path,b'correct location')
        self.assertEqual(path.read_bytes(),b'correct location')
        self.assertEqual(result.path,str(path))
        self.finish(run,tid,a,self.commit(a))

    def test_unrelated_active_isolation_rejects_claim_before_slot_reservation(self):
        from codex_loop_runtime.delegation import create_isolation, abort_isolation
        run=self.new_run([{'key':'A','title':'A','instructions':'Task A'}])
        tid,store=self.worker('t')
        existing=create_isolation(self.repo,self.repo,store,role='reviewer',
                                  objective='Independent pre-existing review',
                                  requested_executor='logical_isolation')
        error=self.cli('claim','--run-id',run,'--task-id',tid,
                       '--worktree-parent',self.parent,expect_ok=False)
        self.assertIn('unrelated Logical Isolation',error['message'])
        state=collab.status(run)
        self.assertEqual(state['slots'][0]['status'],'available')
        self.assertIsNone(state['slots'][0]['worktree'])
        abort_isolation(self.repo,self.repo,store,existing['isolation_id'],
                        'Complete the previous review separately')
        claimed=self.claim(run,tid)
        self.assertEqual(claimed['logical_isolation']['status'],'active')

    def test_waiting_never_enters_isolation(self):
        run=self.new_run([{'key':'A','title':'A','instructions':'A'},
                          {'key':'B','title':'B','instructions':'B','depends_on':['A']}])
        first_id,_=self.worker('a')
        waiter_id,store=self.worker('b')
        self.claim(run,first_id)
        waiting=self.cli('claim','--run-id',run,'--task-id',waiter_id,
                         '--worktree-parent',self.parent,'--wait',
                         '--poll-interval','0.01','--max-wait-seconds','0.03')
        self.assertEqual(waiting['status'],'waiting')
        self.assertNotIn('logical_isolation',waiting)
        self.assertIsNone(store.active_isolation())

    def test_semantic_slot_uses_same_isolation_with_strict_semantic_result(self):
        run=self.new_run([{'key':'S','title':'Semantic review','instructions':'Review input.',
            'isolation':{
               'semantic_work':{'consumer':'unit-test','stage':'semantic-review',
                                'input_sha256':'a'*64,'instruction_sha256':'b'*64}
            }}])
        tid,store=self.worker('s')
        assignment=self.claim(run,tid)
        iso=assignment['logical_isolation']
        self.assertEqual(iso['role'],'semantic-worker')
        self.assertEqual(iso['mutation_policy'],'read_only')
        self.assertEqual(iso['semantic_work']['authority'],'logical_isolation_only')
        wrong=self.cli('finish','--run-id',run,'--task-id',tid,
                       '--slot',assignment['slot'],'--lease-generation',
                       assignment['lease_generation'],
                       '--commit-sha',git(assignment['worktree'],'rev-parse','HEAD'),
                       expect_ok=False)
        self.assertIn('semantic-work-finish',wrong['message'])
        self.assertEqual(collab.status(run)['slots'][0]['status'],'claimed')
        stage=subprocess.run([sys.executable,str(ROOT/'scripts'/'codex_loop.py'),
             'semantic-work-finish','--task-id',tid,'--cwd',str(self.repo),
             '--isolation-id',iso['isolation_id']],
             input=json.dumps({'status':'PASS','review':'performed by model'}),text=True,
             capture_output=True)
        self.assertEqual(stage.returncode,0,stage.stdout+stage.stderr)
        self.assertTrue(json.loads(stage.stdout)['ok'])
        self.assertIsNone(store.active_isolation())
        retry=self.claim(run,tid)
        self.assertEqual(retry['logical_isolation']['isolation_id'],iso['isolation_id'])
        self.assertTrue(retry['logical_isolation']['reused'])
        result=self.finish(run,tid,assignment,git(assignment['worktree'],'rev-parse','HEAD'))
        self.assertTrue(result['integrate_now'])
        self.assertEqual(len(store.isolation_history()),1)

    def test_reclaim_new_worker_gets_distinct_logical_isolation(self):
        run=self.new_run([{'key':'A','title':'Original work','instructions':'Start then resume'}])
        old_tid,old_store=self.worker('a')
        new_tid,new_store=self.worker('b')
        former=self.claim(run,old_tid)
        (Path(former['worktree'])/'partial.txt').write_text('unfinished')
        with collab._connection(write=True) as db:
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=?',(time.time()-601,run))
        new=self.claim(run,new_tid)
        self.assertEqual((Path(new['worktree'])/'partial.txt').read_text(),'unfinished')
        self.assertNotEqual(former['logical_isolation']['isolation_id'],
                            new['logical_isolation']['isolation_id'])
        self.assertEqual(new['logical_isolation']['collaboration']['lease_generation'],
                         new['lease_generation'])
        self.assertEqual(old_store.active_isolation()['status'],'active')
        self.assertEqual(new_store.active_isolation()['status'],'active')

    def test_semantic_slot_rejects_mutation_in_its_actual_worker_worktree(self):
        run=self.new_run([{'key':'S','title':'Semantic review','instructions':'Evaluate without edits',
            'isolation':{'semantic_work':{
                'consumer':'test','stage':'review',
                'input_sha256':'a'*64,'instruction_sha256':'b'*64}}}])
        tid,store=self.worker('s')
        assignment=self.claim(run,tid)
        iso=assignment['logical_isolation']
        (Path(assignment['worktree'])/'unexpected.txt').write_text('mutated during review')
        stage=subprocess.run([sys.executable,str(ROOT/'scripts'/'codex_loop.py'),
            'semantic-work-finish','--task-id',tid,'--cwd',str(self.repo),
            '--isolation-id',iso['isolation_id']],
            input=json.dumps({'status':'PASS'}),text=True,capture_output=True)
        self.assertNotEqual(stage.returncode,0,stage.stdout)
        self.assertIn('Slot worktree changed',stage.stdout)
        self.assertIsNotNone(store.active_isolation())

    def test_generic_readonly_and_custom_reviewer_role_use_existing_isolation(self):
        run=self.new_run([{'key':'R','title':'Review evidence','instructions':'Review only',
                           'isolation':{'role':'reviewer','mutation_policy':'read_only'}}])
        tid,store=self.worker('r')
        assignment=self.claim(run,tid)
        iso=assignment['logical_isolation']
        self.assertEqual(iso['role'],'reviewer')
        self.assertEqual(iso['mutation_policy'],'read_only')
        self.assertIn('read-only',iso['guardrails'])
        with self.assertRaisesRegex(PermissionError,'read-only'):
            guarded_write(self.repo,store,self.repo/'forbidden.txt',b'forbidden')
        premature=self.cli('finish','--run-id',run,'--task-id',tid,'--slot',assignment['slot'],
                     '--lease-generation',assignment['lease_generation'],
                     '--commit-sha',git(assignment['worktree'],'rev-parse','HEAD'),expect_ok=False)
        self.assertIn('isolate-finish',premature['message'])
        review={'summary':'Reviewed the specified input','findings':[],
                'recommended_action':'finish','files_inspected':[],'limitations':[]}
        completed=subprocess.run([sys.executable,str(ROOT/'scripts'/'codex_loop.py'),
              'isolate-finish','--task-id',tid,'--cwd',str(self.repo),
              '--isolation-id',iso['isolation_id']],input=json.dumps(review),
              capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stdout)
        result=self.finish(run,tid,assignment,git(assignment['worktree'],'rev-parse','HEAD'))
        self.assertTrue(result['integrate_now'])
        self.assertEqual(store.isolation_history()[0]['status'],'finished')

    def test_retrying_prior_finish_does_not_reset_next_slot_context(self):
        run=self.new_run([{'key':'A','title':'First','instructions':'First'},
                          {'key':'B','title':'Next','instructions':'Next','depends_on':['A']}])
        tid,store=self.worker('r')
        a=self.claim(run,tid)
        sha=self.commit(a)
        first=self.finish(run,tid,a,sha)
        next_iso=first['next_task']['logical_isolation']['isolation_id']
        retry=self.finish(run,tid,a,sha)
        self.assertTrue(retry['already_finished'])
        self.assertTrue(retry['continue_now'])
        self.assertEqual(retry['next_task']['task_key'],'B')
        self.assertEqual(retry['next_task']['logical_isolation']['isolation_id'],next_iso)
        self.assertEqual(store.active_isolation()['isolation_id'],next_iso)
        self.assertEqual(len(store.isolation_history()),2)

    def test_dynamic_task_isolation_spec_is_preserved(self):
        run=self.new_run([{'key':'A','title':'A','instructions':'A'}])
        tid,_=self.worker('r')
        reviewer,store=self.worker('s')
        assignment=self.claim(run,tid)
        collab.publish_task(run,tid,{
            'key':'R','title':'Review','instructions':'Review output',
            'depends_on':['A'], 'review_of':['A'],
            'isolation':{'role':'reviewer','mutation_policy':'read_only'}
        },lease_generation=assignment['lease_generation'])
        self.finish(run,tid,assignment,self.commit(assignment))
        next_assignment=self.claim(run,reviewer)
        self.assertEqual(next_assignment['task_key'],'R')
        self.assertEqual(next_assignment['logical_isolation']['role'],'reviewer')
        self.assertEqual(next_assignment['logical_isolation']['mutation_policy'],'read_only')
        self.assertIsNotNone(store.active_isolation())

    def test_manual_isolate_finish_is_reused_until_slot_finishes(self):
        run=self.new_run([{'key':'A','title':'Review','instructions':'No changes',
                           'isolation':{'role':'reviewer','mutation_policy':'read_only'}}])
        tid,store=self.worker('r')
        assignment=self.claim(run,tid)
        iso_id=assignment['logical_isolation']['isolation_id']
        review={
            'summary':'Reviewed evidence','findings':[],'recommended_action':'accept',
            'files_inspected':[],'limitations':[],
        }
        completed=subprocess.run([sys.executable,str(ROOT/'scripts'/'codex_loop.py'),
              'isolate-finish','--task-id',tid,'--cwd',str(self.repo),
              '--isolation-id',iso_id],input=json.dumps(review),capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stdout)
        repeat=self.claim(run,tid)
        self.assertTrue(repeat['logical_isolation']['reused'])
        self.assertEqual(repeat['logical_isolation']['isolation_id'],iso_id)
        self.assertEqual(len(store.isolation_history()),1)
        self.finish(run,tid,assignment,git(assignment['worktree'],'rev-parse','HEAD'))
        self.assertEqual(len(store.isolation_history()),1)

    def test_aborted_semantic_isolation_cannot_be_bypassed_by_collab_finish(self):
        run=self.new_run([{'key':'S','title':'Semantic','instructions':'Review',
            'isolation':{'semantic_work':{'consumer':'unit','stage':'review',
                          'input_sha256':'a'*64,'instruction_sha256':'b'*64}}}])
        tid,store=self.worker('s')
        assignment=self.claim(run,tid)
        aborted=subprocess.run([sys.executable,str(ROOT/'scripts'/'codex_loop.py'),
             'isolate-abort','--task-id',tid,'--cwd',str(self.repo),
             '--isolation-id',assignment['logical_isolation']['isolation_id'],
             '--reason','test aborted semantic stage'],capture_output=True,text=True)
        self.assertEqual(aborted.returncode,0,aborted.stdout)
        invalid=self.cli('finish','--run-id',run,'--task-id',tid,
                         '--slot',assignment['slot'],'--lease-generation',
                         assignment['lease_generation'],
                         '--commit-sha',git(assignment['worktree'],'rev-parse','HEAD'),
                         expect_ok=False)
        self.assertIn('Logical Isolation',invalid['message'])
        self.assertEqual(collab.status(run)['slots'][0]['status'],'claimed')
        resumed=self.claim(run,tid)
        self.assertNotEqual(resumed['logical_isolation']['isolation_id'],
                            assignment['logical_isolation']['isolation_id'])

    def test_original_after_reclaim_can_finish_and_close_prior_isolation(self):
        run=self.new_run([{'key':'A','title':'Task','instructions':'Task'}])
        old_tid,old_store=self.worker('a')
        new_tid,new_store=self.worker('b')
        old=self.claim(run,old_tid)
        old_sha=self.commit(old)
        with collab._connection(write=True) as db:
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=?',(time.time()-601,run))
        newcomer=self.claim(run,new_tid)
        completed=self.finish(run,old_tid,old,old_sha)
        self.assertEqual(completed['status'],'accepted')
        self.assertEqual(completed['stopped_worker'],new_tid)
        self.assertIsNone(old_store.active_isolation())
        self.assertEqual(old_store.isolation_history()[0]['status'],'finished')
        self.assertIsNotNone(new_store.active_isolation())

    def test_late_result_preserved_aborts_original_scope(self):
        run=self.new_run([{'key':'A','title':'Task','instructions':'Task'}])
        old_tid,old_store=self.worker('a')
        new_tid,_=self.worker('b')
        old=self.claim(run,old_tid)
        old_sha=self.commit(old)
        with collab._connection(write=True) as db:
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=?',(time.time()-601,run))
        newcomer=self.claim(run,new_tid)
        new_root=Path(newcomer['worktree'])
        (new_root/'new-owner-result.txt').write_text('completed by successor')
        git(new_root,'add','new-owner-result.txt')
        git(new_root,'commit','-m','new owner finishes')
        new_sha=git(new_root,'rev-parse','HEAD')
        accepted=self.finish(run,new_tid,newcomer,new_sha)
        self.assertTrue(accepted['integrate_now'])
        late=self.finish(run,old_tid,old,old_sha)
        self.assertEqual(late['status'],'preserved')
        self.assertIsNone(old_store.active_isolation())
        self.assertEqual(old_store.isolation_history()[0]['status'],'aborted')

    def test_claim_isolation_init_failure_is_retryable_without_releasing_slot(self):
        run=self.new_run([{'key':'A','title':'Task','instructions':'Task scope'}])
        tid,store=self.worker('r')
        reserved=collab.claim(run,tid,worktree_parent=str(self.parent))
        with mock.patch.object(collab_isolation,'create_isolation',
                               side_effect=RuntimeError('injected setup failure')):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                collab_isolation.enter_assignment(reserved)
        self.assertIsNone(store.active_isolation())
        self.assertEqual(collab.status(run)['slots'][0]['status'],'claimed')
        recovered=self.claim(run,tid)
        self.assertEqual(recovered['slot'],reserved['slot'])
        self.assertEqual(recovered['lease_generation'],reserved['lease_generation'])
        self.assertTrue(recovered['logical_isolation']['isolation_id'])

    def test_auto_claim_isolation_failure_reports_retryable_next_slot(self):
        run=self.new_run([{'key':'A','title':'A','instructions':'A'},
                          {'key':'B','title':'B','instructions':'B','depends_on':['A']}])
        tid,store=self.worker('r')
        a=self.claim(run,tid)
        sha=self.commit(a)
        state=collab.finish(run,tid,commit_sha=sha,slot_number=a['slot'],
                            lease_generation=a['lease_generation'])
        self.assertTrue(state['continue_now'])
        with mock.patch.object(collab_isolation,'create_isolation',
                               side_effect=RuntimeError('injected next isolation setup')):
            result=collab_isolation.after_finish(run,tid,state,a['slot'])
        self.assertFalse(result['continue_now'])
        self.assertIn('injected next isolation',result['next_task_blocked'])
        self.assertNotIn('next_task',result)
        self.assertEqual(collab.status(run)['slots'][1]['status'],'claimed')
        # A repeated finish must return a usable next_task, even if the
        # caller never received the prior auto-claim response.
        retry=self.finish(run,tid,a,sha)
        self.assertTrue(retry['already_finished'])
        self.assertTrue(retry['continue_now'])
        recovered=retry['next_task']
        self.assertEqual(recovered['task_key'],'B')
        self.assertTrue(recovered['logical_isolation']['isolation_id'])

    def test_default_review_is_readonly_and_long_instructions_project_fully(self):
        long_instructions='Review carefully. '+'very detailed inputs. '*2000
        run=self.new_run([{'key':'A','title':'A','instructions':'produce'},
                          {'key':'R','title':'Review A','instructions':long_instructions,
                           'review_of':['A']}])
        producer,_=self.worker('a')
        reviewer,store=self.worker('b')
        a=self.claim(run,producer)
        self.finish(run,producer,a,self.commit(a))
        review=self.claim(run,reviewer)
        self.assertEqual(review['task_key'],'R')
        projection=review['logical_isolation']
        self.assertEqual(projection['role'],'reviewer')
        self.assertEqual(projection['mutation_policy'],'read_only')
        self.assertEqual(''.join(projection['collaboration']['instructions_chunks']),
                         long_instructions.strip())
        self.assertEqual(review['review_of'],['A'])
        self.assertIsNotNone(store.active_isolation())

    def test_readonly_reviewer_detects_changes_before_and_after_review(self):
        run=self.new_run([{'key':'R','title':'Reviewer','instructions':'Review',
                          'isolation':{'role':'reviewer'}}])
        tid,store=self.worker('r')
        assignment=self.claim(run,tid)
        self.assertEqual(assignment['logical_isolation']['mutation_policy'],'read_only')
        wt=Path(assignment['worktree'])
        (wt/'rogue.txt').write_text('unauthorized change')
        data={'summary':'Reviewed without findings','findings':[],
              'recommended_action':'accept','files_inspected':[],'limitations':[]}
        def review_finish():
            return subprocess.run([sys.executable,str(ROOT/'scripts'/'codex_loop.py'),
              'isolate-finish','--task-id',tid,'--cwd',str(self.repo),
              '--isolation-id',assignment['logical_isolation']['isolation_id']],
              input=json.dumps(data),text=True,capture_output=True)
        invalid=review_finish()
        self.assertNotEqual(invalid.returncode,0)
        self.assertIn('read-only Slot worktree changed',invalid.stdout)
        self.assertIsNotNone(store.active_isolation())
        (wt/'rogue.txt').unlink()
        accepted=review_finish()
        self.assertEqual(accepted.returncode,0,accepted.stdout)
        (wt/'rogue.txt').write_text('modified after approved review')
        invalid_commit=self.cli('finish','--run-id',run,'--task-id',tid,
                                '--slot',assignment['slot'],
                                '--lease-generation',assignment['lease_generation'],
                                '--commit-sha',git(wt,'rev-parse','HEAD'),
                                expect_ok=False)
        self.assertIn('read-only Slot result is stale',invalid_commit['message'])
        self.assertEqual(collab.status(run)['slots'][0]['status'],'claimed')

    def test_completion_by_other_worker_aborts_original_scope_not_finishes(self):
        run=self.new_run([{'key':'A','title':'Original','instructions':'Original'}])
        old_tid,old_store=self.worker('a')
        new_tid,_=self.worker('b')
        previous=self.claim(run,old_tid)
        old_iso=old_store.active_isolation()
        with collab._connection(write=True) as db:
            db.execute('UPDATE slots SET last_seen=? WHERE run_id=?',(time.time()-601,run))
        successor=self.claim(run,new_tid)
        self.finish(run,new_tid,successor,self.commit(successor))
        collab_isolation._close_previous(old_store,old_iso,
            {'run_id':run,'slot':successor['slot']+1},self.repo)
        self.assertEqual(old_store.isolation_history()[0]['status'],'aborted')

    def test_isolation_history_uses_insertion_order_not_random_id(self):
        from codex_loop_runtime.delegation import create_isolation,abort_isolation
        tid,store=self.worker('z')
        old=create_isolation(self.repo,self.repo,store,role='reviewer',
                             objective='first',requested_executor='logical_isolation')
        abort_isolation(self.repo,self.repo,store,old['isolation_id'],'complete first')
        new=create_isolation(self.repo,self.repo,store,role='reviewer',
                             objective='second',requested_executor='logical_isolation')
        with store.connect() as db:
            db.execute('UPDATE isolations SET created_at=?',('2026-10-15 12:00:00',))
        self.assertEqual(store.isolation_history(limit=1)[0]['isolation_id'],new['isolation_id'])

    def test_invalid_isolation_task_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'mutation_policy'):
            self.new_run([{'key':'A','title':'A','instructions':'A',
                           'isolation':{'mutation_policy':'unsafe_write'}}])
        with self.assertRaisesRegex(ValueError,'semantic'):
            self.new_run([{'key':'A','title':'A','instructions':'A',
                           'isolation':{'semantic_work':{
                            'consumer':'u','stage':'s','input_sha256':'bad','instruction_sha256':'b'*64}}}])
