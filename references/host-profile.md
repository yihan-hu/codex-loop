# Private Host Profile

`~/.codex-loop/host.json` (or a private session/test `CODEX_LOOP_HOME/host.json`) is the single private user-instance preference/locator profile. It is never repository state, authorization state, or observed capability truth.

## Schema v3

```json
{
  "schema_version": 3,
  "progress_visibility": {
    "mode": "enhanced",
    "interval_seconds": 15,
    "tool_call_interval": 3,
    "upfront_plan": true,
    "material_event_updates": true
  },
  "browser": {
    "preferred_target": "cloud_browser",
    "allow_local_chrome_fallback": false
  },
  "web_publish": {
    "provider": "google_drive",
    "staging_folder_id": null
  },
  "workspace": {
    "default_local_workspace": null
  },
  "execution": {
    "default_target": "web",
    "connections": []
  },
  "drive": {"cache_folder_paths": []},
  "persistence": {
    "task_backend": "off",
    "host_profile_backend": "auto"
  }
}
```

Missing config uses these built-in defaults. A preference never asserts capability or permission: `preferred_target=cloud_browser` does not prove Cloud Browser exists, and a workspace alias never means the path is granted or bound. `KNOWN != GRANTED != BOUND` remains authoritative.

The execution default and ordered connection locators are persistent preferences, described in `local-connections.md`. `route-init` consumes them for a new conversation, with the current user's target/connection override taking precedence. The selected `workspace_mode` and `local_connection`, interaction/deployment targets, and audit evidence live in the private conversation-scoped routing file. An existing session or lifecycle is not redirected by later preference changes. Path grants, current-task authorization, and observed capabilities never persist here.

## Across new conversations

Follow [Drive-first recovery and saving](host-profile-drive.md) before selecting Web or Local. Fixed names are `codex-loop/settings/host-profile.json` inside the currently connected user's My Drive. The default `auto` backend restores when Drive is connected, uses defaults when absent, and reports recovery errors. `google_drive` requires a connected Drive; an explicit `local_only` choice disables uploads. Task persistence remains independent and off by default. Runtime import/export validates account-bound configuration; the host connector performs actual provider reads/writes.

## CLI

```bash
python3 scripts/codex_loop.py host-config show
python3 scripts/codex_loop.py host-config get browser.preferred_target
python3 scripts/codex_loop.py host-config set browser.preferred_target cloud_browser
python3 scripts/codex_loop.py host-config set web_publish.staging_folder_id DRIVE_ID
python3 scripts/codex_loop.py host-config set workspace.default_local_workspace piwork
python3 scripts/codex_loop.py host-config set execution.default_target web
python3 scripts/codex_loop.py host-config unset web_publish.staging_folder_id
python3 scripts/codex_loop.py host-config reset progress_visibility
```

`progress-config` remains a compatibility facade over `progress_visibility`; there is only one underlying Host Profile implementation.

## Safety

Reads require a regular, owner-controlled, non-symlink file of bounded size with valid UTF-8 JSON, known schema, and known keys. Unsafe/malformed reads warn and fall back to safe defaults so ordinary work continues. Writes fail closed if an existing profile is unsafe or malformed. Writes use a private sibling temporary file, `0600`, `fsync`, and atomic replace.

Schema v1 `default_local_workspace` migrates into `workspace.default_local_workspace` on write. `default_local_root` remains compatibility input only and is not a new configuration surface.

The profile may be read for non-sensitive global preferences before admission; see `local-connections.md` when its owner is on another computer. Local path resolution requires resolved Local intent (explicit choice or saved default) plus the ordinary path/host checks. The execution resolver fails closed on unsafe/malformed profiles rather than selecting a different location. Other preference reads may still warn/use their safe defaults. This profile never supplies `deployment_target` or authority to reconstruct an existing lifecycle on another host.

Host Profile files, Drive IDs, workspace aliases/paths, browser preferences, credentials, session grants, and task state must never enter Git, source transport artifacts, or Skill packages.

## Drive deletion and cache policy

Host Profile schema v3 keeps `drive.cache_folder_paths` as local-only registry state in `~/.codex-loop/host.json`; it must not be included in Git, task persistence manifests, Drive profile persistence, source bundles, or cross-conversation handoffs. All temporary Drive paths must live under the fixed `ChatGPT-Temporary` root described in `drive-storage.md`; top-level Skill-named folders are reserved for retained archive content. Exact Codex Loop-owned sentinels/staging objects are cleaned when their purpose is complete. Cleanup dispatch/reconciliation uses `drive-deletion.md`; that adapter does not change cache registration, retention, or cleanup eligibility.
