#!/usr/bin/env python3
"""Install the optional private WSL MCP adapter; do not create credentials or start it."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import urllib.request
import zipfile

SOURCE = Path(__file__).resolve().parent


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "codex-loop-wsl-setup"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024:
        raise RuntimeError("Download exceeds size bound")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", required=True, help="Explicit existing WSL project root; repeat for multiple roots")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("This installer currently supports Linux/WSL x86-64 only.")
    for tool in ("node", "npm", "bwrap", "systemctl"):
        if not shutil.which(tool):
            raise SystemExit(f"Missing {tool}; install it from the official Ubuntu/Node sources first.")
    if any(not Path(root).is_absolute() for root in args.root):
        raise SystemExit("Workspace roots must be absolute Linux paths.")
    roots = [str(Path(root).resolve(strict=True)) for root in args.root]
    if any(not Path(root).is_dir() or root in {"/", "/home", str(Path.home()), "/mnt", "/etc", "/usr", "/tmp", "/proc", "/dev"} or ":" in root for root in roots):
        raise SystemExit("Choose explicit narrow Linux project directories.")
    subprocess.run(["node", "--test", str(SOURCE / "test.mjs"), str(SOURCE / "grants.test.mjs")], cwd=SOURCE, check=True)
    home = Path.home()
    app = home / ".local/share/codex-loop-wsl"
    config = home / ".config/codex-loop-wsl"
    binary = home / ".local/bin/tunnel-client"
    for directory in (app, config, binary.parent, home / ".config/systemd/user"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for filename in ("server.mjs", "grants.mjs", "projects.py", "package.json", "package-lock.json", "connect.py"):
        shutil.copy2(SOURCE / filename, app / filename)
    subprocess.run(["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=app, check=True)
    release = json.loads(download("https://api.github.com/repos/openai/tunnel-client/releases/latest"))
    name = f"tunnel-client-{release['tag_name']}-linux-amd64.zip"
    asset = next(asset for asset in release["assets"] if asset["name"] == name)
    expected = asset.get("digest", "")
    if not expected.startswith("sha256:"):
        raise RuntimeError("Official release has no SHA-256 asset digest; refusing unverified installation.")
    data = download(asset["browser_download_url"])
    actual = "sha256:" + hashlib.sha256(data).hexdigest()
    if actual != expected or len(data) != asset["size"]:
        raise RuntimeError("Official tunnel-client archive digest/size mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [member for member in archive.infolist() if Path(member.filename).name == "tunnel-client" and not member.is_dir()]
        if len(members) != 1:
            raise RuntimeError("Expected exactly one tunnel-client executable")
        payload = archive.read(members[0])
        if not payload.startswith(b"\x7fELF"):
            raise RuntimeError("Expected a Linux ELF executable")
        temp = binary.with_suffix(".new")
        temp.write_bytes(payload)
        temp.chmod(0o700)
        os.replace(temp, binary)
    settings = {"workspace_roots": roots, "app_dir": str(app), "tunnel_client": str(binary),
                "tunnel_client_release": release["tag_name"], "archive_sha256": actual[7:]}
    (config / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    (config / "settings.json").chmod(0o600)
    launcher = home / ".local/bin/codex-loop-wsl-connect"
    launcher.write_text(f'#!/bin/sh\nexec /usr/bin/python3 "{app / "connect.py"}" "$@"\n')
    launcher.chmod(0o700)
    # No service is activated and no API key is collected by installation.
    print(json.dumps({"installed": True, "roots": roots, "app_dir": str(app),
                      "tunnel_client_release": release["tag_name"], "verified_sha256": actual,
                      "next": str(launcher), "connection_active": False}, indent=2))


if __name__ == "__main__":
    main()
