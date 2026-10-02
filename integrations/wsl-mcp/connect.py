#!/usr/bin/env python3
"""Interactive local-only credential entry for the already-installed WSL adapter."""
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.parse
import urllib.request


def main():
    home = Path.home()
    config = home / ".config/codex-loop-wsl"
    settings = json.loads((config / "settings.json").read_text())
    tunnel = input("Tunnel ID from Platform tunnel settings: ").strip()
    if not re.fullmatch(r"tunnel_[A-Za-z0-9_-]{16,128}", tunnel):
        raise SystemExit("Invalid tunnel ID")
    if not sys.stdin.isatty():
        raise SystemExit("Enter the runtime API key in an interactive WSL terminal, not a chat or shell argument.")
    key = getpass.getpass("Runtime API key (hidden; saved locally with mode 600): ").strip()
    if not key or any(char.isspace() for char in key) or any(char in key for char in "\"'\\"):
        raise SystemExit("Invalid runtime API key")
    env = dict(os.environ)
    env["CONTROL_PLANE_API_KEY"] = key
    env["CODEX_LOOP_WSL_ROOTS"] = ":".join(settings["workspace_roots"])
    binary = settings["tunnel_client"]
    command = f"/usr/bin/node {shlex.quote(str(Path(settings['app_dir']) / 'server.mjs'))}"
    subprocess.run([binary, "init", "--sample", "sample_mcp_stdio_local", "--profile", "codex-loop-wsl",
                    "--health-listen-addr", "127.0.0.1:0",
                    "--tunnel-id", tunnel, "--mcp-command", command], env=env, check=True)
    subprocess.run([binary, "doctor", "--profile", "codex-loop-wsl", "--explain"], env=env, check=True)
    connection = config / "connection.env"
    if connection.is_symlink():
        raise SystemExit("Credential destination is a symlink; refusing to overwrite it.")
    # Key is never embedded in command arguments, repository files or generated logs.
    fd = os.open(connection, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write('CONTROL_PLANE_API_KEY="' + key + '"\n')
        roots = env["CODEX_LOOP_WSL_ROOTS"].replace('\\', '\\\\').replace('"', '\\"')
        handle.write('CODEX_LOOP_WSL_ROOTS="' + roots + '"\n')
    connection.chmod(0o600)
    # Quote systemd paths and escape specifier expansion independently of shell quoting.
    quote = lambda value: '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    unit = home / ".config/systemd/user/codex-loop-wsl-tunnel.service"
    unit.write_text("[Unit]\nDescription=Codex Loop private WSL MCP tunnel\nAfter=network-online.target\n\n"
                    "[Service]\nType=simple\n"
                    f"EnvironmentFile={quote(connection)}\n"
                    f"ExecStart={quote(binary)} run --profile codex-loop-wsl --mcp.connection-max-ttl 24h "
                    f"--mcp.stdio-send-initialized-notification --health.url-file {quote(config / 'health.url')}\n"
                    "Restart=on-failure\nRestartSec=5\nKillMode=control-group\nUMask=0077\n\n"
                    "[Install]\nWantedBy=default.target\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "codex-loop-wsl-tunnel.service"], check=True)
    health_file = config / "health.url"
    ready = False
    for _ in range(15):
        try:
            url = health_file.read_text().strip()
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise SystemExit("Unexpected non-loopback health URL; inspect the service configuration.")
            with urllib.request.urlopen(url.rstrip("/") + "/readyz", timeout=2) as response:
                ready = response.status == 200
            if ready:
                break
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    if not ready:
        raise SystemExit("Service launch requested, but readiness is unverified. Check systemctl --user status codex-loop-wsl-tunnel.service.")
    print("Local tunnel is ready. In ChatGPT Plugins, add Connection -> Tunnel and select this tunnel.")
    print("Verify a fresh chat with: use Codex Loop WSL and call wsl_status.")


if __name__ == "__main__":
    main()
