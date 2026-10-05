# Codex Loop WSL MCP

Connect ChatGPT web/phone to a Windows computer's WSL terminal through OpenAI Secure MCP Tunnel. This optional stdio/Streamable HTTP server keeps the original `wsl_status`, `wsl_exec`, `wsl_poll` and `wsl_stop` tools and adds `wsl_grant_project` / `wsl_revoke_project` for conversation-scoped temporary project access. It does not launch another AI model or control the Windows desktop.

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

systemd supervision works while WSL runs. [Systemd services do not keep WSL alive](https://learn.microsoft.com/en-us/windows/wsl/systemd#how-does-enabling-systemd-affect-wsl-architecture). Keep a Windows-owned WSL session open, or start a hidden keepalive from Windows PowerShell:

```powershell
Start-Process -FilePath 'wsl.exe' -ArgumentList @('-d','Ubuntu','--','sleep','infinity') -WindowStyle Hidden
```

After restarting Windows or stopping WSL, start the keepalive again and run the service start command above. Installation adds no Windows startup task, sleep override or inbound firewall port. The computer must be awake and online for web/phone calls.

Bubblewrap exposes writable project roots and the secret-free lifecycle runtime; other user files, tunnel credentials and Windows mounts are absent. A private persistent `/tmp` preserves routing state across tool calls. Network access is enabled. Native Git authentication is separately configured; never authorize a credential directory as a project root. Configured roots limit filesystem access; the Host Profile records preferences, not access grants or online status.

The standalone server is excluded from the consumer Skill ZIP. Keep the current installed Skill; adding this connection does not require replacing it. MCP registration and private Host Profile configuration are separate operations.

Official documentation: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [ChatGPT connection setup](https://developers.openai.com/plugins/deploy/connect-chatgpt).

## Upgrade an existing connection to HTTP

The updated local MCP tutorial also applies to this WSL adapter. After pausing other chats using this shared connection, install Ubuntu's `python3-yaml` if needed and run:

```bash
python3 upgrade-http.py --check-only
python3 upgrade-http.py
python3 ~/.local/share/codex-loop-wsl/operate.py status
```

This keeps the existing tunnel and control-plane key reference, backs up the old private profile/unit, and creates a separate mode-600 bearer-header file outside the command sandbox. The HTTP listener binds only `127.0.0.1:18790`, validates Host/Origin and authentication, and runs under its own systemd user service without inheriting the Platform key. Tunnel runtime and discovery headers reference the private file. No second tunnel client is started.

Both HTTP and Tunnel execution request limits are 64. SSE streams do not consume execution slots. Commands retain a separate global limit of four running jobs across all sessions; this is not a promise of 64 concurrent compute jobs. Stateful MCP sessions have independent job registries, lazy executors and automatic idle cleanup (two minutes for discovery-only sessions, thirty minutes after tool use). Active requests and running commands prevent idle cleanup. A DELETE closes only its own session. There is no cumulative session-count cap. Discovery does not start a command worker for each session.

Requests without a session ID share one executor but close their own protocol context after each response. They cannot be reliably separated by ChatGPT chat identity. All sessions share project files and durable lifecycle state; concurrent edits of the same files still require coordination. Cleanup does not delete project files or tasks. This adapter already returns plain-text results without MCP App UI metadata or structured configuration panels, preserving the tool safety annotations and actual command output.

`operate.py start` starts the HTTP backend, waits for health, then starts the Tunnel and waits for ready. Repeated starts reuse healthy services and their PIDs. `operate.py stop` stops both services. A Windows desktop launcher should start one hidden WSL keepalive before calling `operate.py start`; its stop counterpart should terminate only that dedicated keepalive, never shut down the entire WSL distribution. Closing the launch window does not stop background services. These launchers do not imply Windows login autostart.

Run `node --test test.mjs http.test.mjs grants.test.mjs` for sandbox/lifecycle/protocol checks, more than twenty discovery sessions, isolated job handles, idle cleanup with a running command, stateless requests, and 64-slot admission/release. Verify a real ChatGPT tool call after refreshing the connection; service health alone is insufficient.


## Temporarily authorize another project

Keep the default workspace roots narrow. Register additional projects **in your own WSL terminal**, outside the command sandbox:

```bash
python3 ~/.local/share/codex-loop-wsl/projects.py example-project \
  "/mnt/c/Users/example/OneDrive/Projects/example-project" --access read-write
```

Use a real existing project path. The default access is `read-only`; request `read-write` explicitly when edits are intended. This writes the fixed private file `~/.config/codex-loop-wsl/projects.json` with owner-only permissions. It is not stored in this Git repository or restored from Drive. Registration makes a project eligible for authorization; it does not mount it into every command. The registry must remain outside all default roots, temporary project roots and the lifecycle runtime. Never register a credential directory. Updating registrations does not require a service restart.

After you explicitly authorize the project for reuse in the current conversation, the assistant calls:

```json
{"project_id":"example-project","access":"read-write"}
```

with `wsl_grant_project`. The response contains a random `grant_id`, the canonical root, allowed access and expiry. The grant defaults to `read-only` even when the local registration permits writes; request `access: "read-write"` only for an explicitly authorized edit. Grants cannot exceed the locally registered access. Each `wsl_exec` accessing the project must include `grant_id`, alongside its normal command/cwd parameters. The project is mounted only into commands carrying this authorization. Commands without it retain the original default roots; other registered projects remain hidden. Read-only projects cannot be written through this mount. A temporary project must not overlap default roots or the shared lifecycle runtime, since temporary grants cannot narrow access already provided there.

Treat `grant_id` as a private bearer capability, not a project preference: do not save it to shared task files, Drive, Git or logs, or give it to another chat. The same authorized conversation can reuse it across tasks. Optional `task_id` is context only and does not bind or restrict the grant. The connector cannot prove that a request came from a particular chat or that the human authorized it; the assistant must obtain explicit user authorization before requesting a grant. Local registration is the enforced upper boundary, and possession of the random grant controls command access. Another chat does not automatically receive an existing grant, but could request its own grant for a locally registered project if the user authorizes it.

A grant expires after **three days without use** (72 hours). Every admitted grant-backed `wsl_exec` and valid `wsl_poll` for one of its jobs resets that idle deadline to three days from the call. Malformed or rejected execution requests, unrelated commands, `wsl_status`, discovery, health probes and merely chatting do not renew it. The backend cannot observe the last chat message. Long-running commands do not renew themselves; observed polling does. There is no absolute lifetime while the user continues using the grant, and no per-task expiry. The old `ttl_seconds` parameter no longer sets a lifetime. It survives HTTP protocol session expiry/reinitialization while the backend stays running, including sessionless calls. Closing a protocol session still terminates that session's own running jobs; it does not revoke the conversation grant. Backend restart clears all grants and ephemeral job handles; durable project/task files remain. Reauthorization is needed for continuation after restart or expiry. A Host Profile project entry never supplies a grant.

On explicit withdrawal of access, call `wsl_revoke_project` with `grant_id`. Do not revoke merely because one task completed when the user authorized reuse in this conversation. Revocation terminates the grant's active process groups across executors and waits for their exit. Automatic expiry also terminates its running commands, because removing an in-memory entry alone would not remove mounts from an existing sandbox. Files are retained. Task completion and chat closure are not detected by this terminal adapter: explicit revocation or the expiry timer performs cleanup. This is a filesystem boundary; it does not undo completed edits or data already sent over the enabled network.

For an existing HTTP installation, update the checkout and run `python3 upgrade-http.py` only after current commands have completed. This copies the new grant module and local registration script as well as the backend. Refresh tool discovery to see the two added tools; old tool names and ordinary default-root calls still work.


When using an existing Codex Loop Skill without changing its lifecycle or routing code, give this instruction in the chat: “Authorize this project for reuse in this conversation. Do not revoke on task completion; revoke after three days without grant use, on explicit withdrawal, or when My WSL restarts.” This explicit scope takes precedence over the existing task-completion revocation default. The server also advertises the new scope in its MCP instructions. A grant does not authorize unrelated work; follow the user's current request for every command. The conversation must retain its capability: the backend cannot identify the web chat or recover a lost capability automatically.

Grant records and their idle timers are in memory only. Retaining a grant does not keep a bubblewrap process alive: a sandbox starts with a command and exits when it finishes. Protocol sessions and their job executors still follow their existing idle cleanup rules independently. Backend restart clears every grant even when the project registration file remains.


## Upgrade succeeded, but the project is still denied

`workspace_roots` lists **default roots**, not temporary mounts. It should stay narrow after a project grant. A bare `wsl_exec` with an extra-project cwd is expected to fail even on the new backend. Check the complete flow:

1. Update the checkout and run `python3 upgrade-http.py` from this integration directory in your own WSL terminal after pausing active work. The upgrader explicitly restarts the HTTP process and verifies its reported version; enabling or starting an already active service alone does not load changed files. The startup CMD can keep calling `operate.py start`.
2. Register the exact project with `python3 ~/.local/share/codex-loop-wsl/projects.py PROJECT_ID "/absolute/project/path" --access read-write`. This is a separate owner action outside the chat sandbox. A saved Host Profile path is not this registry.
3. Check `wsl_status`: it must report `server_version: "0.3.1"`, `grant_policy: "three-day-idle"`, and the project alias under `registered_projects`. An empty list means no projects have been registered locally. These checks describe the running process, not merely the checkout files.
4. Refresh the connection's metadata in [ChatGPT Plugins](https://chatgpt.com/plugins), then verify the actual tools exposed in the conversation include `wsl_grant_project` / `wsl_revoke_project`, and `wsl_exec` accepts `grant_id`. A server update does not guarantee an existing chat's cached definitions change. Follow the [official refresh workflow](https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata); use a fresh chat only to validate discovery if the existing chat remains stale, without recreating the durable Codex Loop task.
5. After explicit authorization, call `wsl_grant_project` for the registered alias. Pass the returned `grant_id` with `cwd` on every `wsl_exec` accessing that project. Verify `pwd` first. Never broaden shared roots, read private connector configuration from the sandbox, or switch to RDC to bypass a missing grant.

Run `python3 upgrade_test.py` for upgrade regressions covering replacement of a running process, rejection of a stale version, and active-command protection. Full protocol/sandbox tests remain `node --test test.mjs http.test.mjs grants.test.mjs`.
