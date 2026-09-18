import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL / 'scripts'))

from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.completion import CompletionStatus, assess
from codex_loop_runtime.delegation import (
    abort_isolation,
    create_isolation,
    create_semantic_isolation,
    finish_isolation,
    finish_semantic_isolation,
    isolation_status,
    resolve_semantic_result,
)
from codex_loop_runtime.state import create_store


class DelegationTests(unittest.TestCase):
    def make(self, root: Path):
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        store = create_store(root)
        store.configure_task(store.path.parent.name, request_anchor='parent objective')
        capture_baseline(root, store)
        return store

    def test_active_isolation_is_optional_but_completion_relevant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            projection = create_isolation(root, root, store, role='reviewer', objective='review independently')
            self.assertEqual(projection['executor']['kind'], 'logical_isolation')
            self.assertEqual(projection['guardrails'][0], 'read-only')
            self.assertEqual(assess(root, store).status, CompletionStatus.CONTINUE)
            result = {
                'summary': 'review complete',
                'findings': [],
                'recommended_action': 'continue',
                'files_inspected': [],
                'limitations': [],
            }
            finish_isolation(root, root, store, projection['isolation_id'], result)
            self.assertIsNone(isolation_status(root, root, store)['active_isolation'])
            self.assertEqual(assess(root, store).status, CompletionStatus.PASS)

    def test_projection_contains_only_explicit_bounded_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            projection = create_isolation(
                root, root, store,
                role='reviewer', objective='review independently',
                project_files=['src/auth.py'], facts=['failure is intermittent'], criteria_refs=['C1'],
            )
            self.assertEqual(projection['projected_context']['files'], ['src/auth.py'])
            self.assertEqual(projection['projected_context']['facts'], ['failure is intermittent'])
            self.assertNotIn('parent objective', str(projection['projected_context']))

    def test_semantic_work_can_only_finish_through_logical_isolation_authority_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            digest_a = 'a' * 64
            digest_b = 'b' * 64
            projection = create_semantic_isolation(
                root, root, store,
                objective='perform B2 language review',
                consumer='epi-prose', stage='language-review-b2',
                input_sha256=digest_a, instruction_sha256=digest_b,
                project_files=['packet.json'],
            )
            self.assertEqual(projection['executor']['kind'], 'logical_isolation')
            self.assertEqual(projection['role'], 'semantic-worker')
            self.assertEqual(projection['semantic_work']['authority'], 'logical_isolation_only')
            self.assertIn('do not use scripts', ' '.join(projection['guardrails']))

            fake_delegation_result = {
                'summary': 'pretend clean', 'findings': [], 'recommended_action': '',
                'files_inspected': [], 'limitations': [],
            }
            with self.assertRaisesRegex(RuntimeError, 'semantic-work-finish'):
                finish_isolation(root, root, store, projection['isolation_id'], fake_delegation_result)

            domain_result = {'status': 'PASS', 'issues': [], 'reviewed_text': 'actual semantic output'}
            finished = finish_semantic_isolation(root, root, store, projection['isolation_id'], domain_result)
            semantic_result_id = finished['semantic_result']['semantic_result_id']
            resolved = resolve_semantic_result(
                root, store, semantic_result_id,
                consumer='epi-prose', stage='language-review-b2',
                input_sha256=digest_a, instruction_sha256=digest_b,
            )
            self.assertTrue(resolved['authoritative_current'])
            self.assertEqual(resolved['executor'], 'logical_isolation')
            self.assertEqual(resolved['result'], domain_result)

    def test_semantic_result_is_generation_bound_and_cannot_be_reused_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            digest_a = 'c' * 64
            digest_b = 'd' * 64
            projection = create_semantic_isolation(
                root, root, store,
                objective='review current prose',
                consumer='epi-prose', stage='language-review-b2',
                input_sha256=digest_a, instruction_sha256=digest_b,
            )
            finished = finish_semantic_isolation(
                root, root, store, projection['isolation_id'], {'status': 'PASS', 'issues': []}
            )
            semantic_result_id = finished['semantic_result']['semantic_result_id']
            store.bump_generation()
            with self.assertRaisesRegex(RuntimeError, 'stale for generation'):
                resolve_semantic_result(
                    root, store, semantic_result_id,
                    consumer='epi-prose', stage='language-review-b2',
                    input_sha256=digest_a, instruction_sha256=digest_b,
                )

    def test_semantic_work_refuses_completion_if_workspace_changed_during_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            projection = create_semantic_isolation(
                root, root, store,
                objective='review current prose',
                consumer='epi-prose', stage='language-review-b2',
                input_sha256='e' * 64, instruction_sha256='f' * 64,
            )
            store.bump_generation()
            with self.assertRaisesRegex(RuntimeError, 'workspace changed'):
                finish_semantic_isolation(root, root, store, projection['isolation_id'], {'status': 'PASS'})
            abort_isolation(root, root, store, projection['isolation_id'], 'stale semantic work')

    def test_semantic_work_stales_on_user_steer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            projection = create_semantic_isolation(
                root, root, store,
                objective='review current prose',
                consumer='epi-prose', stage='language-review-b2',
                input_sha256='1' * 64, instruction_sha256='2' * 64,
            )
            store.record_steer('change the language requirement')
            with self.assertRaisesRegex(RuntimeError, 'effective user request changed'):
                finish_semantic_isolation(root, root, store, projection['isolation_id'], {'status': 'PASS'})
            abort_isolation(root, root, store, projection['isolation_id'], 'stale semantic work after steer')

    def test_finished_semantic_result_stales_after_later_user_steer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = self.make(root)
            projection = create_semantic_isolation(
                root, root, store,
                objective='review current prose',
                consumer='epi-prose', stage='language-review-b2',
                input_sha256='3' * 64, instruction_sha256='4' * 64,
            )
            finished = finish_semantic_isolation(
                root, root, store, projection['isolation_id'], {'status': 'PASS', 'issues': []}
            )
            semantic_result_id = finished['semantic_result']['semantic_result_id']
            store.record_steer('new user requirement')
            with self.assertRaisesRegex(RuntimeError, 'effective user request changed'):
                resolve_semantic_result(
                    root, store, semantic_result_id,
                    consumer='epi-prose', stage='language-review-b2',
                    input_sha256='3' * 64, instruction_sha256='4' * 64,
                )


if __name__ == '__main__':
    unittest.main()
