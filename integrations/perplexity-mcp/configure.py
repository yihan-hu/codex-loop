#!/usr/bin/env python3
"""Configure this Mac privately, compile the UI helper, and create a scoped example."""
import argparse
import json
import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--my-mac-directory', required=True, help='Existing local My Mac HTTP adapter, with http-launch.json and MCP SDK')
    parser.add_argument('--workspace', required=True, help='Existing user-authorized project directory')
    parser.add_argument('--runtime-cli', default=str(HERE.parents[1]/'scripts/codex_loop.py'))
    parser.add_argument('--node', default=shutil.which('node'))
    parser.add_argument('--cloudflared', default=shutil.which('cloudflared') or str(pathlib.Path.home()/'Library/Application Support/PerplexityCodexLoop/cloudflared'))
    parser.add_argument('--port', type=int, default=31843)
    args = parser.parse_args()
    root = pathlib.Path(args.workspace).expanduser().resolve(strict=True)
    backend = pathlib.Path(args.my_mac_directory).expanduser().resolve(strict=True)
    runtime = pathlib.Path(args.runtime_cli).expanduser().resolve(strict=True)
    if not root.is_dir() or not runtime.is_file() or not (backend/'http-launch.json').is_file():
        raise ValueError('Need an existing workspace, runtime CLI and My Mac HTTP launch file')
    if not 1024 <= args.port <= 65535:
        raise ValueError('Choose a valid unprivileged port')
    for binary in [args.node, args.cloudflared]:
        if not binary or not os.access(binary, os.X_OK):
            raise ValueError('An executable Node.js and cloudflared are required')
    # Verify the exact APIs/dependencies used by server.mjs, before writing config.
    probe = "import{createRequire}from'node:module';import{DatabaseSync}from'node:sqlite';const r=createRequire(process.argv[1]);r('@modelcontextprotocol/sdk/server/index.js');r('ajv');"
    subprocess.run([args.node, '--input-type=module', '-e', probe, str(backend/'package.json')], check=True, capture_output=True)
    app = pathlib.Path.home()/'Library/Application Support/PerplexityCodexLoop'
    state = app/'state'; state.mkdir(parents=True, exist_ok=True, mode=0o700); state.chmod(0o700)
    key = state/'https-api-key'
    if not key.exists():
        with key.open('x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
            stream.write(secrets.token_urlsafe(48)+'\n')
    key.chmod(0o600)
    if len(key.read_text().strip()) < 40:
        raise ValueError('Existing bridge key is unexpectedly short; inspect it privately')
    binary = app/'bin/perplexity-ui'; binary.parent.mkdir(exist_ok=True, mode=0o700)
    subprocess.run(['swiftc', '-O', str(HERE/'perplexity-ui.swift'), '-o', str(binary)], check=True)
    config = {'myMacDirectory': str(backend), 'runtimeCLI': str(runtime), 'python': sys.executable,
              'stateDirectory': str(state), 'defaultWorkspace': str(root), 'backendTempDirectory': tempfile.gettempdir()+'/',
              'httpAuthFile': str(key), 'httpPort': args.port, 'node': str(pathlib.Path(args.node).resolve()),
              'cloudflared': str(pathlib.Path(args.cloudflared).resolve())}
    if (HERE/'config.json').exists():
        config['localSkills']=json.loads((HERE/'config.json').read_text()).get('localSkills',{})
    target = HERE/'config.json'; target.write_text(json.dumps(config, indent=2)+'\n'); target.chmod(0o600)
    example = {'workspace': str(root), 'goal': 'Project scope template; shortcut.py supplies each actual user task',
               'allowed_files': ['draft.md', 'review.md', 'final.md'], 'required_files': ['final.md'],
               'allowed_commands': [], 'max_rounds': 12, 'min_rounds': 1, 'round_timeout_seconds': 900,
               'max_approvals_per_round': 16}
    profile = state/'project-example.json'
    if not profile.exists():
        profile.write_text(json.dumps(example, indent=2)+'\n'); profile.chmod(0o600)
    print(json.dumps({'configured': str(target), 'ui_helper': str(binary), 'project_example': str(profile),
                      'next': 'Review the project scope, save it with shortcut.py save NAME CONFIG --default, then start manage.py. No service has been started or restarted.'}, indent=2))


if __name__ == '__main__':
    main()
