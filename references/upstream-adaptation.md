# Upstream Codex adaptation

Codex Loop follows Codex primarily by **removing orchestration**, not by cloning the Codex runtime. The ChatGPT host remains authoritative for model sampling, ordinary tools, sandboxing, approvals, and conversation context.

## Execution authority and retained context

Public Codex keeps host-owned retained context independent of the replaceable model window and tracks reference/world-state baselines so ordinary turns can emit changes rather than rebuilding a second task specification. Codex Loop ports that invariant in a smaller form:

- exact request + later steers are durable authority;
- no task-level model-written objective/acceptance restatement is created;
- normal model-facing continuation is a thin authority/blocker capsule rather than a telemetry dashboard;
- rich runtime state remains pullable for debugging or specialized workflows without being pushed into every model turn;
- real re-entry re-observes current workspace reality instead of trusting historical validation or summaries.

Relevant upstream surfaces: `codex-rs/core/src/context_manager/history.rs`, `history_user_authorization.rs`, and session rollout reconstruction.

## Project instructions

Public Codex discovers project instructions from project root down to the current working directory, with more-specific scope naturally layering on top. Codex Loop mirrors the behavior through one-time `orient` plus on-demand deeper `instructions` loading. Already-loaded instruction scope is stable authority; it is not repeatedly rediscovered as a lifecycle heartbeat.

Relevant upstream surface: `codex-rs/core/src/agents_md.rs`.

## Native agent loop

Public Codex lets the model repeatedly call ordinary tools and inspect raw tool results until the task is done. Codex Loop therefore keeps its lifecycle out of the ordinary inspect/edit/test/repair path after admission. `next` is state-only; `resume` is the re-entry boundary. Normal validation runs directly through host tools.

## Working plan

Public Codex's plan surface is intentionally tiny: each item has only `step` and `pending | in_progress | completed`, with at most one active item. Codex Loop keeps the same optional working-memory shape. Plan state is not semantic authority and is not a deterministic completion gate.

Relevant upstream surface: `codex-rs/core/src/tools/handlers/plan_spec.rs`.

## Review

Public Codex review favors discrete actionable bugs, rejects speculation/nits, and prefers zero findings when nothing meaningful should be fixed. Codex Loop uses the same policy: at most one ordinary semantic review unless a real repair/risk creates a reason to review again.

Relevant upstream surfaces: `codex-rs/prompts/src/review_request.rs` and `codex-rs/prompts/templates/review/rubric.md`.

## Workspace observation

Codex Loop intentionally does **not** recreate Codex's full world-state runtime. Ordinary orientation uses cheap repository identity/status observations and pre-existing dirty paths. Full content fingerprints, ignored-file watches, generation reconciliation, durable validation receipts, and release lineage remain lazy capabilities for persistence/publication/high-risk boundaries only.

## Current upstream behavioral recheck

Behavior was rechecked against public `openai/codex` main commit `7f83d4922d7e92a36c1c1e4f61159a5815d45360` on 2026-09-15. The current adaptation specifically follows the retained-context/reference-baseline design in `history.rs`, root-to-cwd instruction discovery in `agents_md.rs`, the minimal three-state plan tool, and the actionable-only review rubric. This note is behavioral provenance; frozen copied-resource hashes remain governed separately by the source map/audit.

## Intentionally not emulated

Do not recreate Codex's full session runtime, model loop, token manager, sandbox, approval engine, tool dispatcher, Guardian system, or world-state implementation inside the Skill. Also do not reintroduce criterion-PASS, objective-audit, steer-ack, validation-plan, repeated-fresh-review, lifecycle-heartbeat, or repository-wide-fingerprint ceremonies into the default coding path.
