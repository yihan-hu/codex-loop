# Codex Loop WSL MCP

Connect ChatGPT web/phone to a Windows computer's WSL terminal through OpenAI Secure MCP Tunnel. This optional stdio server offers `wsl_status`, `wsl_exec`, `wsl_poll` and `wsl_stop`. It does not launch another AI model or control the Windows desktop.

Requirements: Ubuntu/WSL 2 on x86-64, Node.js 20+, npm, Python 3, bubblewrap and a working systemd user session. Obtain missing bubblewrap from the official Ubuntu distribution. The npm lockfile uses the maintained MCP SDK v1 compatibility line.

## Install inside WSL

From this directory:

```bash
npm ci --ignore-scripts --no-audit --no-fund
python3 install.py --root /absolute/path/to/projects
```

The root must be an explicit existing Linux directory. Repeat `--root` only for additional intentionally authorized directories. Installation runs real sandbox/MCP/lifecycle tests, copies the server to `~/.local/share/codex-loop-wsl`, and downloads the latest official [tunnel-client](https://github.com/openai/tunnel-client/releases/latest) binary after verifying its published SHA-256 and size. No credentials are collected and no tunnel is activated.

## Connect your account

1. Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels). Create a tunnel associated with the intended ChatGPT workspace and Platform organization. Creation needs Tunnels Read + Manage; the runtime principal needs Read + Use.
2. Obtain a runtime API key with tunnel permission. Use a runtime key, not an admin key. Enter it only in your own WSL terminal, never in a chat or shell argument.
3. Run `~/.local/bin/codex-loop-wsl-connect`. It prompts for the tunnel ID and hidden key. If the tunnel ID is already known, pass `--tunnel-id tunnel_...` to skip that prompt; the key still requires hidden entry in an interactive terminal. The script generates the official stdio profile, runs `tunnel-client doctor`, then enables a systemd user service. The local key is saved with mode 600 at `~/.config/codex-loop-wsl/connection.env`, outside the shell sandbox.
4. Enable developer mode in ChatGPT's Security and login settings. Add a connection in [ChatGPT Plugins](https://chatgpt.com/plugins), choose **Tunnel**, and select the same tunnel. Workspace/account policy may control availability.
5. Select the new MCP connection in a fresh chat and call `wsl_status`, then execute `uname -s; pwd` with an explicitly selected cwd under the reported roots. This verifies the connection independently of any Skill.
6. To use the existing Codex Loop Skill, register this connector in the private Drive Host Profile after the connection works. Preserve existing Mac/RDC entries, add a distinct computer ID for this Windows/WSL host, and save that ID as the execution default if requested. No WSL-specific Skill upload or route action is needed; the Skill discovers the selected connector's actual tool schema. Provision a compatible Local Codex Loop runtime separately when the Skill needs it; this MCP installer does not install or update that runtime.

The connector script fails for an existing profile instead of silently replacing it. Use the official tunnel-client CLI to review/update an existing connection explicitly.

## Operation

```bash
systemctl --user status codex-loop-wsl-tunnel.service
systemctl --user stop codex-loop-wsl-tunnel.service
systemctl --user start codex-loop-wsl-tunnel.service
journalctl --user -u codex-loop-wsl-tunnel.service -n 40 --no-pager
```

The loopback operator URL is saved to `~/.config/codex-loop-wsl/health.url`; its `/readyz` should return success before testing ChatGPT. A running service alone does not prove the workspace association or a successful ChatGPT tool call. Keep raw HTTP logging disabled.

systemd supervision works while WSL runs. Installation adds no Windows startup task, sleep override or inbound firewall port. The computer must be awake and online for web/phone calls.

Bubblewrap exposes writable project roots and the secret-free lifecycle runtime; other user files, tunnel credentials and Windows mounts are absent. A private persistent `/tmp` preserves routing state across tool calls. Network access is enabled. Native Git authentication is separately configured; never authorize a credential directory as a project root. Configured roots limit filesystem access; the Host Profile records preferences, not access grants or online status.

The standalone server is excluded from the consumer Skill ZIP. Keep the current installed Skill; adding this connection does not require replacing it. MCP registration and private Host Profile configuration are separate operations.

Official documentation: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [ChatGPT connection setup](https://developers.openai.com/plugins/deploy/connect-chatgpt).
