import json, subprocess, sys, tempfile, unittest
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
            list(criteria or []), request_anchor='context projection objective',
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
            self.assertLess(len(json.dumps(view, ensure_ascii=False).encode('utf-8')), 32768)
            self.assertNotIn('repository_instructions', view['lifecycle']['active_capabilities'])
            self.assertNotIn('validation', view['lifecycle']['requirements'])
            self.assertNotIn('change_review', view['lifecycle']['requirements'])

    def test_working_projection_exposes_single_focus_and_scope_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            store = self.make(root)
            store.set_working_focus(
                'fix parser null handling',
                non_goals=['do not refactor tokenizer'],
                expected_change_surface=['parser.py', 'tests/parser/'],
            )
            (root / 'helper.py').write_text('unrelated')
            view = build_working(root, root, store)
            focus = view['effective_spec']['working_focus']
            self.assertEqual(focus['current_subgoal'], 'fix parser null handling')
            self.assertEqual(focus['status'], 'in_progress')
            self.assertEqual(focus['non_goals'], ['do not refactor tokenizer'])
            self.assertEqual(focus['expected_change_surface'], ['parser.py', 'tests/parser/'])
            self.assertEqual(view['state']['scope_drift'], ['helper.py'])
            self.assertEqual(view['state']['changed_paths'][0]['scope'], 'drift')
            self.assertTrue(any(x['kind'] == 'review' and 'scope drift' in x['action'] for x in view['next_actions']))

    def test_working_projection_bounds_long_request_authority_with_explicit_drilldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
            anchor = 'a' * 13000
            steer = 'b' * 5000
            store = create_store(root)
            store.configure_task(
                store.path.parent.name,
                'bounded request projection',
                [],
                request_anchor=anchor,
                requires_validation=False,
                no_validation_reason='fixture has no executable validation',
            )
            capture_baseline(root, store)
            store.record_steer(steer)

            view = build_working(root, root, store)
            self.assertEqual(len(view['effective_spec']['request_anchor']), 12000)
            self.assertEqual(len(view['effective_spec']['request_steers'][0]['text']), 4096)
            self.assertEqual(view['truncated']['request_anchor_chars'], 1000)
            self.assertEqual(view['truncated']['request_steer_chars'], 904)
            self.assertTrue(any('full request authority' in x['action'] for x in view['next_actions']))
            self.assertIn({'ref': 'request:full', 'inspect_with': 'snapshot'}, view['evidence_refs'])

            full = build_full(root, root, store)
            self.assertEqual(full['request_anchor'], anchor)
            self.assertEqual(full['effective_request']['steers'], [steer])

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
            self.assertEqual(after['lifecycle']['mode'], 'durable')
            self.assertIn('mutation_tracking', after['lifecycle']['active_capabilities'])
            self.assertEqual(after['lifecycle']['requirements']['validation'], 'required')


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
