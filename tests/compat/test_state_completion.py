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
            'objective',
            [],
            request_anchor='exact user request',
            profile=profile,
            requires_validation=requires_validation,
        )
        capture_baseline(root, store)
        return store

    def test_no_plan_and_no_required_validation_can_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make_store(root)
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_unfinished_plan_continues_until_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make_store(root)
            store.set_plan([{'step': 'inspect', 'status': 'in_progress'}])
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)
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
            self.assertEqual(view["state"]["completion"], "CONTINUE")
            self.assertEqual(view["next_actions"][0]["kind"], "required")
            self.assertIn("external", view["next_actions"][0]["action"])

    def test_lifecycle_only_reconciles_external_action_before_plan_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root)
            store.configure_task(store.path.parent.name, 'objective', [], request_anchor='exact user request')
            store.set_plan([{'step': 'continue implementation', 'status': 'in_progress'}])
            action_id = store.record_external('deploy', 'planned', 'deploy:abc', action_class='external_non_idempotent')
            store.record_external('deploy', 'dispatched', 'deploy:abc', action_class='external_non_idempotent', action_id=action_id)
            view = build_lifecycle_working(store)
            self.assertIn('external', view['next_actions'][0]['action'])
            self.assertNotEqual(view['next_actions'][0]['action'], 'continue implementation')

    def test_lifecycle_only_projection_requires_validation_before_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = create_store(root)
            store.configure_task(
                store.path.parent.name,
                'objective',
                [],
                request_anchor='exact user request',
                requires_validation=True,
            )
            view = build_lifecycle_working(store)
            self.assertEqual(view["state"]["completion"], "CONTINUE")
            self.assertEqual(view["next_actions"][0]["kind"], "verify")


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
