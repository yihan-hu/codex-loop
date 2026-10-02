# Codex Loop WSL MCP

Connect ChatGPT web/phone to a Windows computer's WSL terminal through OpenAI Secure MCP Tunnel. This optional stdio server offers `wsl_status`, `wsl_exec`, `wsl_poll` and `wsl_stop`. It does not launch another AI model or control the Windows desktop.

Requirements: Ubuntu/WSL 2 on x86-64, Node.js 20+, npm, Python 3, Git, bubblewrap and a working systemd user session. Obtain missing bubblewrap from the official Ubuntu distribution. The npm lockfile uses the maintained MCP SDK v1 compatibility line.

## Install inside WSL

From this directory:

```bash
npm ci --ignore-scripts --no-audit --no-fund
python3 install.py --root /absolute/path/to/projects
```

The root must be an explicit existing Linux directory. Repeat `--root` only for additional intentionally authorized directories. Installation runs real sandbox/MCP/lifecycle tests, copies the server to `~/.local/share/codex-loop-wsl`, provisions `~/.codex-loop/runtime-src`, and downloads the latest official [tunnel-client](https://github.com/openai/tunnel-client/releases/latest) binary after verifying its published SHA-256 and size. No credentials are collected and no tunnel is activated.

## Connect your account

1. Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels). Create a tunnel associated with the intended ChatGPT workspace and Platform organization. Creation needs Tunnels Read + Manage; the runtime principal needs Read + Use.
2. Obtain a runtime API key with tunnel permission. Use a runtime key, not an admin key. Enter it only in your own WSL terminal, never in a chat or shell argument.
3. Run `~/.local/bin/codex-loop-wsl-connect`. It prompts for the tunnel ID and hidden key, generates the official stdio profile, runs `tunnel-client doctor`, then enables a systemd user service. The local key is saved with mode 600 at `~/.config/codex-loop-wsl/connection.env`, outside the shell sandbox.
4. Enable developer mode in ChatGPT's Security and login settings. Add a connection in [ChatGPT Plugins](https://chatgpt.com/plugins), choose **Tunnel**, and select the same tunnel. Workspace/account policy may control availability.
5. Select this MCP connection and the updated Codex Loop Skill in a new chat. Ask: “Use Codex Loop WSL. Call wsl_status, then use Local mode for /absolute/path/to/projects/my-repository.” Verify the actual WSL roots before editing.

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

Bubblewrap exposes writable project roots and the secret-free lifecycle runtime; other user files, tunnel credentials and Windows mounts are absent. A private persistent `/tmp` preserves routing state across tool calls. Network access is enabled. Native Git authentication is separately configured; never authorize a credential directory as a project root. See [routing and scope](../../references/wsl-mcp.md).

The standalone server is excluded from the consumer Skill ZIP. Package/install the updated Skill separately; neither artifact automatically registers the other.

Official documentation: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [ChatGPT connection setup](https://developers.openai.com/plugins/deploy/connect-chatgpt).
