"""Regression: upgrading a running unit must replace its process and verify version."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE))
spec = importlib.util.spec_from_file_location('wsl_upgrade', SOURCE / 'upgrade-http.py')
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


class UpgradeTests(unittest.TestCase):
    def run_upgrade(self, refuse_reload=False, active=False):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/codex-loop-wsl'
            profiles = home / '.config/tunnel-client'
            units = home / '.config/systemd/user'
            app = home / '.local/share/codex-loop-wsl'
            for folder in (config, profiles, units, app, home / '.local/bin'):
                folder.mkdir(parents=True)
            (config / 'settings.json').write_text(json.dumps({'workspace_roots': ['/example/projects']}))
            (config / 'connection.env').write_text('')
            (profiles / 'codex-loop-wsl.yaml').write_text('mcp: {}\n')
            (units / 'codex-loop-wsl-tunnel.service').write_text('[Service]\n')
            expected = json.loads((SOURCE / 'package.json').read_text())['version']
            live = {'version': 'old-process'}
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                if command == ['systemctl', '--user', 'restart', 'codex-loop-wsl-http.service'] and not refuse_reload:
                    live['version'] = expected

            def health():
                return {'running_jobs': 1 if active else 0, 'active_requests': 0, 'server_version': live['version']}

            output = io.StringIO()
            with patch.object(upgrade.Path, 'home', return_value=home), patch.object(upgrade, 'health', side_effect=health), patch.object(upgrade.subprocess, 'run', side_effect=run), patch.object(sys, 'argv', ['upgrade-http.py']), contextlib.redirect_stdout(output):
                upgrade.main()
            return commands, json.loads(output.getvalue())

    def test_running_backend_is_restarted_before_success(self):
        commands, result = self.run_upgrade()
        stopped = commands.index(['systemctl', '--user', 'stop', 'codex-loop-wsl-tunnel.service'])
        restarted = commands.index(['systemctl', '--user', 'restart', 'codex-loop-wsl-http.service'])
        self.assertLess(stopped, restarted)
        self.assertEqual(result['server_version'], json.loads((SOURCE / 'package.json').read_text())['version'])
        self.assertTrue(result['upgraded'])

    def test_old_process_cannot_be_reported_as_successful_upgrade(self):
        with self.assertRaisesRegex(SystemExit, 'version mismatch'):
            self.run_upgrade(refuse_reload=True)

    def test_active_command_blocks_upgrade(self):
        with self.assertRaisesRegex(SystemExit, 'Active MCP work'):
            self.run_upgrade(active=True)


if __name__ == '__main__':
    unittest.main()
