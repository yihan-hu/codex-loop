# Private Host Profile
The connected user Google Drive is the only durable Host Profile. The controller imports it once per new conversation into a private temporary session-profile.json under CODEX_LOOP_PROFILE_HOME. Native Mac and WSL runtimes never read or write preferences; they receive a validated route snapshot.

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
  "persistence": {"task_backend": "off", "host_profile_backend": "google_drive"}
}
```
Missing or disconnected Drive profiles block execution until initial setup or recovery. Invalid profiles also fail closed. The session file exists only on the controller; old native host.json files are not consulted.
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
        "git_metadata_root": null,
        "git_auth": null
      }
    }
  }
}
```
Every environment location field is optional: default root, runtime directory, state directory, and `git_metadata_root` default to null; projects default to an empty map. All configured paths are absolute locators interpreted on that environment. Never expand or resolve a remote locator on the Web host. `runtime_directory` points to the dedicated runtime checkout (containing `scripts/codex_loop.py`); `state_directory` is the private `CODEX_LOOP_HOME`, whose `runtime/` holds lifecycle state. Null uses the standard locations `~/.codex-loop/runtime-src` and `~/.codex-loop`, expanded and checked on the selected environment. These runtime defaults never substitute for a missing task workspace.
`git_metadata_root` is an optional host-local root for Git metadata belonging to registered shared worktrees. When set, project alias `NAME` maps to `<git_metadata_root>/NAME`. It is consulted only after the registered project's normal Git probe fails, so ordinary same-host Git access has no additional repair path. The field is a locator, not a grant, and must not point into a shared/synced worktree.
`git_auth` records a nonsecret expected GitHub HTTPS credential helper per execution environment: `osxkeychain` for Mac or `windows_gcm` for WSL (Windows Git Credential Manager). Null means no managed Git credential policy. Configure the actual helper on each host and verify with noninteractive Git push dry-run; this setting never stores credentials or implies authorization. Install a controller version that supports this field before saving it to Drive.
Project aliases are resolved once on the controller from the Drive-restored profile and included in the selected environment snapshot. The local route reads that frozen project map, never a separate native profile. A new conversation reads updated Drive preferences.

## Selection and directory admission

An explicit current Web/environment/connection selection wins over the saved execution default. Selecting a local environment with missing configuration or permissions never switches to Web.
For local filesystem work, use the current-task authorized absolute directory first, otherwise an explicitly named saved project, otherwise that environment's default root. A continued lifecycle uses its already bound exact directory; pass it as the task directory, rather than relocating it to a later default. If no directory is available, block the directory-dependent operation and ask the user to specify this task's directory or save an environment default. Do not guess from home, shell cwd, a connector's allowed roots, the first known project, or a disk search. Ordinary discussion and workspace-independent lifecycle queries do not require a directory.
A locator is not a grant. Before passing `--workspace-granted`, the host must observe current user/task path authority and verify the actual directory and realpath against the selected connector's authorized roots. A saved or task directory that is missing, not a directory, or denied by the connector blocks access; do not silently choose another directory or create the missing one without user intent. Registry grants and Git lifecycle bindings stay separate (`KNOWN != GRANTED != BOUND`).
New routes pin their selected environment and project locations from one controller-supplied execution snapshot. Existing routes never re-read profile data; explicit preference edits affect a new conversation, not an active task.

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
For remembered projects, use host-project set/remove only on the Drive-restored controller session, then update and verify the original Drive file ID. Do not modify a native host profile.
conversation access bookkeeping and never saves a project. Native runtime/profile
alignment is not a prerequisite for saving a remote locator.
