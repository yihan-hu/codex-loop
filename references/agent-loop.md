# Agent Loop Reference

Treat a coding turn as a state machine:

`ORIENT -> FOCUS -> OBSERVE -> ACT -> DIFF REVIEW -> VERIFY -> REVIEW -> GATE -> DONE`

Allow transitions back whenever evidence changes. A tool call is never a completion state; its output becomes evidence for the next iteration.

## Orient

Establish the requested outcome, repository root, local instructions, protected existing changes, acceptance criteria, and likely validation path. Copy the authoritative host-visible user request into `request_anchor` without paraphrasing; later user steers append to it in order, and that effective request remains authoritative over any working objective summary. If relevant user corrections already occurred before bootstrap, record them as ordered steers immediately after bootstrap. Never reconstruct a missing request anchor from a summary. Bootstrap runtime state once; the task is bound to that canonical working tree and shared Git repository identity. Use `next` as the bounded working-set projection and `snapshot` only when full debug/audit state is needed. For concurrent work on one repository, use separate Git worktrees/branches instead of copied source directories.

## Focus

For non-trivial repository work, keep exactly one current `in_progress` subgoal. Add non-goals only when they prevent a likely scope mistake, and record the expected change surface when it can be predicted without speculative architecture work. Focus is working memory, not permission and not a gate. Rebuild it from the request anchor plus ordered steers whenever a user steer or new evidence changes the intended implementation.

## Observe

Prefer high-information evidence: exact failures, implementation around the failure, call sites, configuration, repository-native test commands, current diff, and evidence references surfaced by `next`. Drill down from the bounded summary instead of repeatedly loading the complete runtime state. Avoid exhaustive architecture discovery before taking a useful action.

## Act

Choose the smallest coherent mutation or command. In an existing codebase, make only changes required by the effective request; do not opportunistically refactor, rename, reorganize, fix unrelated bugs, or repair unrelated tests. Prefer the host's native `apply_patch` or another patch-sized edit primitive when available; use guarded writes when a known preimage matters. Use host-specialized tools when they materially outperform local execution, then record/reconcile their effects.

## Delegate when requested

When the workflow asks for a second-opinion worker, enter a bounded read-only isolated task. Prefer native host delegation only when it is actually available; otherwise continue with logical isolation and record the degradation warning. Do not project Main hypotheses by default. The worker independently re-observes evidence and returns structured findings. Finish/abort the isolation before resuming Main; current workspace reality overrides the entry checkpoint. Nested local isolation is flattened/serialized by orchestration rather than treated as a parent-task blocker.

## Observe again

Inspect workload evidence, process/cleanup state, exit status when present, stderr/output, changed files, and external results. After each coherent mutation, inspect the actual diff immediately. Every substantive hunk should be directly explainable from the request anchor, an ordered user steer, or the current subgoal. If a changed path lies outside `expected_change_surface`, treat `scope_drift` as a prompt to narrow/revert the edit or to update focus only when the effective request really requires the extra surface. Workload completion and process termination are independent facts. Do not infer success from a syntactically valid command or from progress-only output such as `100%`; read `execution-supervision.md` when terminal workload evidence appears before process exit.

## Verify

Run the smallest validation that demonstrates the requested behavior from the intended cwd, then broaden only when useful for regression confidence. A broader failing check does not expand the user's task. If semantic review shows a failure is unrelated to the effective request, record that disposition with observable evidence and leave the unrelated code untouched; a current authoritative passing validation is still required when validation is required. The agent-facing validation flow records exact command identity and an `ExecutionObservation` when the host can distinguish workload, process, and cleanup outcomes; ordinary exit-code-only results remain compatibility observations. Generic teardown/lifecycle pathology is handled by execution supervision rather than an agent-invented forced-exit wrapper. Validation identity still includes exact argv plus cwd and is attached to a mutation generation; any later mutation invalidates its freshness. Acceptance-criterion and steer evidence is also generation-bound and must be re-evaluated after mutation.

## Resume after persistence

When recovering across conversations, do not manually reconstruct an old task as current truth. Run `persistence-resume-plan`, observe the required current facts, then `persistence-resume`. Treat old criterion PASS/validation/audit as historical; current source and external-action reality always wins. Never retry a persisted dispatched/outcome-unknown non-idempotent action before reconciliation.

## Review

Review scope fidelity before code quality: every substantive final change must be justified by the effective request. Remove accidental improvements even when they are locally reasonable. Then inspect for behavioral defects, regression risk, stale comments, debug code, incomplete TODOs, generated churn, and mismatch with repository conventions. Review is semantic model work over the current diff; do not replace it with a stored boolean receipt.

## Release and publish when requested

Commit the intended source in the same canonical working tree before packaging. Build release artifacts from the planned Git HEAD into disposable staging, record the commit/tree-bound artifact receipt, and never continue development from the staging directory or artifact. Before publication transport, observe the exact remote head/tree and let the **bundled Codex Loop controller** resolve Web versus Local. Its `publish-enter --controller-abi 1` helper returns a `mode_protocol_reference`; follow that controller-selected mode and never infer another transport from Git terminology, connector availability, GitHub object presence, or remembered behavior. Web publication and Local native Git remain distinct. An ordinary target repository never needs a router/runtime file of its own; only a failure of the bundled controller or an unsupported controller ABI is a controller-level blocker. Read `publication-router.md`.

## Gate

Supply acceptance evidence, then run `completion`. Continue on `CONTINUE`; report a real blocker on `BLOCKED`; finish only on `PASS`.
