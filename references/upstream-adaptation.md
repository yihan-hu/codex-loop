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

## Goal continuation semantics

Public Codex Goals keep the full objective across turns, treat the current worktree/external state as authoritative, classify prior turns as progress / verified wait / no progress, use a concise plan only when the next work is meaningfully multi-step, and treat completion as unproven until requirements are checked against current evidence. Codex Loop ports those semantics into its continuation projection without recreating the Goal scheduler:

- the exact request + steers stay intact across turns;
- current repository/tool/process/external evidence outranks summaries, checkpoints, plans, and historical validation;
- a confirmed live process/session/job is observed through its existing handle rather than restarted after an observation timeout;
- plan updates and status restatements alone are not progress;
- semantic acceptance derives material requirements and verifies them against evidence at matching scope before the final machine completion check;
- `paused` is explicit-user pause, while `blocked` means a genuine current impasse with no remaining safe useful work.

Codex Loop intentionally does **not** port the upstream three-auto-turn blocked threshold because the ChatGPT Skill host cannot schedule autonomous continuation turns. It also does not synthesize token/time budget states because authoritative host budget accounting is unavailable. `resume` reactivates paused/blocked work only as a fresh attempt; a prior blocker must be re-observed and may be set again if it still prevents all useful progress.

Relevant upstream surfaces: `codex-rs/ext/goal/templates/goals/continuation.md`, `codex-rs/ext/goal/src/spec.rs`, and the Goal runtime/idle-dispatch implementation.

## Working plan

Public Codex's plan surface is intentionally tiny: each item has only `step` and `pending | in_progress | completed`, with at most one active item. Codex Loop keeps the same optional durable working-memory shape. Its task board is only a read-only projection (`doing`, `pending`, `done`) of that plan; no second task schema or workflow graph exists. Plan state is not semantic authority and is not a deterministic completion gate.

Relevant upstream surface: `codex-rs/core/src/tools/handlers/plan_spec.rs`.

## Review

Public Codex review favors discrete actionable bugs, rejects speculation/nits, and prefers zero findings when nothing meaningful should be fixed. Codex Loop uses the same policy: at most one ordinary semantic review unless a real repair/risk creates a reason to review again.

Relevant upstream surfaces: `codex-rs/prompts/src/review_request.rs` and `codex-rs/prompts/templates/review/rubric.md`.

## Workspace observation

Codex Loop intentionally does **not** recreate Codex's full world-state runtime. Ordinary orientation uses cheap repository identity/status observations and pre-existing dirty paths. Full content fingerprints, ignored-file watches, generation reconciliation, durable validation receipts, and release lineage remain lazy capabilities for persistence/publication/high-risk boundaries only.

## Current upstream behavioral recheck

Behavior was rechecked against public `openai/codex` main commit `b19cebecc0169097bda7539af03c886e03bdeafe` on 2026-09-24. The current adaptation specifically follows the retained-context/reference-baseline design in `history.rs`, root-to-cwd instruction discovery in `agents_md.rs`, the minimal three-state plan tool, actionable-only review, and the Goal continuation rules for full-objective preservation, evidence-first work, verified wait/no-progress distinction, planning visibility, and completion audit. This note is behavioral provenance; frozen copied-resource hashes remain governed separately by the source map/audit.

## Intentionally not emulated

Do not recreate Codex's full session runtime, model loop, token/budget manager, automatic Goal idle scheduler, native multi-agent runtime, Plan Mode, sandbox, approval engine, tool dispatcher, Guardian system, or world-state implementation inside the Skill. Do not add a Composer DAG on top of the host-native agent loop without concrete evidence that the native execution trajectory is insufficient. Also do not reintroduce criterion-PASS, objective-audit, steer-ack, validation-plan, repeated-fresh-review, lifecycle-heartbeat, or repository-wide-fingerprint ceremonies into the default coding path.
