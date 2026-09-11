# Runtime Protocol

Use `python3 scripts/codex_loop.py ...`. Runtime task state is private and outside the repository.

## Durable task bootstrap

Use only when durable state is useful:

```bash
python3 scripts/codex_loop.py bootstrap --cwd REPO \
  --request-anchor 'exact user request' \
  --objective 'concise working objective' \
  --criterion 'optional acceptance condition'
```

`--criterion` is acceptance text for the model; it is not a status/evidence gate. Recorded validation is optional unless `--require-validation` is explicitly set or a consequential path such as publication requires it.

## Thin plan

```bash
python3 scripts/codex_loop.py plan --cwd REPO --plan-json '[
  {"step":"Inspect implementation","status":"completed"},
  {"step":"Make minimal change","status":"in_progress"},
  {"step":"Run relevant tests","status":"pending"}
]'
```

Allowed statuses are exactly `pending`, `in_progress`, and `completed`; at most one item may be `in_progress`.

## Working/resume view

```bash
python3 scripts/codex_loop.py next --cwd REPO
python3 scripts/codex_loop.py snapshot --cwd REPO
```

`next` is the normal lightweight resume capsule: request anchor/steers, acceptance text, plan, changed paths, validation state, deterministic completion reasons, and suggested next action. Use `snapshot` only for deeper debugging/audit context.

## User steer

```bash
python3 scripts/codex_loop.py steer --cwd REPO --text 'later user correction'
```

The steer is authoritative immediately. There is no separate steer-ack command.

## Validation

Recorded validation is optional for ordinary durable completion. Bootstrap with `--require-validation` only when a current pass must be a deterministic finish condition; publication has its own current-validation requirement.

```bash
python3 scripts/codex_loop.py validate --cwd REPO -- pytest tests/test_target.py
```

If the runtime reports `requires_host_visible_execution`, run that exact command through the host from the returned cwd, then record the observation directly:

```bash
python3 scripts/codex_loop.py validation-record --cwd REPO \
  --command-json '["pytest","tests/test_target.py"]' \
  --exit-code 0 --evidence 'targeted test passed'
```

No validation plan-id or generation handshake is required. Rich workload/process/cleanup fields remain available when the host exposes them.

## Completion

```bash
python3 scripts/codex_loop.py completion --cwd REPO
```

The result is a deterministic guard only:

- `PASS`: no modeled machine blocker remains; perform one model semantic final acceptance review and finish if the user's objective is satisfied.
- `CONTINUE`: current machine state still has work such as unfinished durable plan, missing required validation, unresolved external action, or managed process cleanup.
- `BLOCKED`: a hard state/safety invariant is violated, such as workspace binding mismatch or protected/read-only mutation.

There is no `objective-audit`, `criterion --status pass`, `steer-ack`, or mandatory `focus` command in the normal protocol.

## Checkpoint

```bash
python3 scripts/codex_loop.py checkpoint --cwd REPO --key-finding '...' --next-action '...'
python3 scripts/codex_loop.py checkpoint-restore --cwd REPO
```

Use checkpoints only before long/noisy transitions or when re-entry matters.

## Persistence

Cross-conversation persistence is opt-in:

```bash
python3 scripts/codex_loop.py persistence-export --cwd REPO --backend google_drive
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
