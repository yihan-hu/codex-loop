#!/usr/bin/env python3
"""Upgrade an existing private WSL connection to the authenticated HTTP backend."""
import argparse
import datetime
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import yaml
from operate import health


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    home = Path.home()
    source = Path(__file__).resolve().parent
    config = home / '.config/codex-loop-wsl'
    app = home / '.local/share/codex-loop-wsl'
    settings = json.loads((config / 'settings.json').read_text())
    profile = home / '.config/tunnel-client/codex-loop-wsl.yaml'
    original = yaml.safe_load(profile.read_text())
    if not (config / 'connection.env').is_file():
        raise SystemExit('Configure the private connection first.')
    # Never replace a shared backend while its commands are still running.
    try:
        if health()['running_jobs'] or health()['active_requests']:
            raise SystemExit('Active MCP work detected; wait before upgrading.')
    except OSError:
        # Original stdio jobs are bwrap children, visible without reading arguments.
        children = subprocess.run(['pgrep', '-x', 'bwrap'], capture_output=True)
        if children.returncode == 0:
            raise SystemExit('A sandbox command is active; wait before upgrading.')
    if args.check_only:
        print(json.dumps({'upgrade_safe': True})); return
    subprocess.run(['node', '--test', str(source / 'test.mjs'), str(source / 'http.test.mjs'), str(source / 'grants.test.mjs')], cwd=source, check=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = config / ('http-upgrade-backup-' + stamp)
    backup.mkdir(mode=0o700)
    shutil.copy2(profile, backup / profile.name)
    units = home / '.config/systemd/user'
    tunnel_unit = units / 'codex-loop-wsl-tunnel.service'
    shutil.copy2(tunnel_unit, backup / tunnel_unit.name)
    for name in ('server.mjs', 'grants.mjs', 'projects.py', 'http.mjs', 'operate.py'):
        if (app / name).exists():
            shutil.copy2(app / name, backup / name)
        shutil.copy2(source / name, app / name)
    auth = config / 'http-auth.header'
    if not auth.exists():
        fd = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write('Bearer ' + secrets.token_urlsafe(32) + '\n')
    if auth.is_symlink():
        raise SystemExit('Authorization file must not be a symlink.')
    auth.chmod(0o600)
    # Preserve the control-plane credential reference and association unchanged.
    original['mcp'] = dict(original.get('mcp', {}))
    for key in ('command', 'commands', 'server_urls', 'extra_headers', 'discovery_extra_headers'):
        original['mcp'].pop(key, None)
    original['mcp'].update({'server_urls': [{'channel': 'main', 'url': 'http://127.0.0.1:18790/mcp'}], 'max_concurrent_requests': 64,
        'extra_headers': {'Authorization': 'file:' + str(auth)},
        'discovery_extra_headers': {'Authorization': 'file:' + str(auth)}})
    profile.write_text(yaml.safe_dump(original, sort_keys=False)); profile.chmod(0o600)
    # Backend environment intentionally excludes the control-plane API key.
    roots = ':'.join(settings['workspace_roots']).replace('\\', '\\\\').replace('"', '\\"')
    http_unit = units / 'codex-loop-wsl-http.service'
    http_unit.write_text('[Unit]\nDescription=Codex Loop WSL plain-text HTTP MCP\n\n[Service]\n'
        'ExecStart=/usr/bin/node %h/.local/share/codex-loop-wsl/http.mjs\n'
        'UnsetEnvironment=CONTROL_PLANE_API_KEY OPENAI_API_KEY\n'
        f'Environment="CODEX_LOOP_WSL_ROOTS={roots}"\n'
        'Environment=CODEX_LOOP_WSL_AUTH_FILE=%h/.config/codex-loop-wsl/http-auth.header\n'
        'Environment=MCP_MAX_CONCURRENT_REQUESTS=64\nRestart=on-failure\nRestartSec=3\n'
        'KillMode=control-group\nUMask=0077\n\n[Install]\nWantedBy=default.target\n')
    tunnel_unit.write_text('[Unit]\nDescription=Codex Loop private WSL MCP tunnel\n'
        'Requires=codex-loop-wsl-http.service\nAfter=network-online.target codex-loop-wsl-http.service\n\n'
        '[Service]\nEnvironmentFile=%h/.config/codex-loop-wsl/connection.env\n'
        'UnsetEnvironment=MCP_COMMAND MCP_SERVER_URL MCP_EXTRA_HEADERS MCP_DISCOVERY_EXTRA_HEADERS\n'
        'Environment=MCP_MAX_CONCURRENT_REQUESTS=64\n'
        'ExecStart=%h/.local/bin/tunnel-client run --profile codex-loop-wsl --mcp.max-concurrent-requests 64 '
        '--mcp.startup-wait-timeout 20s --health.url-file %h/.config/codex-loop-wsl/health.url\n'
        'Restart=on-failure\nRestartSec=5\nKillMode=control-group\nUMask=0077\n\n[Install]\nWantedBy=default.target\n')
    subprocess.run(['systemd-analyze', '--user', 'verify', str(http_unit), str(tunnel_unit)], check=True)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'stop', 'codex-loop-wsl-tunnel.service'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'codex-loop-wsl-http.service'], check=True)
    subprocess.run(['python3', str(app / 'operate.py'), 'start'], check=True)
    keepalive = home / '.local/bin/codex-loop-wsl-keepalive'
    keepalive.write_text('#!/bin/sh\nexec /bin/sleep infinity\n'); keepalive.chmod(0o700)
    print(json.dumps({'upgraded': True, 'backup': str(backup), 'max_requests': 64}))


if __name__ == '__main__':
    main()
