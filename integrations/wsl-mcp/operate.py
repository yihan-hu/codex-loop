#!/usr/bin/env python3
"""Start, inspect or stop the private WSL services without showing credentials."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request

CONFIG = Path.home() / '.config/codex-loop-wsl'
HTTP = 'codex-loop-wsl-http.service'
TUNNEL = 'codex-loop-wsl-tunnel.service'


def health():
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18790/healthz',
            headers={'Authorization': (CONFIG / 'http-auth.header').read_text().strip()}), timeout=3) as res:
        return json.load(res)


def ready():
    url = (CONFIG / 'health.url').read_text().strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1':
        raise RuntimeError('Unexpected tunnel health URL')
    with urllib.request.urlopen(url.rstrip('/') + '/readyz', timeout=3) as res:
        return res.status == 200


def wait(probe):
    for _ in range(30):
        try:
            value = probe()
            if value:
                return value
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise SystemExit('Readiness failed; inspect systemctl --user status for the WSL services.')


def control(action, unit):
    subprocess.run(['systemctl', '--user', action, unit], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop'])
    args = parser.parse_args()
    if args.action == 'stop':
        control('stop', TUNNEL)
        control('stop', HTTP)
        print(json.dumps({'stopped': True}))
        return
    if args.action == 'start':
        control('start', HTTP)
        wait(health)
        control('start', TUNNEL)
    metrics = wait(health) if args.action == 'start' else health()
    value = wait(ready) if args.action == 'start' else ready()
    pids = {}
    for unit in (HTTP, TUNNEL):
        pids[unit] = subprocess.check_output(['systemctl', '--user', 'show', unit, '--property=MainPID', '--value'], text=True).strip()
    print(json.dumps({'ready': value, 'http': metrics, 'service_pids': pids}))


if __name__ == '__main__':
    main()
