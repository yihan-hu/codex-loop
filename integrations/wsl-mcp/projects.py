#!/usr/bin/env python3
"""Register a project locally; does not grant access to an MCP task."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_id')
    parser.add_argument('path', type=Path)
    parser.add_argument('--access', choices=['read-only', 'read-write'], default='read-only')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', args.project_id):
        parser.error('Use a simple project ID (letters, digits, underscore or hyphen).')
    if not args.path.is_absolute():
        parser.error('Use an absolute Linux path.')
    root = args.path.resolve(strict=True)
    home = Path.home()
    config = home / '.config/codex-loop-wsl'
    if not root.is_dir() or str(root) in {'/', '/home', str(home), '/mnt', '/mnt/c', '/etc', '/usr', '/proc', '/dev', '/tmp'} or (home / '.config').is_relative_to(root) or config.is_relative_to(root):
        parser.error('Choose a narrow project directory excluding private configuration.')
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = config / 'projects.json'
    if target.is_symlink():
        parser.error('Registry must not be a symlink.')
    value = json.loads(target.read_text()) if target.exists() else {'projects': {}}
    value['projects'][args.project_id] = {'path': str(root), 'access': args.access}
    fd, temporary = tempfile.mkstemp(dir=config)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, indent=2); handle.write('\n')
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f'Registered {args.project_id} ({args.access}); no task grant created.')


if __name__ == '__main__':
    main()
