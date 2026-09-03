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
- Under target-pursuit, an unmodeled surprise that blocked the intended direct external-action path was resolved by repairing the responsible design/control-plane contract with regression evidence before retry; no ad hoc fallback or alternate transport was used merely to get past the surprise.
- No managed/task-owned process that should be stopped remains running, orphaned, or internally failed without host-observed resolution. A teardown stall may be a warning for a functional objective only after authoritative workload PASS and successful cleanup; it prevents completion when clean exit is part of the objective.
- Any validation waiver has a recorded reason, any protected-work override has a per-mutation reason, and any expected Git mutation is explicitly scoped to HEAD/branch/index.
- For tasks using canonical release/publish flow, the workspace binding still matches the bound Git repository; the artifact receipt names the audited commit/tree; and any publish action is terminally reconciled from remote readback.
- No installed Skill was edited in place, auto-selected as fallback source, or treated as competing authority. If the installed-Skill source exception was used, current-turn explicit user authorization was recorded; the installed directory remained read-only; current/latest claims required exact remote equality; explicitly accepted historical/unknown provenance was labeled honestly; and only the fresh copied workspace became mutable authority.
- Any GitHub -> Web acquisition used the exact-revision `workspace-download.yml` Git bundle Actions artifact path, verified artifact digest + bundle SHA-256/size, ran `git bundle verify`, restored a real Git workspace, and required exact target commit/tree before binding it; shell `git clone`, per-file reconstruction, source-only archives, and generic URLs were not substituted as ordinary Web acquisition transports.
- A resumed task uses a new freshness domain: persisted criterion PASS/validation/review/objective-audit evidence remains stale/historical, source divergence is explicit, and dispatched/outcome-unknown non-idempotent actions are reconciled before retry.
- Any Workspace Cache restore verified outer/component integrity, exact HEAD commit/tree, and staged/unstaged/non-ignored-untracked state fingerprint before binding the fresh workspace. A successful restore remained successful even if Drive cleanup failed; consumed caches were excluded from automatic restore selection, and consumed or >=7-day cache cleanup was bounded to exact owned objects in the private cache folder.
- Any packaged Codex Loop Skill carries a verified build-generated deployment manifest bound to the runtime file set. Consumer packages use `repository_binding=none` and contain no repository identity; explicit maintainer packages may additionally carry exact published repository commit/tree provenance marked `provenance_only`. Package SHA remains external receipt evidence.
- Source push, Skill packaging, and ChatGPT deployment were reported as separate states; a Git push or `skill.zip` build was not described as an installed-Skill update without observed deployment evidence.
- A Web-mode `push`/`publish` continuation used `web-publish-continuation-begin` and the default `web-publish-plan` before new validation/preflight/transport work. Fresh validation/review/capability evidence was reused; `FAST_PUBLISH_REFRESH_REQUIRED` refreshed only named stale gates; `.github/workflows/workspace-import-fast.yml` was the default importer; `.github/workflows/workspace-import.yml`/`FULL_VERIFIED_PUBLISH` was used only after explicit user-selected `--standard-web`. A delivery-only push did not create a semantic steer, trigger production packaging, or repeat broad validation solely because commit metadata changed.
- For a Web-mode push of the active workspace Skill, post-push deployment reconciliation ran for the exact published revision. `skill-deploy-handoff` is only planning evidence: UI/surface evidence must come from the platform `skill-creator`/host and be recorded separately; `UI_SURFACED` is not `DEPLOYED`. For Codex Loop self-update, the handoff must record `install_strategy=verified_library_bridge`, `native_self_update_attempt_allowed=false`, `BRIDGE_REQUIRED`, and `INSTALL_READY`; a standard same-name/native production update must not be attempted first. Before the install-only turn, a fresh `b5a748`-template bridge was generated, regression-checked, Skill-Creator-validated, and officially packaged while the production `skill.zip` remained unchanged. The later install-only turn calls `skill-deploy-install-begin`, whose final action is saving that prepared fresh bridge through the Library surface; no later Codex Loop command follows Library-surface initiation, and reconciliation begins only after `skill-deploy-resume` records a genuinely later host turn. If the intended production Skill revision is not observably active, the `chatgpt_skill_update` action remains unresolved and normal completion must not pass merely because GitHub publication, bridge saving, packaging, or an internal handoff succeeded.
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
