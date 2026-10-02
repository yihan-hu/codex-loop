# Optional WSL MCP connection

This is a Local terminal adapter for an explicitly selected WSL/Linux workspace. It is independent of RDC, browser control and Skill installation. Base/Web use needs no local setup.

## Connection and authority

The path is ChatGPT -> OpenAI Secure MCP Tunnel -> tunnel-client in WSL -> stdio MCP server -> sandboxed Bash. There is no public MCP listener. Platform tunnel permissions, the ChatGPT workspace association and developer mode remain OpenAI-owned.

Install the standalone server from the optional `integrations/wsl-mcp/` directory in the public Codex Loop repository. It is outside the consumer Skill archive; do not install npm dependencies in a ChatGPT Skill workspace. Follow that directory's README for setup. Credentials belong only to the tunnel client's private host configuration, never to `host.json`, registry, lifecycle state, a repository or chat.

`wsl_status` returns canonical host roots, the runtime root and active jobs. Availability is not authorization. For an explicitly Local WSL request, the narrow pre-admission infrastructure exception permits `wsl_status`, then bootstrap/resume of `RUNTIME_ROOT/runtime-src/scripts/codex_loop.py` through `wsl_exec`, with an explicitly authorized project root as cwd. Do not inspect the repository yet. If the cache is absent, report the setup blocker; never create a ChatGPT-side lifecycle as a substitute.

After admission, run `route-init --host-surface chatgpt_web` on this same WSL runtime and record the observed explicit Local choice using `route-transition`. Keep its opaque session ID only in current conversation context. Resolve the user's exact Linux workspace and current grant under the roots returned by `wsl_status`; registry aliases still need the normal grant. Host roots are capability ceilings, not permission to inspect sibling repositories.

Before repository access require `route-check --action wsl_repository --workspace-granted`. Before source writes additionally require `route-check --action repository_mutate --workspace-granted --current-user-local-source-mutation-authorized`. These assertions must reflect the user's current instruction and workspace-resolution contract; do not invent authorization. Bind the canonical checkout with `orient --task-id TASK --cwd REPO`, then run every later lifecycle command on the same WSL cache through `wsl_exec`. Resume the same task; retain exact requests and steers.

All remaining lifecycle, source-identity, native-Git publication and completion rules apply. This adapter supplies no GitHub credentials. Configure authenticated Git separately through a normal credential flow when needed; do not expose Windows credential stores to make it work. WSL terminal access implies no Chrome or Windows GUI capability.

## Tools and process continuity

- `wsl_status`: read-only roots and active-job metadata.
- `wsl_exec`: an explicitly authorized Bash command with an absolute Linux cwd, timeout and short observation wait. It can write files and access the network.
- `wsl_poll`: observe the same returned job ID. Use the previous `next_offset` for new output. Offsets are bytes; the bounded output ring reports truncation.
- `wsl_stop`: terminate only a server-owned job and its sandbox descendants. Poll if terminal evidence is not yet returned.

Results distinguish `running`/`finished`, exit code, signal and timeout. An initial observation timeout is not command failure. Never re-run an ambiguous write because the tunnel disconnected or an ID expired; first inspect actual repository/external state. Four simultaneous jobs and bounded history limit memory use. Server disconnect/restart cleans up its processes and invalidates IDs. Task authority persists in the WSL lifecycle runtime independently of the job table.

## Host enforcement

Bubblewrap is mandatory and fails closed. Shells receive read-only Linux executables/libraries and selected non-secret OS files, writable configured project roots, the secret-free Codex Loop runtime, and a private `/tmp` that persists across calls for routing continuity. Other homes, Windows mounts, credential stores and tunnel configuration are absent. Cwd authorization resolves symlinks; lexical prefixes cannot authorize outside directories. Never widen roots during ordinary development.

Network access is enabled; this is filesystem/process isolation, not a network sandbox. User scope still governs every command, including downloads and disclosure of source. Arbitrary outside-root administration and browser/GUI control are unsupported.

The computer must be awake, online and running WSL/tunnel-client. systemd supervises the service while WSL runs. Installation does not change Windows startup, sleep, firewall or remote login settings.

Official references: [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels), [connect and test](https://developers.openai.com/plugins/deploy/connect-chatgpt).
