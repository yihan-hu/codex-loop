# Private Host Profile

`~/.codex-loop/host.json` (or the test-only `CODEX_LOOP_HOME/host.json`) is the single private user-instance preference/locator profile. It is never repository state, authorization state, or observed capability truth.

## Schema v2

```json
{
  "schema_version": 2,
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
  "persistence": {
    "task_backend": "off",
    "host_profile_backend": "local_only"
  }
}
```

Missing config uses these built-in defaults. A preference never asserts capability or permission: `preferred_target=cloud_browser` does not prove Cloud Browser exists, and a workspace alias never means the path is granted or bound. `KNOWN != GRANTED != BOUND` remains authoritative.

Conversation routing is deliberately **not** stored here. `workspace_mode`, `interaction_target`, `deployment_target`, and their selection evidence belong to the private conversation-scoped routing file created by `route-init` under the system temp directory. New conversations therefore cannot inherit yesterday's Local/Web/deployment routing merely because Host Profile persists. Host Profile may provide a browser preference or workspace locator, but `route-check` remains authoritative for the current conversation and current action.

## CLI

```bash
python3 scripts/codex_loop.py host-config show
python3 scripts/codex_loop.py host-config get browser.preferred_target
python3 scripts/codex_loop.py host-config set browser.preferred_target cloud_browser
python3 scripts/codex_loop.py host-config set web_publish.staging_folder_id DRIVE_ID
python3 scripts/codex_loop.py host-config set workspace.default_local_workspace piwork
python3 scripts/codex_loop.py host-config unset web_publish.staging_folder_id
python3 scripts/codex_loop.py host-config reset progress_visibility
```

`progress-config` remains a compatibility facade over `progress_visibility`; there is only one underlying Host Profile implementation.

## Safety

Reads require a regular, owner-controlled, non-symlink file of bounded size with valid UTF-8 JSON, known schema, and known keys. Unsafe/malformed reads warn and fall back to safe defaults so ordinary work continues. Writes fail closed if an existing profile is unsafe or malformed. Writes use a private sibling temporary file, `0600`, `fsync`, and atomic replace.

Schema v1 `default_local_workspace` migrates into `workspace.default_local_workspace` on write. `default_local_root` remains compatibility input only and is not a new configuration surface.

The profile may be read for non-sensitive global preferences at any time, but local path resolution still requires explicit Local-development intent and the ordinary current-conversation grant/host authorization checks. It must never be used as a fallback source for `deployment_target` or to reconstruct a missing routing-session file.

Host Profile files, Drive IDs, workspace aliases/paths, browser preferences, credentials, session grants, and task state must never enter Git, source transport artifacts, or Skill packages.

## Drive deletion and cache policy

Host Profile schema v3 adds `drive.delete_enabled` (default false) and `drive.cache_folder_paths`. Both fields are local-only policy/registry state in `~/.codex-loop/host.json`; they must not be included in Git, task persistence manifests, Drive profile persistence, source bundles, or cross-conversation handoffs. Schema v1/v2 profiles migrate in memory and rewrite as v3 on the next explicit Host Profile write.
