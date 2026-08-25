# Completion Criteria

Use these checks before setting criteria to `pass` and before accepting a runtime `PASS`.

## Universal

- The requested behavior exists in the actual workspace, not only in prose.
- Relevant repository instructions and conventions were followed.
- Unrelated user changes were preserved.
- Relevant validation ran after the final substantive mutation when the environment allowed it, from the intended cwd; command identity includes cwd.
- The final changed-file set was actually reviewed at the current generation.
- Acceptance criteria and steer acknowledgements carry current-generation evidence; stale evidence was re-evaluated.
- No external action with unknown/pending outcome remains relevant to completion.
- No managed process that should be stopped remains running, orphaned, or internally failed without host-observed resolution.
- Any validation waiver has a recorded reason, any protected-work override has a per-mutation reason, and any expected Git mutation is explicitly scoped to HEAD/branch/index.
- Remaining limitations are stated precisely.

## Bug fix

Establish evidence for the failure when practical, fix the correct layer, verify the original failure path, and add proportionate regression coverage.

## Feature

Implement the requested behavior, cover important boundary behavior, update contract-bearing docs/types/tests/config as needed, and verify at least one real path.

## Refactor

Preserve intended behavior, avoid incidental churn, run checks that protect the refactored surface, and inspect the final diff for semantic accidents.

## Environment-limited work

Do not fabricate confidence. Record what was changed, what ran successfully, what could not run, why, and whether the limitation leaves material correctness risk. Mark a criterion blocked rather than passed when the missing validation is required for the user's acceptance condition.
