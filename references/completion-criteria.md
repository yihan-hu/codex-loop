# Completion Criteria

Use these checks before setting criteria to `pass` and before accepting a runtime `PASS`.

## Universal

- The requested behavior exists in the actual workspace, not only in prose.
- Relevant repository instructions and conventions were followed.
- Unrelated user changes were preserved.
- Relevant validation ran after the final substantive mutation when the environment allowed it, from the intended cwd; command identity includes cwd. Authoritative workload PASS is independent from process exit, progress-only evidence never establishes PASS, and cleanup/orphan state is reconciled.
- The final changed-file set was actually reviewed at the current generation.
- Acceptance criteria and steer acknowledgements carry current-generation evidence; stale evidence was re-evaluated.
- Bootstrap acceptance criteria are execution aids, not sufficient completion proof. A fresh objective-level audit was independently derived from the original objective plus referenced current specifications/instructions, and every explicit requirement, numbered item, named artifact, command, test, gate, invariant, and deliverable is proven by authoritative evidence.
- If the objective names another Skill or workflow, authoritative evidence proves that workflow reached its required end state; Codex Loop does not duplicate or infer the domain workflow's internal semantics.
- No external action with unknown/pending outcome remains relevant to completion.
- No managed/task-owned process that should be stopped remains running, orphaned, or internally failed without host-observed resolution. A teardown stall may be a warning for a functional objective only after authoritative workload PASS and successful cleanup; it prevents completion when clean exit is part of the objective.
- Any validation waiver has a recorded reason, any protected-work override has a per-mutation reason, and any expected Git mutation is explicitly scoped to HEAD/branch/index.
- For tasks using canonical release/publish flow, the workspace binding still matches the bound Git repository; the artifact receipt names the audited commit/tree; and any publish action is terminally reconciled from remote readback.
- No installed Skill was edited in place or treated as an ongoing competing source. If an installed Skill bootstrapped a fresh workspace, exact repository/commit freshness evidence proved it matched the latest observed target-branch revision before copying, and only the new workspace became mutable authority. Packaged artifacts and disposable release staging directories were not reused as later development sources.
- Any GitHub -> Web acquisition used the exact-revision `workspace-download.yml` Actions artifact path, verified the artifact digest and source-archive SHA-256 when available, and established the extracted workspace only after integrity checks; shell `git clone`, per-file connector reconstruction, and generic archive URLs were not substituted as ordinary Web acquisition transports.
- A resumed task uses a new freshness domain: persisted criterion PASS/validation/review/objective-audit evidence remains stale/historical, source divergence is explicit, and dispatched/outcome-unknown non-idempotent actions are reconciled before retry.
- Any packaged Codex Loop Skill carries a verified build-generated deployment provenance manifest bound to the exact published repository commit/tree; package SHA remains external receipt evidence.
- Source push, Skill packaging, and ChatGPT deployment were reported as separate states; a Git push or `skill.zip` build was not described as an installed-Skill update without observed deployment evidence.
- For a Web-mode push of the active workspace Skill, post-push deployment reconciliation ran for the exact published revision. `skill-deploy-handoff` is only planning evidence: native UI/surface evidence must come from the platform `skill-creator` or an explicitly equivalent host update primitive and be recorded separately; `UI_SURFACED` is not `DEPLOYED`. If the active workspace Skill is not observably updated, the `chatgpt_skill_update` action remains unresolved and normal completion must not pass merely because GitHub publication, packaging, or an internal handoff succeeded.
- No missing binary transfer bridge was silently replaced with chunked text, base64, heredoc reconstruction, repeated remote writes, or connector payload relay unless the user explicitly authorized that exact transfer method after the limitation was disclosed.
- Any explicitly authorized guarded model relay published a destination only after unique framing, strict Base64 decode, exact decoded size, and full SHA-256 verification; failed one-shot attempts did not heuristically alter payload bytes and surfaced the verified chunk relay only as fallback.
- Browser Control success is claimed only when a supported Browser/Chrome executor attached to the current conversation produced the evidence; RDC/AppleScript or generic GUI automation never satisfies that capability claim.
- Remaining limitations are stated precisely.

## Bug fix

Establish evidence for the failure when practical, fix the correct layer, verify the original failure path, and add proportionate regression coverage.

## Feature

Implement the requested behavior, cover important boundary behavior, update contract-bearing docs/types/tests/config as needed, and verify at least one real path.

## Refactor

Preserve intended behavior, avoid incidental churn, run checks that protect the refactored surface, and inspect the final diff for semantic accidents.

## Environment-limited work

Do not fabricate confidence. Record what was changed, what ran successfully, what could not run, why, and whether the limitation leaves material correctness risk. Mark a criterion blocked rather than passed when the missing validation is required for the user's acceptance condition.
