---
name: codex-loop
description: "Lightweight durable objective layer for ChatGPT. Use for repository/filesystem work, Git/source publication, Skill update/deploy, Web/Local routing, cross-tool objectives, or genuinely long multi-step work that may need resume. Once selected, lifecycle admission is mandatory: for a new objective, bootstrap before any substantive task action; for an admitted continuation, reuse the exact task_id; never continue outside the Codex Loop lifecycle. Keep that lifecycle Codex-like and lightweight, with native agent execution, minimal validation, and one final semantic acceptance review. Escalate planning, persistence, managed processes, or external-action bookkeeping only when risk or task shape requires it. Never launch Codex CLI or another model runtime."
---

# Codex Loop

## Mandatory lifecycle admission

Once Codex Loop is selected, entering its lifecycle is mandatory, not an optional setup step. Reading this Skill entrypoint and any instructions needed to execute it is not task execution. After selection and entrypoint loading, the first task action for a new objective must be `bootstrap`; do not inspect the target workspace, browse for task evidence, make a task plan, call task tools, mutate files, or give a substantive task answer before `bootstrap` returns a `task_id`. Choose the lifecycle execution surface from the user's explicit development location before that bootstrap: ordinary/Web objectives bootstrap with the installed ChatGPT Skill runtime; an explicitly Local objective bootstraps through RDC on the local host so its lifecycle state is created there from the start. This location choice is routing, not task inspection.

If the host cannot execute the Codex Loop runtime entrypoint, fail closed: state that the lifecycle could not be entered and do not silently continue the objective as ordinary chat/tool execution. If the same objective already has an admitted lifecycle in the current conversation, admission is already satisfied; do not bootstrap again. Use the exact `task_id` when it is still available. If a continuation arrives after the host/model lost that identity, recover it through `resume --cwd WORKSPACE` when the canonical workspace is known, otherwise `resume --last`; a continuation must enter runtime-owned resume resolution before any new bootstrap.

Treat Codex Loop as a thin lifecycle, durability, and routing layer around the host model, not as a workflow engine. Let the host model reason, inspect, edit, test, and repair naturally only after lifecycle admission. Codex Loop should mainly preserve the user-authorized objective across turns, prevent unsafe routing, avoid duplicate high-impact external actions, and reconcile task-owned process state.

Do not run a second direct-vs-durable admission decision and do not defer lifecycle creation until a repository or durable feature is needed. The lifecycle itself stays lightweight; planning, workspace binding, checkpoints, persistence, managed processes, and separate review remain lazy capabilities inside it.

Use `scripts/codex_loop.py` from this Skill as the stable runtime entry point on the surface that owns the lifecycle. Web/host mode uses the installed ChatGPT Skill copy. Local mode uses a Codex Loop runtime cached on the local host under `~/.codex-loop/runtime-src` and executes it through RDC; it must not use an arbitrary project checkout of Codex Loop. Lifecycle state and workspace-to-task pointers belong to that same host's `CODEX_LOOP_HOME/runtime` (default `~/.codex-loop/runtime`), never in the target repository. Conversation-scoped routing sessions remain temporary.

## Lifecycle admission

Every newly admitted objective begins by creating the lifecycle and retaining the exact current user request:

```bash
python3 scripts/codex_loop.py bootstrap \
  --request-anchor 'EXACT CURRENT USER REQUEST'
```

Keep the returned `task_id` as the lifecycle identity for the rest of the objective. Pass it explicitly to every later command that reads or mutates lifecycle state; do not let a workspace-local task pointer choose the lifecycle for model execution. Lifecycle creation is workspace-independent; repository/filesystem tasks bind a workspace afterward with `orient`. Creating the lifecycle must not depend on repository acquisition, a plan, a checkpoint, or cross-chat persistence.

For an explicitly Local objective, perform that same bootstrap through RDC on the local host. Use the dedicated local runtime cache `~/.codex-loop/runtime-src`; if it is absent, provision it from the public canonical Codex Loop repository, and if it is present require it to be a clean runtime-owned checkout before fast-forwarding it. Then run `python3 ~/.codex-loop/runtime-src/scripts/codex_loop.py ...`. The resulting `~/.codex-loop/runtime` on the local host is authoritative for the lifecycle. A ChatGPT-host `/home/oai/.codex-loop` copy is not a fallback or mirror for that Local objective.

After Local admission, every lifecycle command for that objective (`orient`, `next`, `resume`, `steer`, `plan`, `pause`, `block`, `validate`, `completion`, and related state mutations) runs on the same local runtime through RDC. If the local runtime or its durable state is unavailable, fail closed instead of bootstrapping or resuming a second lifecycle on the ChatGPT host.

Do not create a second lifecycle for an ordinary follow-up to the same objective. Never re-bootstrap merely because the user says `continue`, `resume`, or `继续`. A successful `bootstrap` is immediately resumable from its durable task state, even before workspace orientation.

Lifecycle status is deliberately small and separate from plan state:

- `active`: work may proceed;
- `paused`: the user explicitly asked to pause; only an explicit continuation/resume reactivates it;
- `blocked`: a concrete blocker is currently confirmed, no remaining safe useful action can advance the objective, and progress requires user input or an external-state change;
- `complete`: terminal success after semantic acceptance plus the final machine completion check;
- `cancelled`: terminal user cancellation.

Never invent host-owned `usage_limited` or `budget_limited` states when the host does not expose authoritative budget data. Plan items remain only `pending | in_progress | completed`; do not duplicate lifecycle `blocked` inside the plan.

## Always-on execution authority

Keep lifecycle authority separate from optional capabilities. The exact initial user request plus later user corrections are the task authority. Do not create a model-written objective or acceptance specification for the same task.

Use this continuation contract after admission:

1. Keep the exact request plus later steers as the objective; never shrink it to what fits one turn.
2. Work from current repository, tool, process, and external state. Re-observe anything that may have gone stale; current reality outranks lifecycle summaries, plans, checkpoints, and historical validation.
3. Make concrete progress toward the requested end state. A status explanation or plan update without executed work/evidence is not progress.
4. If task-owned work is confirmed live, observe the existing handle instead of restarting it. An observation timeout or transient polling failure is not terminal evidence.
5. Repair resolvable failures and continue. Use `blocked` only for a genuine impasse with no remaining safe useful work; do not use it merely because work is difficult, slow, uncertain, or incomplete.
6. Treat completion as unproven until the actual request is verified requirement by requirement against current authoritative evidence.

For repository or filesystem work, bind/orient the existing lifecycle once before the first mutation:

```bash
python3 scripts/codex_loop.py orient --task-id TASK --cwd REPO
```

`orient` is deliberately cheap: establish repository identity, current branch/HEAD/status, applicable root-to-cwd instructions, and pre-existing dirty paths. Do not turn ordinary orientation into a full repository content snapshot or durable freshness proof. Treat returned `protected_paths` as user-owned work and preserve unrelated hunks. Deeper repository instructions are loaded only before first touching a new deeper scope:

```bash
python3 scripts/codex_loop.py instructions --task-id TASK --cwd PATH
```

If instruction discovery is incomplete, reload that scope with a sufficient byte budget before mutation. Otherwise keep the loaded instruction authority stable; do not rediscover it as a heartbeat.

If an existing lifecycle has a stale or legacy workspace binding that lacks enough Git identity to verify a move, do not rewrite lifecycle state manually or bootstrap a replacement task. First verify the recovered canonical Git workspace with `source-acquisition-verify --task-id TASK` against authoritative repository + commit/tree evidence; a `PASS` records only that verified rebind evidence. Then run `orient --task-id TASK --cwd REPO --rebind-verified`. `orient` consumes the stronger verified recovery evidence, preserves the same lifecycle, and clears it after a successful rebind.

## Default execution model

After mandatory admission and any required one-time orientation, use the host-native Codex-like loop:

`inspect -> act -> observe/test -> repair -> optional one review -> final semantic acceptance -> completion`

Ordinary shell/file/edit/test operations go directly through host tools. Do not wrap them in lifecycle commands, record every step, or call `next` between actions. The lifecycle stays active without being polled. A strong model should choose its own execution trajectory and rerun only checks plausibly affected by a repair.

If another selected Skill requires its own domain workflow or state machine, that workflow remains authoritative inside that Skill's scope. Codex Loop wraps it with the durable lifecycle but must not flatten, replace, reinterpret, or bypass its required states/transitions. The domain Skill owns its workflow semantics and persistence; Codex Loop owns task identity, retained user authority, routing/side-effect safety, and final lifecycle completion.

When a coupled domain Skill requires a semantic stage whose execution itself is completion-relevant, route that stage through Codex Loop semantic work instead of accepting a caller-authored result artifact:

`semantic-work-enter -> logical_isolation -> semantic-work-finish -> semantic-result`

`semantic-work-enter` binds the owning consumer/stage plus exact input and governing-instruction SHA-256 values, captures the current effective user-request hash, and always uses `logical_isolation`. `semantic-work-finish` is the only operation that may mint a `semantic_result_id` for that stage. Generic `isolate-finish`, helper scripts, copied PASS payloads, hashes, receipts, or a domain runtime's own assertion that review happened cannot satisfy this authority boundary. `semantic-result` requires the exact binding and current generation; workspace mutation or a user steer during logical isolation blocks semantic completion, and later mutation or steer makes the result stale. The owning domain Skill still defines the semantic instruction, output schema, repair rules, and state transition.

Do not use scripts, templates, loops, or deterministic code to manufacture the semantic judgment submitted to `semantic-work-finish`. Deterministic code may prepare inputs, persist the returned result, and validate identity/schema after the logical-isolation judgment exists. This contract makes semantic execution provenance completion-relevant; it does not claim physical model independence or that a model judgment is necessarily correct.

### Scope contract

The user owns **what** may change; the model owns **how**. The effective request plus later steers define scope. Plans, reviews, architecture preferences, discovered cleanup, failing unrelated tests, or model judgment may guide execution but never expand it. In an existing system, make the smallest coherent change that satisfies the request and preserve unrelated user work.

### Final semantic acceptance

Before finishing:

1. Re-read the exact request plus later steers.
2. Derive the material requirements that must be true, including named artifacts, commands, invariants, gates, and deliverables.
3. For each material requirement, identify current authoritative evidence that would prove it, then inspect the actual artifact/diff/runtime/external state at the matching scope.
4. Treat missing, stale, indirect, or narrower-than-required evidence as not proven; gather stronger evidence or continue working.
5. Remove unrelated or merely beneficial changes, check applicable repository instructions, and preserve pre-existing user work.
6. Run the smallest relevant validation not already current for the changed behavior.
7. If any material requirement remains unsatisfied or unverified, continue working. If no safe useful action remains because of a concrete external/user dependency, use `block --reason ...`.
8. Otherwise run `completion` once. A `PASS` transitions the lifecycle to terminal `complete`; do not use `completion` as a mid-task probe.

Passing tests or a clear lifecycle status never substitutes for this semantic acceptance.

## Continuation and steering

A continuation never creates a new lifecycle. If the task is still known in the current model context, keep using the known `task_id`; no lifecycle heartbeat is required.

`next` is a cheap **state-only** capsule for the already-known lifecycle, including current lifecycle status, the optional plan and its task-board projection, and any known live-work handles. It does not change `paused`/`blocked` status, reconcile the repository, rediscover instructions, hash workspace content, or tell the model to finish:

```bash
python3 scripts/codex_loop.py next --task-id TASK
```

Use `resume` for real re-entry after context loss/reconnect/cross-turn recovery and for an explicit user request such as `continue`, `resume`, or `继续`. User wording stays natural; `resume` is the internal recovery mechanism:

```bash
python3 scripts/codex_loop.py resume --task-id TASK
python3 scripts/codex_loop.py resume --cwd REPO
python3 scripts/codex_loop.py resume --last
```

For `active`, `resume` continues the same lifecycle. For `paused`, it reactivates the same lifecycle. For `blocked`, it reactivates only as a fresh attempt to advance the objective and returns the prior blocker so the model must re-observe that condition; re-block if the same concrete dependency still prevents all useful work. `complete` and `cancelled` are terminal and must never be silently revived by `resume`.

For a Local lifecycle, all lifecycle commands continue through RDC on the same Mac runtime. Never resume or bootstrap a second host-side lifecycle. If the returned authority is truncated, fetch the complete request/steers with `authority` before acting. Re-observe only reality that may have gone stale; do not redo completed work because a plan or historical receipt exists.

When the user explicitly pauses or a genuine impasse is reached:

```bash
python3 scripts/codex_loop.py pause --task-id TASK
python3 scripts/codex_loop.py block --task-id TASK --reason 'concrete currently observed blocker'
```

Do not emulate upstream Goal's repeated-auto-turn blocker threshold: the ChatGPT Skill host cannot start autonomous continuation turns, so a local turn counter would be fake orchestration. `blocked` instead means the current evidence shows a genuine impasse and no safe useful work remains.

Every later task-relevant user correction is recorded exactly before acting:

```bash
python3 scripts/codex_loop.py steer --task-id TASK --text 'exact new user instruction'
```

A pure `continue`/`resume` adds no new authority and needs no steer record.

## Thin lifecycle state

The always-on state is intentionally small: exact request anchor, ordered steers, lifecycle identity/status, optional `blocked_reason`, optional three-state plan, and only machine state needed by capabilities the task actually uses. Ordinary model-facing continuation context contains request authority, the continuation contract, minimal workspace identity, current lifecycle status, active machine blockers/live work, and optional plan. Internal telemetry, hashes, validation history, changed-path inventories, release receipts, and other diagnostics stay runtime-side unless explicitly pulled for debugging or a capability needs them.

### Codex-style plan

A plan is optional durable working memory, not authority, not a collaboration mode, and not a completion gate. Create one when the next work is meaningfully multi-step, the user explicitly asks for planning, or cross-turn continuity benefits from a concise work map; skip it for trivial one-step work. It uses only `pending | in_progress | completed`, with at most one `in_progress` item. Update it when meaningful stages finish or the best execution trajectory materially changes, not after every tool call. Current reality always outranks a stale plan, and an unfinished plan never blocks completion when the actual request is already satisfied.

```bash
python3 scripts/codex_loop.py plan --task-id TASK --plan-json '[
  {"step":"Inspect current implementation","status":"completed"},
  {"step":"Implement minimal fix","status":"in_progress"},
  {"step":"Run relevant tests","status":"pending"}
]'
```

`next` derives a read-only task board from this same plan (`doing`, `pending`, `done`). The board has no separate storage or state machine. Do not add per-item blocked/retry/dependency semantics merely to make the board richer; if one item cannot proceed but other useful work exists, revise/reorder the plan and stay `active`; if the entire objective is genuinely stuck, use lifecycle `blocked`.

## Validation

Run tests/build/lint/typecheck directly through normal host tools. Start with the smallest check that demonstrates the changed behavior; broaden only when it adds useful confidence. After a repair, rerun only plausibly affected checks.

Lifecycle validation receipts are optional durability metadata. Use them only when the task explicitly requires a durable validation finish condition or a publication/release/persistence path needs one. Ordinary coding does not require a `validate -> execute -> validation-record` ceremony.

## Review policy

Trivial or well-covered changes need no separate reviewer. Large, unfamiliar, weakly tested, cross-module, or materially risky changes may receive one Codex-style review over the actual change. Report only discrete actionable findings the author would really fix; if none qualify, return no findings and stop. Repair real findings and rerun only affected checks.

## Deterministic completion blockers

After semantic acceptance, call `completion --task-id TASK` once. It checks machine-observable safety/side-effect conditions only and, on `PASS`, atomically transitions the lifecycle from `active` to terminal `complete`. Do not call it merely to ask whether work seems done; use current evidence, `next`, or diagnostic projections while still working. Machine blockers include:

- explicitly required durable validation is missing;
- consequential external actions remain unresolved;
- task-owned processes still require cleanup/reconciliation;
- protected pre-existing user work was unexpectedly modified when durable protection tracking is active;
- a read-only task profile observed mutation;
- the bound repository/workspace identity no longer matches.

An unfinished plan is not a blocker. `PASS` means only that the model already performed semantic acceptance and the final machine blockers are clear; the runtime itself still does not certify semantic correctness or generate a model-facing “finish now” instruction.

## Heavy reconciliation is lazy

Full repository content fingerprints, ignored-file watches, complete baselines, generation-based validation freshness, release lineage, and cross-chat persistence remain available for tasks that genuinely need durable reconstruction or high-risk publication. They are not part of the ordinary active coding loop. Safety-critical non-idempotent external actions keep deterministic reconciliation at their action boundary.

## Checkpoints and persistence

Use ordinary host conversation continuity first. Checkpoint only before a genuinely long/noisy transition or when durable re-entry matters. Cross-conversation persistence is opt-in; its canonical authority is still request anchor + steers, not a model-written objective/acceptance restatement. Persistence restores the same lifecycle status, including a concrete blocked reason, plus the plan; it never turns historical validation into current proof. A later explicit user `continue` still passes through normal `resume` semantics.

## Repository and host routing

Routing is one of the few deterministic boundaries worth keeping because it controls real side effects. Before repository mutation, Git publication, local computer use, Skill deployment, or Web/Local transfer, resolve the intended host path. Load only the route-specific reference needed for the action; do not force ordinary reasoning/edit/test steps through routing state.

Detailed references:

- Drive temporary/archive placement and cleanup semantics: `references/drive-storage.md`;
- repository reuse/acquisition: `references/repository-continuity.md`, then `references/source-acquisition.md` only for cold acquisition;
- Web/Local routing: `references/interaction-routing.md`;
- publication: `references/publication-router.md`, then the selected publication reference;
- Web -> Local transfer: `references/web-to-local-handoff.md`;
- workspace grants: `references/workspace-registry.md`;
- local execution boundary: `references/remote-desktop-boundary.md`;
- Skill deployment: `references/skill-deployment.md` and `references/deployment-provenance.md`.

## External actions and safety

For consequential non-idempotent external actions, keep `planned -> dispatched -> terminal_success|terminal_failure|outcome_unknown` reconciliation. Never blindly retry `outcome_unknown`; inspect external reality first. When the action itself or its owning adapter returns authoritative terminal evidence for the requested external state, accept that evidence once; do not add a second host readback merely to prove the same fact again. Re-observe only for asynchronous acknowledgement, ambiguity, concurrency, reconciliation, or when current external state is itself the requested result. Sandboxing, approvals, connector authentication, and actual tool dispatch remain host-owned. Interactive task-owned processes remain observable/terminable and are cleaned up before completion.

## Optional capabilities

Base use has zero external setup. A consumer package has no repository binding. GitHub, Google Drive, Remote Desktop Commander, local workspaces, and browser/GUI adapters are optional; read `references/consumer-onboarding.md` only when one of those integrations is actually needed.

Delegation, persistence, managed process sessions, publication adapters, workspace cache, model relay, and GUI/browser routing are optional. Activate them only for tasks that actually need them; their existence must not add steps to the normal happy path.

## Skill maintenance and packaging

When maintaining Codex Loop itself, update `ARCHITECTURE.md` with any architecture change. Prefer upstream Codex semantics over local governance abstractions. `references/source-map.yaml` records upstream-derived/local surfaces; run source-fidelity checks only when mapped upstream resources or mappings actually change.

For maintenance, run `python3 scripts/smoke_test.py` after changing the lightweight task/resume path. For a distributable update, package the complete Skill with the official Skill Creator packager. For Codex Loop delivery, the validated `skill.zip` may be copied byte-for-byte to `codex-loop.zip`; packaging, download exposure, publication, and installation are separate actions.
