# Agent Loop Reference

Use the upstream Codex shape as the default:

`ORIENT -> ACT <-> OBSERVE/TEST/REPAIR -> OPTIONAL REVIEW -> FINAL ACCEPTANCE -> DONE`

Do not turn these labels into mandatory runtime states. They describe how the model should work, not a workflow engine.

## Orient

Preserve the initial user request plus later user corrections as authority; do not replace them with a broader working objective. For repository/filesystem work, run stateless `orient` before the first mutation so the model sees the exact request anchor, current root-to-cwd instructions, and pre-existing dirty/protected work without creating durable task state. Before first touching a deeper instruction scope, run stateless `instructions --cwd PATH`. If the workspace probe is degraded, obtain trustworthy host-visible state before mutation. For durable tasks, persist the same request/steers and baseline rather than inventing a second authority. Use a short three-state plan only when it helps coordination or resume.

## Act and observe

Take the smallest coherent useful action, inspect the result, and continue. Prefer actual repository/tool evidence over summaries. Do not fix unrelated issues merely because they are visible.

## Verify

Run the smallest check that demonstrates the changed/requested behavior. Broaden only when it adds useful regression confidence. After a repair, rerun the checks plausibly affected by that repair; existing repository tests are the default regression mechanism.

## Review

Trivial/well-covered changes need no separate reviewer. Large, unfamiliar, weakly tested, cross-module, or high-risk changes may get one Codex-style semantic review over the actual diff/change. Report only discrete actionable findings. If there are no substantive findings, stop rather than asking for another PASS.

## Resume

Resume from the request, short plan, checkpoint notes, and current repository/tool state. Completed plan steps are continuity hints, not proof that current reality is unchanged. Re-observe anything that can have gone stale.

## Final acceptance

Before finishing, re-read the effective request, inspect the final state, and compare the change with the orientation snapshot and applicable repository instructions. Preserve pre-existing user work and remove any change that is merely beneficial rather than required. If a material requirement remains unsatisfied, continue. Otherwise finish. The deterministic `completion` command exists only to catch machine-observable blockers such as unfinished durable-plan steps, missing required validation, unresolved external/process state, protected-work violations, or workspace mismatch.
