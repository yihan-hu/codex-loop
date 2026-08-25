import subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))

from codex_loop_runtime.change_tracker import capture_baseline
from codex_loop_runtime.checkpoint import create as create_checkpoint
from codex_loop_context_projection import build_full, build_working
from codex_loop_runtime.state import create_store


class ContextProjectionTests(unittest.TestCase):
    def make(self, root: Path, *, criteria=None, requires_validation=False):
        store = create_store(root)
        store.configure_task(
            store.path.parent.name,
            'context projection objective',
            list(criteria or []),
            requires_validation=requires_validation,
            no_validation_reason=None if requires_validation else 'fixture has no executable validation',
        )
        capture_baseline(root, store)
        return store

    def test_working_projection_is_bounded_and_hides_task_bookkeeping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make(root, criteria=[f'criterion {i}' for i in range(30)])
            view = build_working(root, root, store)
            self.assertNotIn('task_id', view)
            self.assertNotIn('generation', view)
            self.assertEqual(len(view['effective_spec']['criteria']), 24)
            self.assertEqual(view['truncated']['criteria'], 6)
            self.assertLessEqual(len(view['next_actions']), 8)
            self.assertTrue(any('acceptance criteria' in x['action'] for x in view['next_actions']))

    def test_working_projection_derives_freshness_without_exposing_evidence_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            (root / 'a.txt').write_text('one')
            store = self.make(root, criteria=['a is correct'], requires_validation=True)
            store.set_criterion(0, 'pass', 'observed a.txt')
            store.record_validation(0, ['pytest'], 0, cwd=root, evidence='local runtime validation passed')
            before = build_working(root, root, store)
            self.assertEqual(before['effective_spec']['criteria'][0]['status'], 'pass')
            self.assertEqual(before['state']['validation'], 'fresh-pass')
            (root / 'a.txt').write_text('two')
            after = build_working(root, root, store)
            criterion = after['effective_spec']['criteria'][0]
            self.assertEqual(criterion['status'], 'stale')
            self.assertNotIn('evidence_generation', criterion)
            self.assertEqual(after['state']['validation'], 'stale')
            self.assertEqual(after['state']['review'], 'stale')


    def test_next_actions_include_pending_criteria_beyond_projection_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make(root, criteria=[f'criterion {i}' for i in range(25)])
            for ordinal in range(24):
                store.set_criterion(ordinal, 'pass', f'criterion {ordinal} observed')
            view = build_working(root, root, store)
            self.assertEqual(view['truncated']['criteria'], 1)
            self.assertTrue(any('C25' in x['action'] for x in view['next_actions']))

    def test_stale_freshness_waiver_does_not_hide_opaque_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            (root / '.gitignore').write_text('big.dat\n')
            (root / 'big.dat').write_bytes(b'x' * (1024 * 1024 + 1))
            store = self.make(root, criteria=['criterion'])
            opaque = store.get_meta('ignored_watch', {}).get('opaque_paths', [])
            store.set_freshness_waiver(opaque, 'fixture accepts current opaque path set')
            (root / 'visible.txt').write_text('mutation')
            view = build_working(root, root, store)
            self.assertTrue(any('freshness waiver' in x['action'] for x in view['next_actions']))

    def test_checkpoint_and_full_world_state_share_the_same_projection_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make(root, criteria=['criterion'])
            full = build_full(root, root, store)
            checkpoint = create_checkpoint(root, root, store, key_findings=['fact'], next_action='next')
            for key in ('objective', 'profile', 'generation', 'criteria', 'changes', 'validation', 'instructions'):
                self.assertEqual(checkpoint[key], full[key])
            self.assertEqual(checkpoint['key_findings'], ['fact'])
            self.assertEqual(checkpoint['next_action'], 'next')


if __name__ == '__main__':
    unittest.main()
