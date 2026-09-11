# Completion Criteria

Use these checks before setting criteria to `pass` and before accepting a runtime `PASS`.

## Universal

- The requested behavior exists in the actual workspace, not only in prose.
- The immutable request anchor plus ordered later user steers is the authoritative effective request. Working objective/criteria summaries did not replace or broaden that authority.
- Relevant repository instructions and conventions were followed.
- Unrelated user changes were preserved.
- Every substantive final diff hunk can be justified by the effective request. Any `scope_drift` outside the expected change surface was reviewed and either narrowed/reverted or explicitly re-anchored because the request required the extra surface; scope drift was not treated as an automatic blocker or automatic permission to expand work.
- Relevant validation ran after the final substantive mutation when the environment allowed it, from the intended cwd; command identity includes cwd. Authoritative workload PASS is independent from process exit, progress-only evidence never establishes PASS, and cleanup/orphan state is reconciled.
- Validation began with the most specific relevant check and broadened only when useful. A broader unrelated failure did not create a new repair obligation; any `unrelated_to_request` disposition contains actual semantic-review evidence and does not substitute for a required current passing validation.
- The actual final changed-file set was reviewed semantically after the last substantive mutation.
- Acceptance criteria and steer acknowledgements carry current-generation evidence; stale evidence was re-evaluated.
- Bootstrap objective/acceptance criteria are execution aids, not sufficient completion proof. A fresh objective-level audit was independently derived from the effective request plus referenced current specifications/instructions, and every explicit requirement, numbered item, named artifact, command, test, gate, invariant, and deliverable is proven by authoritative evidence.
- If the objective names another Skill or workflow, authoritative evidence proves that workflow reached its required end state; Codex Loop does not duplicate or infer the domain workflow's internal semantics.
- No external action with unknown/pending outcome remains relevant to completion.
- Under `continuation_policy=until_terminal`, a no-progress action was re-observed and replanned rather than blindly repeated; modeled external-action recovery still follows its explicit route and authorization rules.
- No managed/task-owned process that should be stopped remains running, orphaned, or internally failed without host-observed resolution. A teardown stall may be a warning for a functional objective only after authoritative workload PASS and successful cleanup; it prevents completion when clean exit is part of the objective.
- Any validation waiver has a recorded reason and any protected-work override has a per-mutation reason. Git state is judged directly against the objective rather than pre-authorized through bookkeeping.
- For tasks using canonical release/publish flow, the workspace binding still matches the bound Git repository; the artifact receipt names the audited commit/tree; and any publish action is terminally reconciled from remote readback.
- No installed Skill was edited in place, auto-selected as fallback source, or treated as competing authority. If the installed-Skill source exception was used, current-turn explicit user authorization was recorded; the installed directory remained read-only; current/latest claims required exact remote equality; explicitly accepted historical/unknown provenance was labeled honestly; and only the fresh copied workspace became mutable authority.
- Any GitHub -> Web acquisition used the exact-revision `workspace-download.yml` Git bundle Actions artifact path, verified artifact digest + bundle SHA-256/size, ran `git bundle verify`, restored a real Git workspace, and required exact target commit/tree before binding it; shell `git clone`, per-file reconstruction, source-only archives, and generic URLs were not substituted as ordinary Web acquisition transports.
- A resumed current-schema task preserves request anchor and ordered steers but uses a new freshness domain: persisted criterion PASS/validation/objective-audit/steer-integration evidence remains stale or pending, source divergence is explicit, and dispatched/outcome-unknown non-idempotent actions are reconciled before retry. Legacy recovery state without an original request anchor is never promoted from a summarized objective into current task authority.
- Any Workspace Cache restore verified outer/component integrity, exact HEAD commit/tree, and staged/unstaged/non-ignored-untracked state fingerprint before binding the fresh workspace. A successful restore remained successful even if Drive cleanup failed; consumed caches were excluded from automatic restore selection, and consumed or >=3-day cache cleanup was bounded to exact owned objects in the private cache folder.
- Any packaged Codex Loop Skill carries a verified build-generated deployment manifest bound to the runtime file set. Consumer packages use `repository_binding=none` and contain no repository identity; explicit maintainer packages may additionally carry exact published repository commit/tree provenance marked `provenance_only`. Package SHA remains external receipt evidence.
- Source push, Skill packaging, current-conversation artifact exposure, and ChatGPT installation were reported as separate boundaries; a Git push or `skill.zip` build was not described as a downloadable package or installed-Skill update without the corresponding current host/product evidence.
- Every repository `push`/`publish` intent was intercepted before literal transport execution and resolved through the bundled Codex Loop controller. Web used the verified exact-identity Web path; Local used native Git from the bound worktree plus exact remote commit/tree readback. Ordinary target repositories were never required to contain `publish-enter` or another Codex Loop runtime file. The returned `mode_protocol_reference` described only the selected mode. In Web mode fresh validation/capability evidence was reused, FAST_PUBLISH remained the default, and GitHub not already containing the audited source commit object was not treated as a blocker because the verified bundle introduces it. A delivery-only push did not create a semantic steer, trigger production packaging, or repeat broad validation solely because commit metadata changed.
- When Codex Loop itself was updated, the task produced a validated repository-neutral official `skill.zip` after source validation/review and after any explicitly requested publication, copied it byte-for-byte to `codex-loop.zip`, verified identical SHA-256 values, and exposed that exact file through a fresh current-conversation host artifact reference. No presumed/stale Library reference was used. Completion did not depend on installation, and the user-facing install path was `Plugins -> Plugin Directory -> Skills -> Create -> Upload from your computer`.
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
