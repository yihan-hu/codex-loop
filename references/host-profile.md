# Private Host Profile

`~/.codex-loop/host.json` is the single user-instance preference/locator profile. It is never repository state, never packaged, and never authorization/capability truth.

Schema v2 groups `progress_visibility`, `browser`, `web_publish`, `workspace`, and `persistence`. Missing/invalid reads degrade to safe built-in defaults; writes fail closed on malformed, unsafe, non-private, symlinked, wrong-owner, oversized, or unknown-key input and use atomic `0600` replacement. Schema v1 `default_local_workspace` migrates to `workspace.default_local_workspace`; `default_local_root` remains compatibility input only and is not extended.

Host Profile may be read before Local mode because preferences are non-sensitive routing hints. Reading `workspace.default_local_workspace` does not activate Local mode, grant a path, or bind a task. `KNOWN != GRANTED != BOUND` remains unchanged.

`host-config show|get|set|unset|reset` is the canonical CLI. `progress-config` remains a compatibility facade over the same implementation.

Built-in browser preference is `cloud_browser`. Resolution order is: explicit user target > hard task requirement (for example, signed-in local session) > Host Profile preference > built-in default > capability degradation. Preferences never fabricate availability. Local Chrome/local Mac targets still require explicit current-task computer-use authorization.
