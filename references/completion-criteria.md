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
- For tasks using canonical release/publish flow, the workspace binding still matches the bound Git repository; the artifact receipt names the audited commit/tree; and any publish action is terminally reconciled from remote readback.
- A packaged artifact, installed Skill, or disposable release staging directory was not reused as a later development source.
- Source push, Skill packaging, and ChatGPT deployment were reported as separate states; a Git push or `skill.zip` build was not described as an installed-Skill update without observed deployment evidence.
- No missing binary transfer bridge was silently replaced with chunked text, base64, heredoc reconstruction, repeated remote writes, or connector payload relay unless the user explicitly authorized that exact transfer method after the limitation was disclosed.
- Any explicitly authorized guarded model relay published a destination only after unique framing, strict Base64 decode, exact decoded size, and full SHA-256 verification; failed one-shot attempts did not heuristically alter payload bytes and surfaced the verified chunk relay only as fallback.
- Remaining limitations are stated precisely.

## Bug fix

Establish evidence for the failure when practical, fix the correct layer, verify the original failure path, and add proportionate regression coverage.

## Feature

Implement the requested behavior, cover important boundary behavior, update contract-bearing docs/types/tests/config as needed, and verify at least one real path.

## Refactor

Preserve intended behavior, avoid incidental churn, run checks that protect the refactored surface, and inspect the final diff for semantic accidents.

## Environment-limited work

Do not fabricate confidence. Record what was changed, what ran successfully, what could not run, why, and whether the limitation leaves material correctness risk. Mark a criterion blocked rather than passed when the missing validation is required for the user's acceptance condition.
