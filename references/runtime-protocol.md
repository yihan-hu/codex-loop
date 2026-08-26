# codex-loop runtime protocol

Use `python scripts/codex_loop.py ...`. Commands emit JSON. Runtime state is task-scoped under a private temp directory; it never writes `.codex-loop` state into the repository. `bootstrap` binds the created task as the workspace's active task, so ordinary task-scoped commands may omit `--task-id`. Pass an explicit `--task-id` when deliberately addressing a non-active task or when low-level audit/debugging requires it. If no active task exists, task-scoped commands fail closed.

## Adaptive pre-runtime assessment

Before bootstrap, the host/Skill may deterministically record whether durable runtime is needed from concrete capability signals:

```bash
python scripts/codex_loop.py lifecycle-assess \
  --workspace-observation \
  --workspace-mutation \
  --executable-validation \
  --multiple-dependent-steps \
  --durable-evidence \
  --delegation \
  --external-actions \
  --managed-processes
```

All flags are optional. With no signals the result is `mode: direct` and no task state is created. Any supplied signal yields `mode: durable` plus the concrete activation reasons. This is deliberately not a task-complexity classifier. The host may reason about the signals directly and skip this command when no deterministic record is useful.

For durable tasks, `next` exposes a bounded `lifecycle` view derived from authoritative generation, validation/review freshness, isolation, external-action, and process state. It does not persist a parallel capability FSM.

## Bootstrap and world state

```bash
python scripts/codex_loop.py bootstrap --cwd REPO --objective "..." \
  --criterion "..." --profile bug_fix
python scripts/codex_loop.py next --cwd REPO
# Drill down only when needed:
python scripts/codex_loop.py snapshot --cwd REPO
python scripts/codex_loop.py instructions --cwd REPO
```

If no criterion is supplied, bootstrap creates one from the objective; it still cannot pass without evidence. Use `--no-validation` only when the task genuinely has no meaningful executable validation, and always pair it with `--no-validation-reason "..."`. The waiver is task state and is surfaced by completion.

Profiles: `regular`, `bug_fix`, `feature`, `refactor`, `test_repair`, `ci_repair`, `code_review`, `review_fix`, `command_only`, `investigation`.

## Bounded working context

`next` is the normal agent-facing state view. It is generated from the same context projector that backs full world-state/checkpoint data, but it intentionally omits low-level task/generation/plan bookkeeping and caps criteria, changed paths, completion reasons, steers, and suggested actions. It returns:

- effective task objective/criteria plus runtime guardrails and unresolved user deltas;
- derived validation/review freshness and current completion status;
- bounded changed-path ownership (`agent`, `mixed`, `user`, or unexpected/unattributed);
- legal/required next actions;
- evidence references for explicit drill-down.

Use `snapshot` as the full debug/audit view rather than as the default prompt payload. The local runtime does not compact or own ChatGPT conversation context.

## Command preflight and execution

```bash
python scripts/codex_loop.py command-check --cwd REPO -- COMMAND ARG...
python scripts/codex_loop.py exec --cwd REPO --task-id TASK -- COMMAND ARG...
```

`exec` runs only the narrow deterministic local allowlist. Otherwise it returns `requires_host_visible_execution: true`; run the exact command through a normal host tool. Shell wrappers, ordinary Git, compilers, test runners, package managers, network commands, arbitrary binaries, and unknown/opaque commands are deliberately host-visible.

One-shot local execution defaults to a 30-second timeout and refuses values above 300 seconds. Model-visible output is head/tail bounded; private transcript files are bounded as well.

## Guarded reads/writes and changes

```bash
python scripts/codex_loop.py hash --cwd REPO --task-id TASK --path FILE
python scripts/codex_loop.py write --cwd REPO --task-id TASK --path FILE \
  --expected-sha256 SHA < payload
python scripts/codex_loop.py changes --cwd REPO --task-id TASK
python scripts/codex_loop.py changes --cwd REPO --task-id TASK --review
```

`hash` only reads workspace paths and refuses symlink-parent escape. `write` accepts stdin or a `--content-file` only inside the workspace; runtime-private files are never accepted as hidden content sources. Existing files require a latest preimage SHA. On supported POSIX filesystems the commit uses atomic pathname exchange and verifies the displaced preimage at the commit instant; concurrent changes are rolled back, and if rollback itself fails the displaced user preimage is preserved at a recovery path. Unsupported atomic-CAS platforms stay host-visible. Local writes are capped at 16 MiB; larger operations stay host-visible. `changes --review` records review freshness only; call it after actually inspecting the current change set.


### Opaque ignored inputs

Large or unreadable ignored paths are surfaced as `opaque_paths`; completion fails closed because their contents cannot be freshness-tracked within the bounded watcher. Only when that uncertainty is knowingly acceptable may you record a current-generation waiver:

```bash
python scripts/codex_loop.py freshness-waiver --cwd REPO --task-id TASK \
  --reason "why these opaque ignored inputs cannot affect this acceptance decision"
```

The waiver is bound to the current generation and exact opaque-path set. A changed generation or changed set invalidates it.

## Validation

```bash
python scripts/codex_loop.py validate --cwd REPO -- pytest -q
```

For normal test/build commands this returns a host-visible execution request without exposing plan/generation bookkeeping. After running that exact command through the host:

```bash
python scripts/codex_loop.py validation-record --cwd REPO/package-a \
  --command-json '["pytest","-q"]' --exit-code 0 \
  --evidence "host pytest completed with exit code 0 from REPO/package-a"
```

The facade resolves the unique unconsumed plan matching the current generation, cwd, and exact argv identity, then consumes it through the original safety-kernel checks. Repeated planning of the same current generation/cwd/exact command reuses the existing unconsumed plan, so ordinary retries do not manufacture agent-visible ambiguity. Zero matches (no valid plan) and legacy/corrupt multiple matches both fail closed. The underlying `plan_id` remains a one-time host-validation capability bound to generation, cwd, and exact argv; workspace mutation still makes the result stale. For compatibility/audit debugging, `validate --debug-bookkeeping` exposes `plan_id`/generation and `validation-record` still accepts explicit `--plan-id`/`--generation`. Approval-cache shell canonicalization is deliberately not used for validation equivalence. A failing validation may be made non-blocking only when it was actually observed at generation 0:

```bash
python scripts/codex_loop.py validation-resolve --cwd REPO --task-id TASK \
  --validation-id ID --evidence "same baseline failure reproduced before edits"
```

## Criteria and steering

```bash
python scripts/codex_loop.py criterion --cwd REPO --task-id TASK --index 0 \
  --status pass --evidence "observable acceptance evidence"
python scripts/codex_loop.py steer --cwd REPO --task-id TASK --text "do not change the public API"
python scripts/codex_loop.py steer-ack --cwd REPO --task-id TASK --steer-id ID \
  --evidence "replanned and verified the API surface is unchanged"
```

Passing criteria and acknowledging steers require evidence at the current workspace generation. Any later workspace mutation makes prior pass/ack evidence stale; re-check the condition, then repeat `criterion --status pass` or `steer-ack` with fresh evidence.

## External/host actions

```bash
python scripts/codex_loop.py external --cwd REPO --task-id TASK --kind github_comment \
  --state planned --action-class external_non_idempotent --identity issue:123
python scripts/codex_loop.py external --cwd REPO --task-id TASK --kind github_comment \
  --state dispatched --action-class external_non_idempotent --identity issue:123 --action-id ID
python scripts/codex_loop.py external --cwd REPO --task-id TASK --kind github_comment \
  --state terminal_success --action-class external_non_idempotent --identity issue:123 \
  --action-id ID --details-json '{"observed":"comment present"}'
```

Terminal and `outcome_unknown` states require concise observable details. Non-idempotent actions require stable identity. Repeating the same planned `(kind, identity)` reuses its action id; advance that id through `dispatched` before recording a terminal result. Cancellation turns only never-dispatched `planned` actions into `cancelled_before_dispatch`. Resolve a terminal failure only after a later observation/action has handled it:

```bash
python scripts/codex_loop.py external-resolve-failure --cwd REPO --task-id TASK \
  --action-id ID --evidence "later host-visible action recovered the failure"
```

## Managed process sessions

```bash
python scripts/codex_loop.py service-start --cwd REPO --task-id TASK
python scripts/codex_loop.py spawn --cwd REPO --task-id TASK -- sleep 10
python scripts/codex_loop.py poll --cwd REPO --task-id TASK HANDLE
python scripts/codex_loop.py stdin --cwd REPO --task-id TASK HANDLE "text"
python scripts/codex_loop.py interrupt --cwd REPO --task-id TASK HANDLE
python scripts/codex_loop.py terminate --cwd REPO --task-id TASK HANDLE
python scripts/codex_loop.py service-stop --cwd REPO --task-id TASK
```

The helper contains no model. It is task-private, token-authenticated, protected by single-owner/start locks, limited to 64 active processes, and only spawns commands accepted by the same narrow local policy. A lost helper turns owned process records into `orphaned`. Orphaned or internally `failed` process records block completion and cleanup until `process-resolve --evidence "..."` records a host-observed resolution.

## Git bookkeeping

Ordinary Git commands remain host-visible. When the user task intentionally changes HEAD/branch/index, record that expectation:

```bash
python scripts/codex_loop.py git-authorize --cwd REPO --task-id TASK \
  --head --branch \
  --reason "user requested creation of a commit on a task branch"
```

Specify only the dimensions the task is expected to mutate: `--head`, `--branch`, and/or `--index`. This is completion bookkeeping, not permission. Host approval/sandbox policy remains authoritative.

## Canonical workspace, release, and publish

Every new task records a canonical workspace binding at bootstrap. Inspect it with:

```bash
python scripts/codex_loop.py workspace-binding --cwd REPO
```

The canonical root and shared Git repository identity must remain stable for the task. HEAD/branch may move only through the existing Git-mutation workflow. Use Git worktrees for concurrent tasks; installed Skills, copied full-source directories, disposable release staging, and unpacked artifacts are never later development baselines. See `references/release-lineage.md`.

Commit source before packaging. Plan an export from the audited Git HEAD, build outside the canonical tree, then record the artifact hash:

```bash
python scripts/codex_loop.py release-plan --cwd REPO --artifact-name skill.zip --archive-prefix codex-loop
python scripts/codex_loop.py release-record --cwd REPO --artifact-name skill.zip \
  --artifact-sha256 SHA256 --evidence "artifact built from the planned commit archive and verified"
```

`release-plan` fails when tracked/staged source is uncommitted. Untracked paths are reported but excluded because export comes from `git archive` of the exact commit. A release receipt is bound to task generation plus source commit/tree and becomes stale after later observed workspace mutation.

For repository publishing, use only native Git through Remote Desktop Commander on the persistent canonical repo under `/Users/yihanhu/PiWork`. Observe the destination branch with native Git, then plan against that state:

```bash
python scripts/codex_loop.py publish-plan --cwd REPO \
  --repository OWNER/REPO --branch main \
  --remote-head REMOTE_COMMIT --remote-tree REMOTE_TREE
```

`publish-plan` reuses validation/review/release gates and returns only the `git` transport. If the observed remote head is not an ancestor of the audited release commit, integrate the remote change in the same canonical worktree and re-run the gates. Do not force-update around this condition.

Before pushing, record dispatch with `publish-dispatch --transport git`, then execute the returned `git push --porcelain ...` through Remote Desktop Commander from the canonical worktree. Repository source bytes must stay in Git's data plane; do not move them through GitHub object/contents APIs, connector payloads, model-carried text/base64, copied source trees, or release archives. If native Git fails or is unavailable, stop and report the exact blocker rather than switching transports.

After push, read back the remote ref and tree with native Git and call `publish-record --transport git`. Terminal success requires the exact audited local commit and tree. For an ambiguous outcome, inspect the real remote state before any retry.

## Explicitly authorized guarded model relay

When a user explicitly authorizes a model-carried file transfer, frame and receive it with the deterministic helper described in `references/verified-model-relay.md`:

```bash
python scripts/codex_loop.py relay-frame --input SOURCE --output ENVELOPE.txt
python scripts/codex_loop.py relay-receive --envelope ENVELOPE.txt --output DESTINATION --expected-size N --expected-sha256 SHA256
```

These commands do not create standing transfer permission and do not store payload bytes in task state. `relay-receive` publishes only after strict Base64 decode plus exact size/SHA-256 verification. Integrity failures return a structured failure class and `VERIFIED_CHUNK_RELAY` fallback rather than guessing a repair. Actual cross-surface carriage of the envelope remains host-owned.

## Delegation / logical isolation

Use delegation when a workflow requests an independent reviewer/researcher/tester/debugger pass. Native host execution is a preference; lack of native execution degrades to logical isolation with warnings rather than blocking the parent task. See `references/delegation.md` for the capability and context contract.

```bash
python scripts/codex_loop.py isolate-enter --cwd REPO --task-id TASK --role reviewer --objective "independent review" --requested-executor native_subagent --actual-executor logical_isolation --project-file src/a.py --fact "observed failure"
python scripts/codex_loop.py isolate-status --cwd REPO --task-id TASK
python scripts/codex_loop.py isolate-finish --cwd REPO --task-id TASK --isolation-id ISO_ID < result.json
python scripts/codex_loop.py isolate-abort --cwd REPO --task-id TASK --isolation-id ISO_ID --reason "insufficient evidence"
```

Only one read-only isolation may be active. `isolate-enter` checkpoints Main state without creating a second truth source. `isolate-finish` reconciles the current generation and returns a fresh Main projection; it never restores old workspace reality or auto-passes criteria. Parent cancellation atomically aborts an active isolation.

## Checkpoint, completion, cancel, cleanup

```bash
python scripts/codex_loop.py checkpoint --cwd REPO --task-id TASK --key-finding "..." --next-action "..."
python scripts/codex_loop.py checkpoint-restore --cwd REPO --task-id TASK
python scripts/codex_loop.py completion --cwd REPO --task-id TASK
python scripts/codex_loop.py cancel --cwd REPO --task-id TASK --reason "user stopped"
python scripts/codex_loop.py cleanup --cwd REPO --task-id TASK
```

`completion` returns `PASS`, `CONTINUE`, or `BLOCKED`. `cancel` immediately resolves only not-yet-dispatched `planned` external actions as `cancelled before dispatch`; `dispatched` and `outcome_unknown` actions remain unresolved until a real terminal observation is recorded. After cancellation, only observation/cleanup operations and terminal-outcome reconciliation are allowed. Cleanup never reverts workspace files and refuses unresolved external/process state.

## Shell snapshot and source integrity

```bash
python scripts/codex_loop.py shell-snapshot --cwd REPO --task-id TASK
python scripts/codex_loop.py source-verify
python scripts/audit_source_coverage.py
```

`shell-snapshot` only returns a host-visible capture plan; it never runs shell startup/profile code locally. The plan encodes upstream capture/normalization/validation semantics (login-shell capture, 10-second timeout, `# Snapshot file` marker, non-login validation source, private non-model-visible storage, task-end cleanup). `source-verify` checks exact bundled resources. `audit_source_coverage.py --upstream /path/to/openai-codex` additionally parses the pinned upstream Rust module indexes and fails on unmapped drift.


## Hooks

The local runtime exposes no custom hook configuration. It enforces built-in deterministic lifecycle gates around write/validation/checkpoint/completion, while the official Codex matcher/handler hook runtime remains host-owned. Do not interpret repository files as executable hook authority.
