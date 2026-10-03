# Progress visibility

Use this reference whenever Codex Loop enters a multi-step/durable objective or the user asks to tune how often progress is surfaced.

## Default behavior

Progress visibility is a host-facing behavior policy, not a second execution engine. Codex Loop does not manufacture timestamps, tool-call events, or hidden host state; it tells the ChatGPT host/model how aggressively to surface concise user-visible progress while the host remains authoritative for actual message timing and tool execution.

The default is **standard** for substantive work and **low-noise** for lightweight/trivial work:

- lightweight work: no periodic progress messages or upfront plan;
- substantive work: send a short upfront plan when useful and use the host’s normal progress cadence; an explicit enhanced preference uses approximately **15 seconds** or **3 substantive tool calls**;
- material findings, blockers, meaningful state transitions, or a user steer should be surfaced immediately when `material_event_updates` is enabled;
- do not print low-level tool logs, repetitive status, internal bookkeeping, credentials, hidden prompts, or chain-of-thought;
- updates should say what materially changed, what was learned, and what happens next;
- if the user interrupts during long work, acknowledge the new instruction promptly and integrate the steer before continuing.

The cadence is approximate because message timing belongs to the ChatGPT host. Higher-priority host/system rules always win.

## Effective policy

For a Codex Loop objective, consult the effective policy when the runtime is available:

```bash
python3 scripts/codex_loop.py progress-policy --work-shape substantive
```

For a direct task:

```bash
python3 scripts/codex_loop.py progress-policy --work-shape lightweight
```

A verified missing profile uses defaults. A corrupt, unsafe, or unreadable profile is an error, never a fallback or permission to overwrite it.

## Private configuration

User preferences live in `~/.codex-loop/host.json` (or under `CODEX_LOOP_HOME` when the host overrides that root). This file is host-local/private state: it is outside the repository, outside `skill.zip`, and must never be copied into GitHub source transport artifacts.

The progress node is part of the unified Private Host Profile schema v4 (see `host-profile.md`):

```json
{
  "schema_version": 4,
  "progress_visibility": {
    "mode": "standard",
    "interval_seconds": 15,
    "tool_call_interval": 3,
    "upfront_plan": true,
    "material_event_updates": true
  }
}
```

`progress-config` is a compatibility facade over the same Host Profile implementation; it does not own a second config file or schema. Unsupported old schemas require an explicit private-profile upgrade; no automatic schema adapters remain.
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

The writer preserves unrelated Host Profile sections such as browser, persistence, Web-publish, and workspace defaults. A malformed existing host file is never silently overwritten. Read-only policy resolution reports corrupt or unsafe profiles without changing them.
