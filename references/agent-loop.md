# Agent Loop Reference

Use the upstream Codex shape as the default:

`ORIENT -> ACT <-> OBSERVE/TEST/REPAIR -> OPTIONAL REVIEW -> FINAL ACCEPTANCE -> DONE`

Do not turn these labels into mandatory runtime states. They describe how the model should work, not a workflow engine.

## Orient

Preserve the initial user request plus later user corrections as authority; do not replace them with a broader working objective. Every selected invocation already has one lifecycle and retained request authority. For repository/filesystem work, run `orient --task-id TASK --cwd REPO` before the first mutation so the model sees current root-to-cwd instructions and pre-existing dirty/protected work. Before first touching a deeper instruction scope, run `instructions --task-id TASK --cwd PATH`. If instruction discovery is incomplete or the workspace probe is degraded, do not mutate until trustworthy complete state is available. Keep the same lifecycle and request/steers throughout; never create a second authority. Use a short three-state plan only when it helps coordination or resume.

## Act and observe

Take the smallest coherent useful action, inspect the result, and continue. Prefer actual repository/tool evidence over summaries. Do not fix unrelated issues merely because they are visible.

## Verify

Run the smallest check that demonstrates the changed/requested behavior. Broaden only when it adds useful regression confidence. After a repair, rerun the checks plausibly affected by that repair; existing repository tests are the default regression mechanism.

## Review

Trivial/well-covered changes need no separate reviewer. Large, unfamiliar, weakly tested, cross-module, or high-risk changes may get one Codex-style semantic review over the actual diff/change. Report only discrete actionable findings. If there are no substantive findings, stop rather than asking for another PASS.

## Resume

Resume the same lifecycle from its retained request/steers, short plan, checkpoint notes, and current repository/tool state; never re-bootstrap merely because the user says continue/resume. Completed plan steps are continuity hints, not proof that current reality is unchanged. Re-observe anything that can have gone stale.

## Final acceptance

Before finishing, re-read the effective request, inspect the final state, and compare the change with the orientation snapshot and applicable repository instructions. Preserve pre-existing user work and remove any change that is merely beneficial rather than required. If a material requirement remains unsatisfied, continue. Otherwise finish. The deterministic `completion` command exists only to catch machine-observable blockers such as unfinished plan steps, missing required validation, unresolved external/process state, protected-work violations, or workspace mismatch.
