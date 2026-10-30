"""Authorized non-Slot Run edits and live decisions across task publication/claims."""
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from codex_loop_runtime import local_collaboration as c
from codex_loop_runtime.routing_state import route_init
from codex_loop_runtime.workspace_registry import admit_workspace
from codex_loop_runtime.state import create_store


def git(root, *args):
    p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(p.stderr)
    return p.stdout.strip()


class RunEditorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        prev = os.environ.get('CODEX_LOOP_HOME')
        self.addCleanup(lambda: os.environ.__setitem__('CODEX_LOOP_HOME', prev)
                        if prev is not None else os.environ.pop('CODEX_LOOP_HOME', None))
        os.environ['CODEX_LOOP_HOME'] = str(self.root / 'state')
        self.repo = self.root / 'repo'
        self.parent = self.root / 'workers'
        self.repo.mkdir()
        self.parent.mkdir()
        git(self.repo, 'init', '-b', 'main')
        git(self.repo, 'config', 'user.email', 'test@example.org')
        git(self.repo, 'config', 'user.name', 'Test')
        (self.repo / 'start.txt').write_text('start')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'start')
        self.run = c.create_run(str(self.repo), 'main', str(self.parent),
                                [{'key': 'A', 'title': 'A', 'instructions': 'Implement A'}],
                                goal_key='editor-test')['run_id']
        self.sid = 'run-editor-' + uuid.uuid4().hex
        connection = {
            'name': 'my-mac', 'computer': 'mac', 'connector': 'My Mac', 'kind': 'mcp',
            'locations': {'default_root': str(self.repo), 'git_auth': 'osxkeychain',
                          'git_metadata_root': None, 'runtime_directory': None,
                          'state_directory': None, 'projects': {}},
        }
        routing = route_init(session_id=self.sid, host_surface='chatgpt_web',
                             resolved_execution={'status': 'resolved', 'workspace_mode': 'local',
                                                 'basis': 'explicit_user_target', 'computer': 'mac',
                                                 'local_connection': connection})
        self.addCleanup(lambda: Path(routing['state_path']).unlink(missing_ok=True))
        create_store(self.repo, task_id='editor-lifecycle').configure_task(
            'editor-lifecycle', request_anchor='Edit this authorized Run without a Slot')
        admit_workspace('run-project', str(self.repo), 'repository',
                        'Current user authorized management of this Run',
                        session_id=self.sid, host_authorized_roots=[str(self.repo)],
                        current_user_authorization_observed=True)

    def editor(self):
        return {'editor_session_id': self.sid, 'connector': 'My Mac'}

    def admit(self):
        return c.admit_run_editor(self.run, 'editor-lifecycle', session_id=self.sid,
                                  connector='My Mac', reason='User authorized this Run edit',
                                  current_user_authorization_observed=True)

    def test_editor_requires_explicit_permission_and_never_claims_slot(self):
        with self.assertRaises(PermissionError):
            c.admit_run_editor(self.run, 'editor-lifecycle', session_id=self.sid,
                               connector='My Mac', reason='unobserved')
        with self.assertRaises(PermissionError):
            c.publish_task(self.run, 'editor-lifecycle',
                           {'key': 'B', 'title': 'B', 'instructions': 'B'},
                           expected_revision=1, **self.editor())
        admitted = self.admit()
        self.assertFalse(admitted['slot_required'])
        self.assertEqual(c.status(self.run)['pools']['default']['claimed'], 0)
        with self.assertRaises(PermissionError):
            c.publish_task(self.run, 'editor-lifecycle',
                           {'key': 'B', 'title': 'B', 'instructions': 'B'},
                           expected_revision=1, editor_session_id=self.sid,
                           connector='Another Connector')
        published = c.publish_task(self.run, 'editor-lifecycle',
                                   {'key': 'B', 'title': 'B', 'instructions': 'B'},
                                   expected_revision=1, **self.editor())
        self.assertEqual(published['graph_revision'], 2)
        self.assertEqual(c.status(self.run)['pools']['default']['claimed'], 0)
        with self.assertRaises(RuntimeError):
            c.publish_task(self.run, 'editor-lifecycle',
                           {'key': 'C', 'title': 'C', 'instructions': 'C'},
                           expected_revision=1, **self.editor())
        changed = c.revise_task(self.run, 'editor-lifecycle', 'B',
                                {'instructions': 'Updated B'}, expected_revision=2,
                                **self.editor())
        self.assertEqual(changed['graph_revision'], 3)
        self.assertEqual([row['instructions'] for row in c.status(self.run)['slots']
                          if row['task_key'] == 'B'], ['Updated B'])

    def test_run_guidance_reaches_new_and_active_tasks_without_extra_worker_reads(self):
        self.admit()
        guidance = 'Maintain 1:4. Avoid unnecessary independent review.'
        c.set_run_guidance(self.run, 'editor-lifecycle', guidance, expected_revision=1,
                           **self.editor())
        context = c.run_context(self.run)
        self.assertEqual(context['guidance'], guidance)
        claimed = c.claim(self.run, 'worker-1', worktree_parent=str(self.parent))
        self.assertIn(guidance, claimed['instructions'])
        self.assertIn('Implement A', claimed['instructions'])
        # A user changes the decision while work is already claimed.
        latest = 'Maintain 1:4. Do not create automatic review tasks.'
        response = c.set_run_guidance(
            self.run, 'editor-lifecycle', latest,
            expected_revision=context['graph_revision'], **self.editor())
        self.assertEqual(response['notified_claimed_workers'], 1)
        self.assertIn(latest, c.inbox(self.run, 'worker-1')['messages'][0]['body'])
        spec = {'key': 'B', 'title': 'B', 'instructions': 'Implement B'}
        c.publish_task(self.run, 'editor-lifecycle', spec,
                       expected_revision=response['graph_revision'], **self.editor())
        next_task = c.claim(self.run, 'worker-2', worktree_parent=str(self.parent))
        self.assertIn(latest, next_task['instructions'])
        self.assertNotIn(guidance, next_task['instructions'])
        self.assertEqual(next_task['task_key'], 'B')

    def test_multiple_rapid_updates_deliver_only_latest_run_guidance(self):
        self.admit()
        c.claim(self.run,'worker-1',worktree_parent=str(self.parent))
        first=c.set_run_guidance(self.run,'editor-lifecycle','Old decision',
                                 expected_revision=1,**self.editor())
        second=c.set_run_guidance(self.run,'editor-lifecycle','Current decision',
                                  expected_revision=first['graph_revision'],**self.editor())
        pending=c.inbox(self.run,'worker-1')['messages']
        self.assertEqual(len(pending),1)
        self.assertIn('Current decision',pending[0]['body'])
        self.assertNotIn('Old decision',pending[0]['body'])

    def test_missing_unrelated_workspace_does_not_block_authorized_run(self):
        from codex_loop_runtime.workspace_registry import admit_workspace
        missing=self.root/'unrelated'
        missing.mkdir()
        admit_workspace('a-unrelated',str(missing),'repository','Authorized other workspace',
                        session_id=self.sid,host_authorized_roots=[str(missing)],
                        current_user_authorization_observed=True)
        missing.rmdir()
        result=self.admit()
        self.assertEqual(result['role'],'run_editor')

    def test_initial_guidance_is_available_before_first_claim(self):
        new = c.create_run(str(self.repo), 'main', str(self.parent),
                           [{'key': 'X', 'title': 'X', 'instructions': 'Do X'}],
                           goal_key='initial-policy',
                           guidance='Original end goal; preserve 1:4 and avoid needless review.')
        self.assertTrue(new['guidance_initialized'])
        context = c.run_context(new['run_id'])
        self.assertIn('Original end goal', context['guidance'])
        assigned = c.claim(new['run_id'], 'fresh-worker', worktree_parent=str(self.parent))
        self.assertIn('preserve 1:4', assigned['instructions'])
        self.assertIn('Do X', assigned['instructions'])

    def test_worker_still_publishes_and_stale_lease_cannot_edit(self):
        assigned = c.claim(self.run, 'worker-1', worktree_parent=str(self.parent))
        revision = c.run_context(self.run)['graph_revision']
        with self.assertRaises(TypeError):
            c.publish_task(self.run, 'worker-1',
                           {'key': 'stale', 'title': 'stale', 'instructions': 'old'},
                           lease_generation=assigned['lease_generation'])
        new = c.publish_task(self.run, 'worker-1',
                             {'key': 'B', 'title': 'B', 'instructions': 'B'},
                             lease_generation=assigned['lease_generation'],
                             expected_revision=revision)
        self.assertEqual(new['graph_revision'], revision + 1)
        with self.assertRaises(PermissionError):
            c.revise_task(self.run, 'worker-1', 'B', {'title': 'wrong'},
                          lease_generation=assigned['lease_generation'] + 1,
                          expected_revision=new['graph_revision'])


if __name__ == '__main__':
    unittest.main()
