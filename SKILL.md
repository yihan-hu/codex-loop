---
name: codex-loop
description: "Lightweight durable objective layer for ChatGPT. Use for repository/filesystem work, Git/source publication, Skill update/deploy, Web/Local routing, cross-tool objectives, or genuinely long multi-step work that may need resume. Once selected, lifecycle admission is mandatory: for a new objective, bootstrap before any substantive task action; for an admitted continuation, reuse the exact task_id; never continue outside the Codex Loop lifecycle. Keep that lifecycle Codex-like and lightweight, with native agent execution, minimal validation, and one final semantic acceptance review. Escalate planning, persistence, managed processes, or external-action bookkeeping only when risk or task shape requires it. Never launch Codex CLI or another model runtime."
---

# Codex Loop

## Mandatory lifecycle admission

Once Codex Loop is selected, entering its lifecycle is mandatory, not an optional setup step. Reading this Skill entrypoint and any instructions needed to execute it is not task execution. After selection and entrypoint loading, the first task action for a new objective must be `bootstrap`; do not inspect the target workspace, browse for task evidence, make a task plan, call task tools, mutate files, or give a substantive task answer before `bootstrap` returns a `task_id`.

If the host cannot execute the Codex Loop runtime entrypoint, fail closed: state that the lifecycle could not be entered and do not silently continue the objective as ordinary chat/tool execution. If the same objective already has an admitted lifecycle in the current conversation, admission is already satisfied; do not bootstrap again, and use that exact `task_id` for continuation.

Treat Codex Loop as a thin lifecycle, durability, and routing layer around the host model, not as a workflow engine. Let the host model reason, inspect, edit, test, and repair naturally only after lifecycle admission. Codex Loop should mainly preserve the user-authorized objective across turns, prevent unsafe routing, avoid duplicate high-impact external actions, and reconcile task-owned process state.

Do not run a second direct-vs-durable admission decision and do not defer lifecycle creation until a repository or durable feature is needed. The lifecycle itself stays lightweight; planning, workspace binding, checkpoints, persistence, managed processes, and separate review remain lazy capabilities inside it.

Use `scripts/codex_loop.py` from this Skill as the stable runtime entry point. Runtime state belongs in the private system temp directory, never in the target repository.

## Lifecycle admission

Every newly admitted objective begins by creating the lifecycle and retaining the exact current user request:

```bash
python3 scripts/codex_loop.py bootstrap \
  --request-anchor 'EXACT CURRENT USER REQUEST'
```

Keep the returned `task_id` as the lifecycle identity for the rest of the objective. Pass it explicitly to every later command that reads or mutates lifecycle state; do not let a workspace-local active-task pointer choose the lifecycle for model execution. Lifecycle creation is workspace-independent; repository/filesystem tasks bind a workspace afterward with `orient`. Creating the lifecycle must not depend on repository acquisition, a plan, a checkpoint, or cross-chat persistence.

Do not create a second lifecycle for an ordinary follow-up to the same objective. Never re-bootstrap merely because the user says `continue`, `resume`, or `继续`.

## Always-on execution authority

Keep lifecycle authority separate from optional capabilities. Preserve the initial user request and later user corrections as the scope authority; do not replace them with a broader model-written objective.

For repository or filesystem work, bind/orient the existing lifecycle before the first mutation:

```bash
python3 scripts/codex_loop.py orient --task-id TASK --cwd REPO
```

Use the returned repository instructions and pre-existing work as active constraints. Treat returned `protected_paths` as user-owned work: do not revert, overwrite, or normalize them unless the requested change requires touching that path, and then preserve unrelated hunks. If `safe_to_mutate` is false, obtain a trustworthy host-visible workspace/Git observation before mutating.

Repository instructions are scoped. Before first touching a file under a deeper directory whose instruction scope has not been loaded, read that scope inside the same lifecycle:

```bash
python3 scripts/codex_loop.py instructions --task-id TASK --cwd PATH
```

If repository-instruction discovery reports `complete=false`, do not mutate yet. Reload with a sufficient `--max-bytes` value until the applicable instruction set is complete. For non-repository work, keep the same request-authority rule and use the relevant host/domain context instead.

## Default execution model

Use this happy path unless the task itself requires more rigor:

`execute <-> inspect/test/repair -> optional one review -> final acceptance -> done`

Do not create checker A/B chains, repeated fresh-PASS ceremonies, criterion-by-criterion evidence gates, or a separate outer semantic audit by default. A strong model should choose its own execution trajectory and rerun only checks plausibly affected by a repair.

### Scope contract

The user owns **what** may change; the model owns **how** to accomplish that change. The effective user request plus later user corrections define task scope. A plan, working objective, architecture preference, discovered cleanup, failing unrelated test, reviewer suggestion, or model judgment may guide execution but never expand that scope.

In an existing system, make the smallest coherent change that satisfies the request. Do not redesign, refactor, rename, clean up, or otherwise improve adjacent behavior unless it is directly required to deliver the requested result. If a potentially useful change falls outside that boundary, leave it unchanged and mention it separately when relevant.

Before keeping any substantive change, be able to justify it directly from the effective user request or from a dependency that is necessary for that requested change to work. If that justification is missing, do not make or keep the change.

### Final acceptance

Before finishing, do one semantic review against the actual current state:

1. Re-read the user's effective request, including later corrections.
2. Inspect the final artifact/diff/state that matters.
3. Check that every substantive change is directly justified by the request or a necessary dependency; remove unrelated or merely beneficial changes.
4. Check the final change against the orientation snapshot and applicable repository instructions; preserve pre-existing user work and unrelated hunks.
5. Run the minimum relevant validation that has not already been run on the current state.
6. If a material requirement remains unsatisfied, continue working.
7. Otherwise finish and report the important evidence and any real limitation.

The runtime `completion` command checks deterministic blockers only. It does not certify semantic correctness.

## Continuation and steering

Treat `continue`, `resume`, `继续`, and equivalent follow-ups as continuation of the active lifecycle, not as a new objective. Before acting, recover the current lifecycle state:

```bash
python3 scripts/codex_loop.py next --task-id TASK
```

Use its request, plan, completion blockers, current workspace observations, and next action as the starting point. If it reports `authority_reload_required=true`, reload the complete user authority before continuing:

```bash
python3 scripts/codex_loop.py authority --task-id TASK
```

Then re-observe current repository/tool reality and continue from the smallest unfinished useful action. Do not repeat completed work merely because the user said `continue`.

For every later task-relevant user message that changes or constrains the objective, record that exact correction before acting. Do not decide that a scope-changing user instruction is too small to retain:

```bash
python3 scripts/codex_loop.py steer --task-id TASK --text 'exact new user instruction'
```

A pure continuation request adds no new scope and does not need a steer record.

## Thin lifecycle state

Lifecycle state always exists once the Skill is selected. Keep it minimal: request anchor, ordered steers, lifecycle status, and only the machine state that the task actually uses. A model-written objective and acceptance text are working aids, not a second specification.

### Codex-style plan

For genuinely multi-step work, keep only a short plan with Codex's three statuses:

- `pending`
- `in_progress`
- `completed`

At most one step may be `in_progress`. Update several statuses in one call rather than recording lifecycle transitions after every action.

```bash
python3 scripts/codex_loop.py plan --task-id TASK --plan-json '[
  {"step":"Inspect current implementation","status":"completed"},
  {"step":"Implement minimal fix","status":"in_progress"},
  {"step":"Run relevant tests","status":"pending"}
]'
```

Use `next` as the lightweight continuation/resume capsule. It exposes the request, plan, acceptance text, changed paths, validation state, deterministic finish blockers, and the smallest useful next action.

```bash
python3 scripts/codex_loop.py next --task-id TASK
```

On resume, inspect current repository/tool state before acting. Do not redo a completed step unless current evidence shows it is stale.

Steers are immediately authoritative. Do not require a separate steer acknowledgement or re-ack them after every workspace mutation.

## Validation

Run tests/build/lint/typecheck through the normal host-visible execution path when they are relevant. Start with the smallest check that exercises the changed behavior; broaden only when useful.

Lifecycle `completion` does not require a recorded validation by default. Add `--require-validation` at lifecycle creation only when a current passing check must be a deterministic finish condition (publication paths impose their own validation requirement).

`validate` may return a host-visible execution request. After the host runs the command, record the observed result directly; there is no plan-id handshake.

```bash
python3 scripts/codex_loop.py validate --task-id TASK --cwd REPO -- pytest tests/test_target.py
python3 scripts/codex_loop.py validation-record --task-id TASK --cwd REPO \
  --command-json '["pytest","tests/test_target.py"]' \
  --exit-code 0 --evidence 'targeted test passed'
```

A repair invalidates confidence only where it can matter. Rerun affected validation; do not mechanically rerun every prior checker. Existing repository tests are the default regression mechanism.

## Review policy

Use no separate review for trivial or well-covered changes when direct inspection plus tests is sufficient.

Use one Codex-style review for large, unfamiliar, weakly tested, cross-module, or materially risky changes. Read `references/codex-review.md`, review the actual diff/change against the base/commit/current changes, and return only discrete actionable findings that the author would really fix. Ignore nits and speculative breakage. If there are no substantive findings, stop; do not create a second reviewer just to obtain another PASS.

After a real finding is repaired, rerun only affected tests/checks. Escalate to independent review or broader regression only when the repair/risk justifies it.

## Deterministic completion blockers

Before finishing any Codex Loop objective, run `completion --task-id TASK` after the semantic final acceptance review. `completion` may block/continue for concrete machine-observable conditions such as:

- unfinished plan steps when a plan exists;
- missing current validation when validation was explicitly required for the lifecycle;
- unresolved task-owned processes;
- unresolved consequential external actions;
- protected pre-existing user work modified unexpectedly;
- read-only task profiles that observed mutation;
- canonical workspace binding mismatch.

Do not use `completion` to repeat the model's semantic acceptance review.

## Checkpoints and persistence

Use ordinary host conversation continuity first. Use `checkpoint` only before a genuinely long/noisy transition or when durable re-entry matters. Keep checkpoints small: request, plan, key findings, next action, and current machine-observable state.

Cross-conversation persistence remains opt-in. Read `references/persistence.md` and `references/persistence-resume.md` only when the user explicitly needs the objective/workspace to survive conversation loss.

## Repository and host routing

Routing is one of the few places where deterministic governance is worth keeping because it controls real side effects.

Before repository/filesystem mutation, Git publication, local computer use, Skill deployment, or Web/Local transfer, resolve the intended host path. In ChatGPT Web, Web is the default workspace until the user explicitly selects Local. Local selection does not itself grant source mutation or computer use.

For detailed routes, load only the relevant reference:

- repository reuse/acquisition: `references/repository-continuity.md`, then `references/source-acquisition.md` only if cold acquisition is required;
- Web/Local routing: `references/interaction-routing.md`;
- publication: `references/publication-router.md`, then the selected `references/web-mode-publish.md` or `references/release-lineage.md`;
- Web -> local transfer: `references/web-to-local-handoff.md`;
- workspace grants: `references/workspace-registry.md`;
- local execution/computer boundary: `references/remote-desktop-boundary.md`;
- Skill packaging/deployment: `references/skill-deployment.md` and `references/deployment-provenance.md`.

Keep routing checks at the action boundary. Do not force unrelated reasoning/edit/test steps through routing state.

## External actions and safety

For consequential non-idempotent external actions, keep `planned -> dispatched -> terminal_success|terminal_failure|outcome_unknown` reconciliation. Never blindly retry `outcome_unknown`; inspect external reality first.

Sandboxing, approvals, connector authentication, and actual tool dispatch remain host-owned. Put governance effort at these side-effect boundaries rather than constraining model reasoning.

For interactive/task-owned processes, use bounded timeouts, keep processes observable/terminable, and clean them up before completion. Read `references/execution-supervision.md` only when process lifecycle is relevant.

## Optional capabilities

Base use has zero external setup. A consumer package has no repository binding. GitHub, Google Drive, Remote Desktop Commander, local workspaces, and browser/GUI adapters are optional; read `references/consumer-onboarding.md` only when one of those integrations is actually needed.

Delegation, persistence, managed process sessions, publication adapters, workspace cache, model relay, and GUI/browser routing are optional. Activate them only for tasks that actually need them; their existence must not add steps to the normal happy path.

## Skill maintenance and packaging

When maintaining Codex Loop itself, update `ARCHITECTURE.md` with any architecture change. Prefer upstream Codex semantics over local governance abstractions. `references/source-map.yaml` records upstream-derived/local surfaces; run source-fidelity checks only when mapped upstream resources or mappings actually change.

For maintenance, run `python3 scripts/smoke_test.py` after changing the lightweight task/resume path. For a distributable update, package the complete Skill with the official Skill Creator packager. For Codex Loop delivery, the validated `skill.zip` may be copied byte-for-byte to `codex-loop.zip`; packaging, download exposure, publication, and installation are separate actions.
