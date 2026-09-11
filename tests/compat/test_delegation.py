import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL / 'scripts'))

from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.completion import CompletionStatus, assess
from codex_loop_runtime.delegation import create_isolation, finish_isolation, isolation_status
from codex_loop_runtime.state import create_store


class DelegationTests(unittest.TestCase):
    def make(self, root: Path):
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        store = create_store(root)
        store.configure_task(store.path.parent.name, 'parent objective', [], request_anchor='parent objective')
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


if __name__ == '__main__':
    unittest.main()
