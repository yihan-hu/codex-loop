# Upstream Codex adaptation

Codex Loop now follows Codex primarily by **removing orchestration**, not by cloning the Codex runtime. The ChatGPT host remains authoritative for model sampling, tools, sandboxing, approvals, and conversation context.

## Working plan

Public Codex uses a very small plan model: each step is `pending`, `in_progress`, or `completed`, with at most one current `in_progress` step. Codex Loop ports that shape directly as optional working memory. It does not add semantic lifecycle states around those steps.

Relevant upstream surface: `codex-rs/core/src/tools/handlers/plan_spec.rs` and the base instructions that describe `update_plan`.

## Review

Public Codex supports reviewing uncommitted changes, a base-branch diff, a commit, or custom instructions. Its review rubric favors discrete actionable bugs, rejects speculative/nit findings, and prefers zero findings when nothing meaningful should be fixed.

Codex Loop uses the same behavioral rule through `references/codex-review.md`. Review stays optional and normally singular.

Relevant upstream surfaces: `codex-rs/prompts/src/review_request.rs` and `codex-rs/prompts/templates/review/rubric.md`.

## Resume and retained context

Public Codex persists rollouts and reconstructs session state on resume; its context manager keeps host-owned retained context separate from the replaceable model window. Codex Loop adopts the invariant rather than porting the Rust runtime wholesale:

- the request/steers/short plan are durable facts when persistence is enabled;
- ordinary model history remains host-owned;
- resume re-observes current workspace/external reality before continuing;
- historical validation is not promoted to current proof.

Relevant upstream surfaces: `codex-rs/rollout/src/recorder.rs`, `codex-rs/core/src/session/rollout_reconstruction.rs`, and `codex-rs/core/src/context_manager/history.rs`.

## Existing-code execution style

Use surgical edits, do not widen scope to unrelated cleanup, and validate the most specific changed behavior before broader checks. Let the model choose the execution path instead of encoding a fixed checker DAG.

## Intentionally not emulated

Do not recreate Codex's full session runtime, model loop, token manager, sandbox, approval engine, or tool dispatcher inside the Skill. Do not retain the former Codex Loop objective-audit, criterion-PASS, steer-ack, validation-plan, focus/scope-drift, or repeated-fresh-review protocols. Host-native equivalents and model judgment are preferred whenever they already solve the problem.
