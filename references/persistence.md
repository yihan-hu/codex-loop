# Optional cross-conversation persistence

Codex Loop may use a host-connected cloud store as an optional persistence backend when a Web task needs to survive a conversation or ephemeral-workspace boundary. Persistence is a reliability enhancement, not a correctness authority.

## Default and authority

- The default backend is `off`. Codex Loop must work normally when no cloud storage is connected.
- `google_drive` is the first supported host adapter for `state_only` persistence. Google OAuth, connector sessions, refresh tokens, user identity, and file authorization remain owned by the ChatGPT host. Codex Loop never reads, copies, serializes, or commits them.
- Repository source contains only adapter logic, schemas, tests, and policy. User-instance folder IDs, task IDs, manifests, checkpoints, and connection state never belong in GitHub source.
- The authoritative task FSM remains the Codex Loop runtime plus current observed workspace/tool facts. A Drive object is a recoverable snapshot, not a second mutable truth source.

## State-only MVP

The runtime command `persistence-export --backend google_drive` creates a private temporary `state-only.json` manifest. The host may upload that file to a private Drive folder such as `Codex Loop/.runtime/tasks/<task-id>/` and should record the returned Drive file/folder IDs only in task-private host state.

The manifest is schema-whitelisted. It may contain the objective, criterion text/status, task/profile/generation metadata, repository commit/tree lineage, bounded resume metadata, and external-action state with the action identity hashed. It must not contain chain of thought, hidden system/developer instructions, credentials/tokens/cookies, raw tool transcripts, approval/session nonces, environment secrets, or a raw external-action identity.

A new conversation may download a manifest through the host connector and run `persistence-validate`, but deterministic recovery must continue through `persistence-resume-plan` and `persistence-resume`; see `persistence-resume.md`. Resume creates a new freshness domain rather than reopening the old database. Previous criterion PASS, validation, review, and objective-audit evidence becomes stale/historical. Current GitHub/workspace/tool facts always override persisted assumptions. Never blindly repeat a non-idempotent action because a manifest says it was dispatched or outcome-unknown; reconcile the external system first.

Task persistence and Host Profile persistence are separate control planes. The task manifest contains objective/lifecycle recovery evidence; `host.json` contains private user preferences/locators. They must never be merged into one cloud object or truth source. Optional Host Profile cloud sync, if later enabled, must use a private location and never the public-read GitHub staging folder.

## Cleanup lifecycle

Every manifest has `created_at` and `expires_at`. The default refreshable TTL is 30 days for active tasks and 7 days for completed/cancelled tasks. Re-exporting an active task refreshes its expiry. Cleanup is opportunistic: when Codex Loop next has Drive access, it may scan only its bounded runtime folder and apply `persistence-cleanup-plan` to expired objects.

Cleanup is trash-first. If a manifest records a dispatched, outcome-unknown, planned, or unresolved terminal-failure external action, retain it for reconciliation even after expiry. Codex Loop does not permanently delete Drive data; final deletion follows Drive/user retention policy.

## Capability degradation

A missing or disconnected Drive connector is not a task failure when persistence is optional. Report one concise degradation warning and continue with ephemeral runtime state. Persistence becomes a completion requirement only when the user explicitly requires cross-conversation recoverability for the current objective.

Workspace snapshots are deliberately outside the MVP. Git-backed work should normally reconstruct source from verified repository lineage plus state-only recovery. A future `state_and_workspace` mode must have a separate size/privacy policy and explicit user opt-in.
