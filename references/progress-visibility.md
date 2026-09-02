# Progress visibility

Use this reference whenever Codex Loop enters a multi-step/durable objective or the user asks to tune how often progress is surfaced.

## Default behavior

Progress visibility is a host-facing behavior policy, not a second execution engine. Codex Loop does not manufacture timestamps, tool-call events, or hidden host state; it tells the ChatGPT host/model how aggressively to surface concise user-visible progress while the host remains authoritative for actual message timing and tool execution.

The default is **enhanced** for durable work and **low-noise** for direct/trivial work:

- direct path: no periodic progress messages;
- durable path: send an upfront plan when useful, then surface progress after whichever comes first: approximately **15 seconds** or **3 substantive tool calls**;
- material findings, blockers, meaningful state transitions, or a user steer should be surfaced immediately when `material_event_updates` is enabled;
- do not print low-level tool logs, repetitive status, internal bookkeeping, credentials, hidden prompts, or chain-of-thought;
- updates should say what materially changed, what was learned, and what happens next;
- if the user interrupts during long work, acknowledge the new instruction promptly and integrate the steer before continuing.

The cadence is approximate because message timing belongs to the ChatGPT host. Higher-priority host/system rules always win.

## Effective policy

After `lifecycle-assess`, consult the effective policy when the runtime is available:

```bash
python3 scripts/codex_loop.py progress-policy --lifecycle-mode durable
```

For a direct task:

```bash
python3 scripts/codex_loop.py progress-policy --lifecycle-mode direct
```

If the runtime/config surface is unavailable, fall back to the defaults above rather than becoming silent for a long durable objective.

## Private configuration

User preferences live in `~/.codex-loop/host.json` (or under `CODEX_LOOP_HOME` when the host overrides that root). This file is host-local/private state: it is outside the repository, outside `skill.zip`, and must never be copied into GitHub source transport artifacts.

The progress node is part of the unified Private Host Profile schema v2 (see `host-profile.md`):

```json
{
  "schema_version": 2,
  "progress_visibility": {
    "mode": "enhanced",
    "interval_seconds": 15,
    "tool_call_interval": 3,
    "upfront_plan": true,
    "material_event_updates": true
  }
}
```

`progress-config` is a compatibility facade over the same Host Profile implementation; it does not own a second config file or schema. Schema-v1 workspace defaults are migrated when the profile is next written.
Supported modes:

- `enhanced`: use the configured approximate seconds/tool-call cadence;
- `standard`: defer periodic cadence to the host's normal behavior, while retaining concise material updates;
- `quiet`: suppress routine periodic updates; required blockers and configured material events may still be surfaced.

Bounds are intentionally narrow: `interval_seconds` must be 5-120 and `tool_call_interval` must be 1-20.

Read the effective config:

```bash
python3 scripts/codex_loop.py progress-config
```

Persist overrides atomically to the private host file:

```bash
python3 scripts/codex_loop.py progress-config \
  --mode enhanced \
  --interval-seconds 20 \
  --tool-call-interval 4 \
  --upfront-plan \
  --material-event-updates
```

Reset only the progress node to built-in defaults:

```bash
python3 scripts/codex_loop.py progress-config --reset
```

The writer preserves unrelated Host Profile sections such as browser, persistence, Web-publish, and workspace defaults. A malformed existing host file is never silently overwritten. Read-only policy resolution degrades to the enhanced defaults with a warning so progress preferences cannot block substantive work.
