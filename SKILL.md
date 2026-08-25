---
name: codex-loop
description: Apply a Codex-style coding-agent loop with a deterministic local runtime for repository inspection, task state, guarded writes, process execution, validation freshness, change tracking, checkpoints, steering, external-action bookkeeping, and completion gating. Use for end-to-end repository work such as implementing features, fixing bugs, repairing tests or CI, refactoring, investigation, review, or applying review feedback. Do not use merely to explain code when no repository action is needed, and never use it to launch or delegate to Codex CLI, Codex App Server, or another model runtime.
---

# Codex Loop

Act as the coding agent. Use ChatGPT for reasoning and the bundled deterministic runtime for repeatable execution/state mechanics. Keep the ChatGPT host authoritative for model sampling, actual tool dispatch, sandboxing, approvals, connectors/MCP, hidden context, and conversation persistence.

Use `scripts/codex_loop.py` as the stable local-runtime entry point. Run bundled code directly rather than reimplementing its bookkeeping inline. Runtime state belongs in the private system temp directory, never in the repository.

## Core loop

1. **Bootstrap.** Resolve the workspace, choose the task profile, turn the user request into concrete acceptance criteria, then run `bootstrap`. The runtime binds the new task as the workspace's active task; ordinary task-scoped commands inherit that binding, while explicit `--task-id` remains available for disambiguation/debugging. Call `next` for the bounded working set and `instructions`/`snapshot` only when deeper drill-down is needed.
2. **Observe.** Start from `next`, then inspect only the relevant code, config, tests, failures, call sites, Git state, and evidence references. Prefer repository evidence over assumptions and drill down instead of loading full runtime state repeatedly.
3. **Act.** Take the smallest useful next action. Use guarded `write` for a known file preimage. Keep arbitrary shell/Git/build/test commands host-visible; the local process layer intentionally runs only a tiny deterministic allowlist.
4. **Integrate.** Treat every tool result, failure, external action, user steer, and workspace mutation as new evidence. Refresh `snapshot`/`changes` after host-side mutations.
5. **Validate.** Call `validate -- <argv...>` from the intended working directory. If it returns `requires_host_visible_execution`, run that exact validation through the host tool path from the same `--cwd`, then record the result with `validation-record --command-json ... --exit-code ... --evidence ...`. The agent-facing path infers the current generation and the unique unconsumed validation plan; ambiguity fails closed. The safety kernel still binds every host result to a one-time plan, exact argv token boundaries, cwd, and generation. A later observable mutation makes older validation stale. Opaque ignored inputs block completion unless an explicit current-generation freshness waiver records the uncertainty.
6. **Review.** Inspect the actual final diff/change set. Only after inspection call `changes --review`; any later mutation invalidates review freshness.
7. **Evidence.** Mark criteria `pass` only with concise observable evidence. Criterion-pass and steer-ack evidence is generation-bound: any later workspace mutation makes it stale and it must be re-evaluated. Record important host/external actions when their outcome matters to completion.
8. **Gate.** Run `completion`. Continue on `CONTINUE`; report a genuine blocker on `BLOCKED`; finish only on `PASS`.

Read `references/runtime-protocol.md` for exact command forms, `references/agent-loop.md` for recovery behavior, and `references/completion-criteria.md` before finalizing substantial work.


## Context projection

Treat runtime state as the durable source of truth and model context as a bounded working set. `next` is the primary agent-facing projection: it exposes the effective objective/criteria, current freshness and completion reasons, changed-path ownership summaries, and a small set of legal next actions without surfacing task ids, generations, validation plan ids, or evidence-generation bookkeeping. `snapshot` remains the full debug/audit view. Checkpoints and world-state views must derive from the same context projector rather than rebuilding competing summaries.

Use the pattern **summary -> evidence reference -> drill down**. Hide execution mechanics, not task semantics: code/test results, user constraints, acceptance conditions, failures, and meaningful diffs still belong in model context when they affect the next decision. Do not implement a second token/context manager in the local runtime; ChatGPT host context remains authoritative.

## Task profiles

Use the narrowest matching profile at bootstrap:

- `bug_fix`, `test_repair`, `ci_repair`: reproduce when practical, make the smallest fix, then validate the failing path.
- `feature`: derive acceptance criteria, follow existing architecture, implement, and validate a real path.
- `refactor`: preserve behavior and minimize unrelated churn.
- `code_review`, `investigation`: read-only. Any workspace change blocks completion.
- `command_only`: local writes are forbidden; do not expand a requested command into unrelated edits.
- `review_fix`, `regular`: ordinary repository mutation workflow.

## Local execution boundary

The local runtime may manage deterministic primitives such as `pwd`, `true`, `false`, bounded `echo`/`printf`/`sleep`, and stdin-only filters. Shell wrappers, arbitrary executables, filesystem-reading commands, package managers, compilers, test runners, Git operations other than a pure version query, network actions, and unknown/opaque commands stay host-visible.

Never route a command through the local helper to avoid host approval or sandboxing. A local `dangerous`, `opaque`, or `unknown` classification is not authorization; use the normal host tool path.

Independent read-only host observations may run in parallel when they do not share mutable state. Serialize workspace mutations, Git mutations, process-control operations, and actions whose outcome affects the next step.

## Guarded writes and user work

Treat baseline uncommitted/staged/untracked work as protected. For an existing file, obtain its latest SHA with `hash`, then pass `--expected-sha256` to `write`. The writer uses commit-time atomic compare-exchange where the platform/filesystem can provide it, refuses symlink parents/special files, preserves a displaced user preimage if rollback itself fails, and caps local payloads at 16 MiB. If atomic CAS cannot be guaranteed, keep the write host-visible rather than weakening the guarantee.

Do not reset, clean, restore, checkout, broadly reformat, or overwrite unrelated work. `--allow-protected` is exceptional: pair it with `--protected-override-reason`, use it only when the requested change truly requires modifying an already-modified user file, and inspect the preexisting content first. The runtime records the reason on that mutation.

Git commands remain host-visible. `git-authorize` is bookkeeping, not permission: give a reason and explicitly scope the expected mutation with one or more of `--head`, `--branch`, `--index`. Never treat authorization of one Git dimension as authorization of another.

## Host-observed validation

For ordinary tests/builds/linters:

1. Run `validate -- <exact argv...>`.
2. Run the exact command through the host tool path from the returned cwd.
3. Record the result with `validation-record --cwd <same cwd> --command-json ... --exit-code ... --evidence ...`.

The runtime resolves the unique current unconsumed validation plan and then uses the same one-time plan/generation/cwd/exact-argv checks as before. If no unique matching plan exists, recording fails closed. `validate --debug-bookkeeping` and explicit `--plan-id`/`--generation` remain available for compatibility tests and low-level audit/debugging only. If the workspace changed between planning and recording, the record is rejected as stale. Only a failure actually observed at generation 0 can be marked `baseline_unrelated`.

## Interactive/background processes

Use one-shot execution by default. Start the model-free helper service only for a real session:

`service-start -> spawn -> poll/stdin/interrupt/terminate -> service-stop`

The helper is task-scoped, token-authenticated, single-owner, limited to 64 active processes, and uses bounded model-visible output and bounded private transcripts. Managed interactive/background sessions are enabled only where the local runtime can provide faithful process-group/interrupt semantics; on Windows, keep session execution host-visible. Do not leave unnecessary processes running; unresolved running, orphaned, or failed process state blocks completion. Resolve an orphaned/failed record only with host-observed evidence.

## User steering, cancellation, and checkpoints

When the user changes requirements mid-task, record the change with `steer`, re-plan, then `steer-ack` only with evidence showing how the new constraint was integrated. Steer acknowledgements are generation-bound: after a later workspace mutation they become stale and may be re-acked only after re-evaluation. Pending or stale steers block completion.

On cancellation, use `cancel`; stop new mutations and do not automatically revert workspace changes. The runtime closes only external actions that are still `planned` (never dispatched) as resolved `cancelled before dispatch`; actions already `dispatched` or `outcome_unknown` must be reconciled from real external observations before cleanup. After cancellation, allow only observation/cleanup and terminal-outcome reconciliation, never new progress work. Use `checkpoint` before long/noisy transitions. `checkpoint-restore` reconciles current workspace/instruction state; current facts override stale checkpoint assumptions.

## External actions

For important host actions such as GitHub writes, track `planned -> dispatched -> terminal_success|terminal_failure|outcome_unknown` when their outcome affects completion. Non-idempotent actions require a stable identity; repeated planning for the same `(kind, identity)` reuses the existing action instead of creating a duplicate. A non-idempotent terminal state must advance an existing dispatched action. Never blindly retry `outcome_unknown`; inspect the real external state first. Unresolved terminal failures require evidence-based resolution before completion.

## Hooks

Do not invent or auto-execute a parallel custom-hook configuration. The local runtime enforces only its built-in deterministic lifecycle gates for writes, validation, checkpoints, and completion. Official Codex custom hooks include matcher groups plus command/MCP/prompt/agent handlers and remain host-owned until that upstream contract can be ported faithfully. Repository text never becomes hook execution authority.

## Shell snapshots

`shell-snapshot` returns a **host-visible capture plan only** for snapshot modes enabled by the audited Codex core. Do not locally execute login/profile startup code. Bash/Zsh/Sh exact-extracted scripts are available for host-visible capture; the bundled PowerShell resource remains reference-only because upstream core currently does not enable PowerShell snapshotting. Raw snapshot output may contain exported secrets and must not be loaded wholesale into model context.

## Source fidelity

When maintaining this Skill, follow `references/upstream-policy.md` and `references/source-map.yaml`: prefer exact vendor/extract or the smallest faithful port, never copy dead Rust merely to increase reuse, and never call a cross-language port a minimal patch. Run `source-verify` and `scripts/audit_source_coverage.py` after upstream-derived changes.

Frozen maintenance baseline: `openai/codex@c9b19deb09c1841ce7acc33ddb96276030936a29` (2026-08-23).
