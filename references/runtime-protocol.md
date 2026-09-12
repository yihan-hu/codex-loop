# Runtime Protocol

Use `python3 scripts/codex_loop.py ...`. Runtime task state is private and outside the repository.

## Lifecycle admission and orientation

Every selected invocation creates one lifecycle immediately, before workspace acquisition or optional persistence:

```bash
python3 scripts/codex_loop.py bootstrap \
  --request-anchor 'exact current user request'
```

Keep the returned `task_id` for the objective and pass it explicitly to every later lifecycle-stateful command; do not use the workspace active-task pointer to infer model task identity. For repository/filesystem work, bind and orient that same lifecycle before the first mutation:

```bash
python3 scripts/codex_loop.py orient --task-id TASK --cwd REPO
```

The result returns applicable root-to-cwd repository instructions plus the current Git dirty/protected-path snapshot. If `instructions.complete=false` or `safe_to_mutate=false`, do not mutate until the applicable authority/context is complete.

Load a more-specific repository instruction scope before first touching files there:

```bash
python3 scripts/codex_loop.py instructions --task-id TASK --cwd PATH
```

A later `continue` / `resume` / `继续` restores this same lifecycle with `next --task-id TASK`; it does not create a replacement lifecycle.

## Thin plan

```bash
python3 scripts/codex_loop.py plan --task-id TASK --plan-json '[
  {"step":"Inspect implementation","status":"completed"},
  {"step":"Make minimal change","status":"in_progress"},
  {"step":"Run relevant tests","status":"pending"}
]'
```

Allowed statuses are exactly `pending`, `in_progress`, and `completed`; at most one item may be `in_progress`.

## Working/resume view

```bash
python3 scripts/codex_loop.py next --task-id TASK
python3 scripts/codex_loop.py snapshot --task-id TASK --cwd REPO
```

`next` is the normal lightweight resume capsule: request anchor/steers, acceptance text, plan, changed paths, validation state, deterministic completion reasons, and suggested next action. Use `snapshot` only for deeper debugging/audit context.

## User steer

```bash
python3 scripts/codex_loop.py steer --task-id TASK --text 'later user correction'
```

The steer is authoritative immediately. There is no separate steer-ack command.

## Validation

Recorded validation is optional for ordinary lifecycle completion. Create the lifecycle with `--require-validation` only when a current pass must be a deterministic finish condition; publication has its own current-validation requirement.

```bash
python3 scripts/codex_loop.py validate --task-id TASK --cwd REPO -- pytest tests/test_target.py
```

If the runtime reports `requires_host_visible_execution`, run that exact command through the host from the returned cwd, then record the observation directly:

```bash
python3 scripts/codex_loop.py validation-record --task-id TASK --cwd REPO \
  --command-json '["pytest","tests/test_target.py"]' \
  --exit-code 0 --evidence 'targeted test passed'
```

No validation plan-id or generation handshake is required. Rich workload/process/cleanup fields remain available when the host exposes them.

## Completion

```bash
python3 scripts/codex_loop.py completion --task-id TASK --cwd REPO
```

The result is a deterministic guard only:

- `PASS`: no modeled machine blocker remains; perform one model semantic final acceptance review and finish if the user's objective is satisfied.
- `CONTINUE`: current machine state still has work such as unfinished plan, missing required validation, unresolved external action, or managed process cleanup.
- `BLOCKED`: a hard state/safety invariant is violated, such as workspace binding mismatch or protected/read-only mutation.

There is no `objective-audit`, `criterion --status pass`, `steer-ack`, or mandatory `focus` command in the normal protocol.

## Checkpoint

```bash
python3 scripts/codex_loop.py checkpoint --task-id TASK --cwd REPO --key-finding '...' --next-action '...'
python3 scripts/codex_loop.py checkpoint-restore --task-id TASK --cwd REPO
```

Use checkpoints only before long/noisy transitions or when re-entry matters.

## Persistence

Cross-conversation persistence is opt-in:

```bash
python3 scripts/codex_loop.py persistence-export --task-id TASK --cwd REPO --backend google_drive
python3 scripts/codex_loop.py persistence-resume-plan --manifest STATE.json
python3 scripts/codex_loop.py persistence-resume --cwd REPO --manifest STATE.json --observations-json OBS.json
```

The v4 manifest stores the request, three-state plan, acceptance text, steers, minimal workspace identity, and unresolved consequential external-action identities. Prior validation is historical after resume; current repository/external reality wins.

## Side-effect routing

Routing and publication commands are deliberately separate from the normal agent loop. Use the dedicated references for exact commands:

- `interaction-routing.md`
- `repository-continuity.md`
- `source-acquisition.md`
- `publication-router.md`
- `web-mode-publish.md`
- `release-lineage.md`
- `workspace-registry.md`
- `web-to-local-handoff.md`

These controls guard real side effects. Do not route ordinary reasoning/edit/test steps through them unless the host action itself requires it.

## Managed processes / delegation

Use service/process and isolation commands only when the task actually needs an interactive managed process or delegated reviewer. They are not part of the default happy path. See `execution-supervision.md` and `delegation.md`.
