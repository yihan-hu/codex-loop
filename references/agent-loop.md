# Agent Loop Reference

Treat a coding turn as a state machine:

`ORIENT -> OBSERVE -> ACT -> OBSERVE -> VERIFY -> REVIEW -> GATE -> DONE`

Allow transitions back whenever evidence changes. A tool call is never a completion state; its output becomes evidence for the next iteration.

## Orient

Establish the requested outcome, repository root, local instructions, protected existing changes, acceptance criteria, and likely validation path. Bootstrap runtime state once and use `snapshot` to establish generation zero.

## Observe

Prefer high-information evidence: exact failures, implementation around the failure, call sites, configuration, repository-native test commands, current diff, and current runtime world state. Avoid exhaustive architecture discovery before taking a useful action.

## Act

Choose the smallest coherent mutation or command. Preserve unrelated work. Use guarded writes when a known preimage matters. Use host-specialized tools when they materially outperform local execution, then record/reconcile their effects.

## Observe again

Inspect exit status, stderr, output, process state, changed files, and external results. Do not infer success from a syntactically valid command.

## Verify

Run the smallest validation that demonstrates the requested behavior from the intended cwd. Validation identity includes command plus cwd and is attached to a mutation generation; any later mutation invalidates its freshness. Acceptance-criterion and steer evidence is also generation-bound and must be re-evaluated after mutation.

## Review

Inspect the final change set for accidental edits, stale comments, debug code, incomplete TODOs, generated churn, and mismatch with repository conventions. Mark review freshness only after this inspection.

## Gate

Supply acceptance evidence, then run `completion`. Continue on `CONTINUE`; report a real blocker on `BLOCKED`; finish only on `PASS`.
