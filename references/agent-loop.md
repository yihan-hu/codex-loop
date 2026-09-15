# Agent Loop Reference

Use the upstream Codex shape as the default:

`ADMIT -> ORIENT (if needed) -> ACT <-> OBSERVE/TEST/REPAIR -> OPTIONAL REVIEW -> FINAL ACCEPTANCE -> COMPLETION -> DONE`

Only admission is mandatory as a lifecycle action. The other labels describe model behavior, not a workflow state machine.

## Admit

Create or resume exactly one lifecycle before substantive work. Retain the exact request plus later steers; do not generate a second model-written objective/acceptance specification for the same task.

## Orient

For repository/filesystem work, run one cheap `orient` before first mutation. Load current repository identity/status, root-to-cwd instructions, and pre-existing user work. Load deeper instruction scope only before first touching it. Do not establish a full repository content baseline for ordinary coding.

## Act and observe

Work directly through normal host tools. Take the smallest coherent useful action, inspect its real result, repair resolvable failures, and continue. Do not call lifecycle `next` as a heartbeat or wrap ordinary edits/tests in lifecycle bookkeeping.

## Verify

Run the smallest check that demonstrates the requested behavior. Broaden only when it adds useful regression confidence. After a repair, rerun checks plausibly affected by that repair. Passing checks do not imply the user-requested end state is satisfied.

## Review

Use no separate reviewer for trivial/well-covered changes. Large, unfamiliar, weakly tested, cross-module, or high-risk changes may get one Codex-style review over the actual change. Report only discrete actionable findings the author would really fix; no substantive finding means stop reviewing.

## Continue vs resume

While the same model context still owns the task, continue directly with the known `task_id`; no lifecycle heartbeat is required. `next` is only a cheap state read. `resume` is for real re-entry after context/identity loss and re-observes current workspace/instructions before work continues.

## Final acceptance

Before finishing, re-read the exact request plus steers, inspect the actual final artifact/diff/state, preserve pre-existing work, and remove unrelated changes. If a material requirement remains unsatisfied, continue. When the actual end state is true, run one deterministic `completion` check for real machine blockers. An unfinished optional plan is not a blocker.
