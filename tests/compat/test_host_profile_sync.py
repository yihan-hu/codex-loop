from __future__ import annotations

import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from codex_loop_runtime.host_config import host_config_set, host_config_show
from codex_loop_runtime.host_profile_sync import PROFILE_DRIVE_PATH, export_profile, import_profile
from codex_loop_runtime.local_connection import resolve_execution


class HostProfileSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'first-chat'
        self.env = patch.dict(os.environ, {'CODEX_LOOP_HOME': str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def export(self):
        path = self.root / 'transport' / 'host-profile.json'
        return path, export_profile(drive_root_id='current-user-root', output=str(path))

    def test_new_chat_restores_computer_priority_and_explicit_override(self):
        connections = [dict(name='primary', computer='laptop', connector='User MCP', kind='mcp'),
                       dict(name='backup', computer='laptop', connector='User RDC', kind='rdc')]
        save = host_config_set('execution.connections', connections)
        self.assertFalse(save['cross_chat_saved'])
        host_config_set('execution.default_target', 'laptop')
        host_config_set('drive.cache_folder_paths', ['ChatGPT-Temporary/private-cache'])
        path, exported = self.export()
        envelope = json.loads(path.read_text())
        self.assertEqual(PROFILE_DRIVE_PATH, 'codex-loop/settings/host-profile.json')
        self.assertNotIn('drive', envelope['profile'])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(exported['cross_chat_saved'])
        os.environ['CODEX_LOOP_HOME'] = str(self.root / 'second-chat')
        imported = import_profile(drive_root_id='current-user-root', input_path=str(path))
        self.assertFalse(imported['tasks_restored'])
        self.assertEqual(resolve_execution(available_connections=['primary', 'backup'])['local_connection']['name'], 'primary')
        self.assertEqual(resolve_execution(target='web')['workspace_mode'], 'web')
        self.assertEqual(host_config_show()['drive']['cache_folder_paths'], [])

    def test_wrong_account_corruption_unknown_fields_leave_existing_untouched(self):
        host_config_set('execution.default_target', 'web')
        path, _ = self.export()
        baseline = (self.home / 'host.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'different Drive account'):
            import_profile(drive_root_id='another-user-root', input_path=str(path))
        payload = json.loads(path.read_text())
        payload['profile']['execution']['default_target'] = 'local'
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            import_profile(drive_root_id='current-user-root', input_path=str(path))
        payload['profile']['api_key'] = 'private-token'
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, 'unsupported fields'):
            import_profile(drive_root_id='current-user-root', input_path=str(path))
        self.assertEqual((self.home / 'host.json').read_bytes(), baseline)

    def test_defaults_and_native_cache_registry(self):
        self.assertEqual(resolve_execution()['workspace_mode'], 'web')
        self.assertEqual(host_config_show()['persistence']['host_profile_backend'], 'auto')
        path, _ = self.export()
        host_config_set('drive.cache_folder_paths', ['ChatGPT-Temporary/native'])
        import_profile(drive_root_id='current-user-root', input_path=str(path))
        self.assertEqual(host_config_show()['drive']['cache_folder_paths'], ['ChatGPT-Temporary/native'])

    def test_root_alias_cannot_bind_every_users_account_to_same_value(self):
        for root in ['root', 'me', 'https://drive.example/root', '']:
            with self.assertRaises(ValueError):
                export_profile(drive_root_id=root, output=str(self.root / 'host-profile.json'))

    def test_cli_round_trip_and_backend_save_status(self):
        cli = Path(__file__).resolve().parents[2] / 'scripts' / 'codex_loop.py'
        path = self.root / 'cli' / 'host-profile.json'
        for action, flag in [('export', '--output'), ('import', '--input')]:
            result = subprocess.run([sys.executable, str(cli), 'host-profile', action,
                                     '--drive-root-id', 'current-user-root', flag, str(path)],
                                    capture_output=True, text=True, check=True)
            self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertEqual(host_config_set('persistence.host_profile_backend', 'local_only')['profile_sync_action'], 'local_only_no_upload')
        self.assertEqual(host_config_set('persistence.host_profile_backend', 'google_drive')['profile_sync_action'], 'sync_required_or_report_failure')

    def test_export_refuses_credentials_and_profile_overwrite(self):
        host_config_set('web_publish.staging_folder_id', 'sk-' + 'S' * 24)
        with self.assertRaisesRegex(ValueError, 'credentials'):
            self.export()
        host_config_set('web_publish.staging_folder_id', None)
        with self.assertRaisesRegex(ValueError, 'must not replace'):
            export_profile(drive_root_id='current-user-root', output=str(self.home / 'host.json'))


if __name__ == '__main__':
    unittest.main()
