import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

from codex_loop_context_projection import build_lifecycle_working
from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.completion import CompletionStatus, assess
from codex_loop_runtime.state import create_store


class LightweightCompletionTests(unittest.TestCase):
    def make_store(self, root: Path, *, requires_validation: bool = False, profile: str = 'regular'):
        store = create_store(root)
        store.configure_task(
            store.path.parent.name,
            request_anchor='exact user request',
            profile=profile,
            requires_validation=requires_validation,
        )
        capture_baseline(root, store)
        return store

    def test_cli_completion_uses_bound_workspace_not_caller_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo, caller = base / 'repo', base / 'controller'
            repo.mkdir()
            caller.mkdir()
            subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
            subprocess.run(['git', 'config', 'user.email', 'test@example.invalid'], cwd=repo, check=True)
            subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo, check=True)
            (repo / 'file.txt').write_text('base\n')
            subprocess.run(['git', 'add', 'file.txt'], cwd=repo, check=True)
            subprocess.run(['git', 'commit', '-qm', 'base'], cwd=repo, check=True)
            cli = Path(__file__).resolve().parents[2] / 'scripts' / 'codex_loop.py'
            env = {**os.environ, 'CODEX_LOOP_HOME': str(base / 'state'),
                   'PYTHONDONTWRITEBYTECODE': '1'}

            def invoke(*args):
                process = subprocess.run([sys.executable, str(cli), *args], cwd=caller,
                                         env=env, capture_output=True, text=True, check=True)
                return json.loads(process.stdout)['data']

            task_id = invoke('bootstrap', '--request-anchor', 'test completion cwd')['task_id']
            self.assertEqual(
                invoke('orient', '--task-id', task_id, '--cwd', str(repo))['root'],
                str(repo.resolve()),
            )
            wrong = invoke('completion', '--task-id', task_id, '--cwd', str(caller))
            self.assertEqual(wrong['status'], 'BLOCKED')
            self.assertIn('canonical workspace binding', wrong['reasons'][0])
            completed = invoke('completion', '--task-id', task_id)
            self.assertEqual(completed['status'], 'PASS')
            self.assertEqual(completed['lifecycle_status'], 'complete')
            self.assertTrue(completed['details']['workspace_binding']['matches'])

            unbound = invoke('bootstrap', '--request-anchor', 'lifecycle only')['task_id']
            self.assertEqual(invoke('completion', '--task-id', unbound)['status'], 'PASS')

            vanished = invoke('bootstrap', '--request-anchor', 'missing repo')['task_id']
            invoke('orient', '--task-id', vanished, '--cwd', str(repo))
            repo.rename(base / 'moved-repo')
            missing = invoke('completion', '--task-id', vanished)
            self.assertEqual(missing['status'], 'BLOCKED')
            self.assertIn('canonical workspace binding', missing['reasons'][0])

    def test_no_plan_and_no_required_validation_can_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make_store(root)
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_unfinished_plan_does_not_gate_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make_store(root)
            store.set_plan([{'step': 'inspect', 'status': 'in_progress'}])
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)
            store.set_plan([{'step': 'inspect', 'status': 'completed'}])
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_required_validation_needs_current_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make_store(root, requires_validation=True)
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)
            store.record_observed_validation(['pytest', '-q'], 0, cwd=root, evidence='pytest passed')
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)


    def test_lifecycle_only_projection_never_reports_pass_with_unresolved_external_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root, requires_validation=False)
            action_id = store.record_external("github_push", "planned", "push:abc", action_class="external_non_idempotent")
            store.record_external("github_push", "dispatched", "push:abc", action_class="external_non_idempotent", action_id=action_id)
            view = build_lifecycle_working(store)
            self.assertFalse(view["machine"]["blockers_clear"])
            self.assertIn("external action state is unresolved", view["machine"]["blockers"])

    def test_lifecycle_only_reconciles_external_action_before_plan_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root)
            store.configure_task(store.path.parent.name, request_anchor='exact user request')
            store.set_plan([{'step': 'continue implementation', 'status': 'in_progress'}])
            action_id = store.record_external('deploy', 'planned', 'deploy:abc', action_class='external_non_idempotent')
            store.record_external('deploy', 'dispatched', 'deploy:abc', action_class='external_non_idempotent', action_id=action_id)
            view = build_lifecycle_working(store)
            self.assertIn('external action state is unresolved', view['machine']['blockers'])
            self.assertEqual(view['plan'][0]['step'], 'continue implementation')

    def test_lifecycle_only_projection_requires_validation_before_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root)
            store.configure_task(
                store.path.parent.name,
                request_anchor='exact user request',
                requires_validation=True,
            )
            view = build_lifecycle_working(store)
            self.assertFalse(view["machine"]["blockers_clear"])
            self.assertIn("required validation is missing", view["machine"]["blockers"])

    def test_lifecycle_status_transitions_are_distinct_from_execution_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make_store(root)
            store.pause()
            self.assertEqual(store.task_status(), 'paused')
            self.assertEqual(assess(root, store).status, CompletionStatus.BLOCKED)
            previous, reason = store.resume()
            self.assertEqual((previous, reason), ('paused', None))
            store.block('waiting for user input')
            view = build_lifecycle_working(store)
            self.assertEqual(view['continuation']['mode'], 'blocked')
            self.assertEqual(view['continuation']['blocked_reason'], 'waiting for user input')
            previous, reason = store.resume()
            self.assertEqual((previous, reason), ('blocked', 'waiting for user input'))
            store.mark_complete()
            self.assertEqual(store.task_status(), 'complete')
            with self.assertRaisesRegex(RuntimeError, 'not resumable'):
                store.resume()

    def test_task_board_is_a_projection_of_the_three_state_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root)
            store.set_plan([
                {'step': 'done step', 'status': 'completed'},
                {'step': 'current step', 'status': 'in_progress'},
                {'step': 'later step', 'status': 'pending'},
            ])
            view = build_lifecycle_working(store)
            self.assertEqual(view['task_board'], {
                'doing': ['current step'], 'pending': ['later step'], 'done': ['done step'],
            })

    def test_live_process_projects_verified_wait_without_inventing_new_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make_store(root)
            store.upsert_process('job-1', 123, ['pytest', '-q'], str(root), 'running')
            view = build_lifecycle_working(store)
            self.assertEqual(view['live_work']['mode'], 'verified_wait')
            self.assertEqual(view['live_work']['processes'][0]['handle'], 'job-1')
            self.assertIn('do not restart', view['live_work']['rule'])
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)


    def test_steer_is_authoritative_without_ack_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make_store(root)
            store.record_steer('do not change API')
            self.assertEqual(store.effective_request()['steers'], ['do not change API'])
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_read_only_profile_blocks_workspace_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            (root / 'a.txt').write_text('a\n')
            store = self.make_store(root, profile='code_review')
            (root / 'a.txt').write_text('b\n')
            self.assertEqual(assess(root, store).status, CompletionStatus.BLOCKED)


if __name__ == '__main__':
    unittest.main()
