# Private Host Profile

`~/.codex-loop/host.json` (or a private `CODEX_LOOP_HOME/host.json`) is the single private user-instance preference/locator profile. It is never task state, permission, or observed capability truth. Follow `host-profile-drive.md` to restore and save the current user's account-bound Drive copy.

## Schema v4 and empty-profile defaults

```json
{
  "schema_version": 4,
  "progress_visibility": {
    "mode": "standard",
    "interval_seconds": 15,
    "tool_call_interval": 3,
    "upfront_plan": true,
    "material_event_updates": true
  },
  "browser": {
    "preferred_target": "cloud_browser",
    "allow_local_chrome_fallback": false
  },
  "interaction": {"language": "follow_user"},
  "web_publish": {"provider": "google_drive", "staging_folder_id": null},
  "workspace": {"environments": {}},
  "execution": {"default_target": "web", "connections": []},
  "drive": {"cache_folder_paths": []},
  "persistence": {"task_backend": "off", "host_profile_backend": "auto"}
}
```

A verified missing file, an empty current-version profile, or omitted preference fields use these defaults in memory. Reading defaults does not create a file or upload to Drive. Unsafe files, corrupt JSON, unsupported schemas, wrong-account envelopes, ambiguous discovery, and transport errors fail with their actual error; never treat them as empty or overwrite them with defaults. This version directly replaces the older workspace/global-root model. Update an older private profile explicitly, retaining the user's unrelated preferences; the runtime has no legacy routing or schema adapters.

`follow_user` uses the current user's language. An explicit language preference may override it, but never infer language from computer names, filesystem paths, or the author account. Standard progress uses the host's normal cadence and reports material progress, failure, or required user input; simple work has no upfront plan or periodic updates. Enhanced cadence remains an optional explicit preference.

## Environment-owned locations

Each key in `workspace.environments` matches a connection's `computer` identifier. Here computer means an **execution environment with one filesystem**, not just physical hardware. Mac, Windows, WSL distributions, and separate containers need different identifiers even if they run on the same physical computer.

```json
{
  "workspace": {
    "environments": {
      "laptop": {
        "default_root": "/absolute/path/to/work",
        "projects": {"example": "/absolute/path/to/work/example"},
        "runtime_directory": null,
        "state_directory": null,
        "git_metadata_root": null
      }
    }
  }
}
```

Every environment location field is optional: default root, runtime directory, state directory, and `git_metadata_root` default to null; projects default to an empty map. All configured paths are absolute locators interpreted on that environment. Never expand or resolve a remote locator on the Web host. `runtime_directory` points to the dedicated runtime checkout (containing `scripts/codex_loop.py`); `state_directory` is the private `CODEX_LOOP_HOME`, whose `runtime/` holds lifecycle state. Null uses the standard locations `~/.codex-loop/runtime-src` and `~/.codex-loop`, expanded and checked on the selected environment. These runtime defaults never substitute for a missing task workspace.
`git_metadata_root` is an optional host-local root for Git metadata belonging to registered shared worktrees. When set, project alias `NAME` maps to `<git_metadata_root>/NAME`. It is consulted only after the registered project's normal Git probe fails, so ordinary same-host Git access has no additional repair path. The field is a locator, not a grant, and must not point into a shared/synced worktree.

Projects map canonical aliases to absolute directories. Resolve a saved project through the pinned route using `route-check --project ALIAS`; when a local grant registry is needed, materialize and canonicalize that exact project location on the selected environment before granting. The profile is the editable source of saved project locations; the local registry entry for a saved alias is only its derived grant lookup. Reconcile a stale entry from this source, invalidating its old grant, rather than choosing one location arbitrarily. Conversation-only extra directories may use the registry independently and must not be saved as preferences without user intent.

## Selection and directory admission

An explicit current Web/environment/connection selection wins over the saved execution default. Selecting a local environment with missing configuration or permissions never switches to Web.

For local filesystem work, use the current-task authorized absolute directory first, otherwise an explicitly named saved project, otherwise that environment's default root. A continued lifecycle uses its already bound exact directory; pass it as the task directory, rather than relocating it to a later default. If no directory is available, block the directory-dependent operation and ask the user to specify this task's directory or save an environment default. Do not guess from home, shell cwd, a connector's allowed roots, the first known project, or a disk search. Ordinary discussion and workspace-independent lifecycle queries do not require a directory.

A locator is not a grant. Before passing `--workspace-granted`, the host must observe current user/task path authority and verify the actual directory and realpath against the selected connector's authorized roots. A saved or task directory that is missing, not a directory, or denied by the connector blocks access; do not silently choose another directory or create the missing one without user intent. Registry grants and Git lifecycle bindings stay separate (`KNOWN != GRANTED != BOUND`).

New routes snapshot their selected environment default/runtime/state locations. Named project lookups read the current controller profile, so saving or changing an alias is immediately visible. Existing lifecycle bindings always pass their bound directory as `--local-root`; preference edits never move that binding. Connection changes within the same environment retain the default/runtime/state snapshot. A route transition to another environment loads that environment's locations for a new objective.

## Editing and saving

```bash
python3 scripts/codex_loop.py host-config show
python3 scripts/codex_loop.py host-config set execution.connections '[
  {"name":"primary","computer":"laptop","connector":"User MCP","kind":"mcp"}
]'
python3 scripts/codex_loop.py host-config set workspace.environments '{
  "laptop":{"default_root":"/absolute/path/to/work"}
}'
python3 scripts/codex_loop.py host-config set execution.default_target web
python3 scripts/codex_loop.py host-config set interaction.language follow_user
```

Object/list setters replace that field: read its current value and retain unrelated environments, connections, and projects when updating it. A request to remember settings authorizes a preference save; a one-task override does not. Local save results never claim cross-chat durability until Drive provider readback verifies the exact exported bytes.

Never store passwords, tokens, keys, one-time approvals, grants, conversation nonces, active task/branch/worktree state, or claims that a connector is online or a path exists. Verify actual capabilities when needed. User configuration, account IDs, and paths never enter Git, source bundles, or Skill ZIPs. `drive.cache_folder_paths` is local cleanup bookkeeping and is excluded from Drive profile export; temporary Drive storage stays under `ChatGPT-Temporary`.

Temporary Drive cleanup uses `drive-storage.md` and the shared `drive-deletion.md` dispatch/reconciliation adapter. That adapter does not change cache registration, retention, or cleanup eligibility; retained host profiles are never temporary cache.

For a remembered project, prefer `host-project set --computer ENV --name ALIAS --path ABSOLUTE`
or `host-project remove --computer ENV --name ALIAS` using the controller's restored
preference home. These edit one source entry and preserve other raw settings;
then update and verify the same Drive file ID. Registry materialization is temporary
conversation access bookkeeping and never saves a project. Native runtime/profile
alignment is not a prerequisite for saving a remote locator.
