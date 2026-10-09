# Local connections and saved execution location

For first-time setup, follow [the local MCP tutorial](local-mcp-tutorial.md): connect a private file/shell server through Secure MCP Tunnel, verify it from ChatGPT, then register it here. This document defines the runtime selection contract.

The user's private `~/.codex-loop/host.json` stores connection locators and an execution default. It lives outside the repository and is excluded from Git, source bundles, task persistence, and Skill ZIPs. Never store API keys, endpoint credentials, grants, or online/authorized claims in it. The connected MCP app owns authentication.

## Configuration

Use the existing `host-config` command. `execution.connections` is an ordered list; unique `name` identifies a connection, `computer` groups connections to the same execution environment/filesystem (give Mac, Windows, and each WSL distribution distinct IDs), `connector` is its exact host-exposed app name or ID, `kind` is `mcp` or `rdc`; paths belong only to `workspace.environments[computer]`, never to individual connections. This includes the optional host-local `git_metadata_root` used to repair a registered shared project's host-specific `.git` pointer after a failed normal Git probe.

```bash
python3 scripts/codex_loop.py host-config set execution.connections '[
  {"name":"my-mac","computer":"mac","connector":"My Mac","kind":"mcp"},
  {"name":"second-mac-link","computer":"mac","connector":"My second MCP","kind":"mcp"},
  {"name":"rdc-mac","computer":"mac","connector":"Remote Desktop Commander","kind":"rdc"}
]'
python3 scripts/codex_loop.py host-config set workspace.environments '{"mac":{"default_root":"/absolute/path/to/work"}}'
python3 scripts/codex_loop.py host-config set execution.default_target mac
python3 scripts/codex_loop.py host-config set execution.default_target web
```

Save settings when the user asks to remember/change them. A one-task request such as “use My Mac this time” is an override, not a preference write. Keep unrelated profile fields. Set connections before saving a computer default. `local` as a default means automatic computer selection; a computer ID keeps selection on that exact computer. Web remains the built-in default.

## Read preferences before lifecycle admission

Every new conversation first follows [Drive-first profile recovery](host-profile-drive.md). Restore from the current connected user's fixed private `codex-loop/settings/host-profile.json` before resolving execution. No author account or local machine is a default profile owner. Web uses a fresh session preference home; disconnected Drive or a verified absent file uses built-in defaults. Errors and duplicate matches stop recovery. A persistent native host may retain its own private settings when Drive is unavailable.

Retain that preference cache for Web selection/configuration calls only. Local lifecycle commands run on the selected computer's own runtime home. Saving user-requested preferences must synchronize through the connected user's Drive and verify the provider result; do not write a native computer's profile just to use it as an execution connection. An explicit one-task override and an existing conversation route remain separate from stored defaults.

## Selection and actual execution

1. A new conversation route uses the current user location/connection choice, otherwise the saved default. Within an existing conversation, a one-task override requires an explicit route transition before a new objective; changing defaults alone never rewrites that route. Continuing a lifecycle reuses its original computer/runtime even if defaults changed.
2. For Local selection, match registered connectors to currently attached host tools. Inspect each candidate's actual file/shell capabilities and perform only a minimal read-only host identity probe when needed. Confirm that all entries sharing a computer ID really reach the same execution environment/filesystem. Pass usable connection **names** as `--available-connections-json`; registered names alone are not observations. A candidate must support the task's operations: a read-only file MCP cannot execute the Local lifecycle. No tool definitions are hard-coded into Codex Loop; use the selected app's real schema (for example Desktop Commander's `start_process`, `read_file`, `write_file`).
3. Automatic selection checks custom MCPs first, preserving their array order; RDC entries come afterward in their array order. For a named computer, never select a connection to another computer. With no registered RDC entry, the generic name `rdc` is available only for untargeted `local` selection; identify its actual machine/root before access. Register RDC with a computer ID before using it as that named computer's fallback. Do not install a connector, recharge, or accept a paid service just to satisfy fallback.
4. `--connection NAME` selects only that connection. If it is absent or lacks the needed capability, report the error; never silently use another connection. An explicit Web target plus a local connection is a conflict.
5. Without live observations, the resolver returns `needs_observation`; do not execute from that candidate alone. `route-init` and local `route-transition` refuse unobserved candidates. An empty observed list means none are usable and fails closed. A local-target failure never switches to Web.

```bash
python3 scripts/codex_loop.py execution-resolve --workspace-target local \
  --available-connections-json '["my-mac","rdc-mac"]'
python3 scripts/codex_loop.py route-init --host-surface chatgpt_web \
  --workspace-target mac --connection second-mac-link \
  --available-connections-json '["second-mac-link"]'
```

For the project-gated My Mac HTTP bridge, local lifecycle creation is a special private-runtime call: pin the exact Mac connector, use its canonical Codex Loop runtime path, include the current conversation `session_id`, and issue the normal `bootstrap --request-anchor '…'` command without fabricating a `task_id`. The bridge's existing private `.codex-loop` runtime exception is intentionally not restricted to an allowlist of bootstrap commands; normal terminal and file tools still require both a real `task_id` and an explicit conversation workspace grant. Register a current-user-authorized project through `workspace-materialize` and `workspace-grant` after bootstrap, and preserve that same ID for normal work. `resume --last` and `resume --task-id` in the private runtime similarly recover the lifecycle without granting new project access. An existing connection permission is not a second project authorization request.

Use the returned `local_connection` for **all** Local lifecycle, file, shell, native Git, and transfer calls. Connection-specific schemas stay host-owned. The `local_repository`, `local_transfer`, and `local_host_config` action classes apply equally to custom MCP and RDC. Browser/GUI capability remains separate: a file/shell MCP does not provide Browser Control merely because it can run a terminal command.

`route-init` consumes preferences once and records the selected connection in the private conversation session. Repeated `route-init` for that session returns the same route. For an explicitly requested change use `route-transition --workspace-target COMPUTER --connection NAME --current-user-selection-observed --selection-evidence 'exact user selection'` with the same live observations. An existing task cannot move its lifecycle to another computer; complete/cancel it or obtain an explicitly scoped new objective there. A same-computer transport change must first re-observe that computer and its lifecycle.

Availability selection happens before dispatch. Once a write, command, or publish was dispatched, an error or missing return value requires inspecting that exact operation's status/output. Do not resend it through another connector to escape ambiguity. Connection preferences select location/transport; current task scope, path grants, host confirmations, and existing execution safety checks still govern the action. A saved Local default plus an explicit edit/fix request is Local intent for that request, not permission for unrelated paths or future unrelated writes.

## Pinning during task recovery

Use the installed Skill's conversation route before any Local bootstrap/resume or narrow runtime task lookup. `route-check --action local_lifecycle --session-id SESSION --dispatch-connector 'ACTUAL APP NAME OR ID'` must return `allowed=true` and `dispatch_connector_verified=true` before dispatching the lifecycle command through that app. `route-check` for Local repository actions also receives `--dispatch-connector`; checks without it are permission planning, not verified tool dispatch. Compare the actual host tool's owning app/namespace with the returned `local_connection.connector` before calling it. The CLI checks the supplied identity; it cannot intercept a host tool call that bypasses the check.

Initialize a selected but uninitialized MCP and re-observe its file/shell identity before treating it as unavailable. RDC's device list and Offline status describe RDC only. Do not probe RDC when a selected custom MCP is healthy. Once pinned, a transport change requires explicit user selection, same-computer verification, and route transition; it must not restart or replace the task. A task originally accessed via RDC can be resumed through a user-selected custom MCP if it reaches the same authoritative runtime and exact task. Historical connector names are not current route authority. OneDrive is a filesystem path, not a connector requirement. Do not read global tool history or scan unrelated folders to discover a project.

## Directory-dependent dispatch

Read `host-profile.md` for environment location fields and empty defaults. Selection alone can initialize a route and bootstrap a workspace-independent lifecycle. Before local repository/filesystem work, run `route-check --action local_repository --session-id SESSION --dispatch-connector ACTUAL_CONNECTOR`, supplying `--local-root TASK_DIRECTORY` for an explicit task directory or existing lifecycle binding, or `--project ALIAS` for a saved project; otherwise it uses the pinned environment default. Supply `--workspace-granted` only after observing task path authority and actual directory/realpath access through that connector. A missing default plus no task directory blocks even with a grant flag. A known default alone blocks without path authority. No fallback to cwd, home, connector roots, another environment, or Web. Report the selected environment and concrete missing input or denial. Normal discussion and workspace-independent lifecycle commands remain available.


When the selected WSL connector exposes `wsl_grant_project`, directory access beyond its default roots requires the current user's explicit task authorization and a project registered by the local owner. Ask for a grant using the current lifecycle `task_id` and registered `project_id`; pass the returned private `grant_id` and matching `task_id` to each `wsl_exec` requiring that project, then verify real directory access before declaring `--workspace-granted`. Registration in the Host Profile alone never opens the sandbox. If the project is not registered locally or the installed adapter lacks the grant tool, report that concrete requirement; do not switch connector or broaden shared roots.

Keep the capability in the current conversation's private working context, outside Drive, Host Profile, shared lifecycle files, Git and diagnostics. A task label is not an authenticated chat identity; possession of the capability is required, and another chat must not be given it. Request only the access and duration needed; the locally registered access is an upper bound. Revoke the grant on task completion/cancellation, on a user request to stop access, or before leaving this project. A normal pause can retain it until expiry, but must not be described as revoked. Protocol reconnection alone can reuse an unexpired grant while the backend remains running; backend restart or expiry requires fresh user authorization. Never automatically replay an ambiguous command after reauthorization. See [WSL setup and grant lifetime](https://github.com/yihan-hu/codex-loop/blob/main/integrations/wsl-mcp/README.md#temporarily-authorize-another-project).
