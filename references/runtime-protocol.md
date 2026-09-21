# Runtime Protocol

Use `python3 scripts/codex_loop.py ...`. Runtime task state is private and outside the target repository.

Lifecycle admission is fail-closed. After Codex Loop selection and entrypoint loading, a new task must run `bootstrap` before any substantive task action. A continuation reuses the exact existing lifecycle.

## Admission and cheap orientation

```bash
python3 scripts/codex_loop.py bootstrap \
  --request-anchor 'exact current user request'
```

The request anchor is the task specification. Later corrections are stored as ordered steers; no parallel task objective or acceptance list is created.

For repository/filesystem work, orient once before first mutation:

```bash
python3 scripts/codex_loop.py orient --task-id TASK --cwd REPO
```

Ordinary orientation reads repository identity/status, applicable root-to-cwd instructions, and pre-existing dirty paths. It deliberately avoids a complete repository content baseline. Load a deeper instruction scope only before first touching it:

```bash
python3 scripts/codex_loop.py instructions --task-id TASK --cwd PATH
```

## Native active loop

After admission/orientation, ordinary work is direct host execution:

`inspect/edit/tool -> observe/test -> repair -> continue`

Do not call lifecycle commands between normal actions. Run ordinary tests directly through host tools.

## Optional plan

```bash
python3 scripts/codex_loop.py plan --task-id TASK --plan-json '[
  {"step":"Inspect implementation","status":"completed"},
  {"step":"Make minimal change","status":"in_progress"},
  {"step":"Run relevant tests","status":"pending"}
]'
```

Statuses are `pending | in_progress | completed`, with at most one `in_progress`. The plan is working memory only and never blocks completion by itself.

## `next` versus `resume`

```bash
python3 scripts/codex_loop.py next --task-id TASK
```

`next` is a cheap state-only capsule. It returns exact request/steers, the short execution contract, optional plan, stored workspace identity, and real machine blockers. It does **not** reconcile Git, hash workspace content, rediscover instructions, or emit a suggested finish action.

Use `resume` for real re-entry after model/context/task-identity loss:

```bash
python3 scripts/codex_loop.py resume --task-id TASK
python3 scripts/codex_loop.py resume --cwd REPO
python3 scripts/codex_loop.py resume --last
```

`resume` re-observes the bound workspace and applicable instructions before execution continues. Use `snapshot` only for explicit rich debugging/audit state.

## User steer

```bash
python3 scripts/codex_loop.py steer --task-id TASK --text 'later user correction'
```

The steer is authoritative immediately. A pure continuation needs no steer acknowledgement or heartbeat.

## Validation

Run ordinary validation directly through host tools. Lifecycle validation recording is only for workflows that explicitly require durable validation state:

```bash
python3 scripts/codex_loop.py validation-record --task-id TASK --cwd REPO \
  --command-json '["pytest","tests/test_target.py"]' \
  --exit-code 0 --evidence 'targeted test passed'
```

Create the lifecycle with `--require-validation` only when a current durable pass must be a deterministic finish condition or a publication/release path requires one.

## Completion

After the model has semantically accepted the actual result against the exact request:

```bash
python3 scripts/codex_loop.py completion --task-id TASK --cwd REPO
```

Completion checks machine-observable blockers only:

- `PASS`: machine blockers are clear. It is not a semantic correctness verdict and emits no “finish now” instruction.
- `CONTINUE`: a real machine condition remains, such as explicitly required validation, unresolved external action, or managed-process cleanup.
- `BLOCKED`: a hard state/safety invariant is violated, such as workspace identity mismatch, protected-work mutation under durable tracking, or any mutation in a read-only profile.

An unfinished optional plan is not a blocker.

## Checkpoint / persistence

Checkpoints and persistence are lazy capabilities for long/noisy transitions or cross-conversation durability. Persistence schema v5 stores the exact request anchor, steers, optional plan, minimal workspace identity, and unresolved consequential external-action identities. It does not persist a model-written task objective/acceptance restatement. Historical validation stays historical after resume; current reality wins.

## Heavy/high-risk paths

Full content baselines, ignored-file watches, workspace fingerprints, generation-based freshness, release lineage, publication gates, managed processes, and non-idempotent external-action reconciliation remain available where their durability/safety value is real. They are not part of the ordinary coding loop.
