# codex-loop runtime protocol

Use `python scripts/codex_loop.py ...`. Commands emit JSON. Runtime state is task-scoped under a private temp directory; it never writes `.codex-loop` state into the repository. `bootstrap` binds the created task as the workspace's active task, so ordinary task-scoped commands may omit `--task-id`. Pass an explicit `--task-id` when deliberately addressing a non-active task or when low-level audit/debugging requires it. If no active task exists, task-scoped commands fail closed.

## Persistent workspace registry and conversation grants

Workspace registry commands are host-local and not task-scoped. They never bootstrap a repository task and never imply Local mode.

```bash
python3 scripts/codex_loop.py workspace-register --name epiagent --path /ABS/PATH --kind repository
python3 scripts/codex_loop.py workspace-register --name piwork --path /ABS/PATH --kind development_root
python3 scripts/codex_loop.py workspace-registry-list
python3 scripts/codex_loop.py workspace-resolve epiagent
python3 scripts/codex_loop.py workspace-remove epiagent
```

Updating an existing canonical alias requires explicit `--update`. Registry state lives at `~/.codex-loop/workspace-registry.json` (or the test-only/process override `CODEX_LOOP_HOME`) and stores only alias/path/kind identity.

After the host/model observes explicit user authorization in the current conversation, record a semantic grant:

```bash
python3 scripts/codex_loop.py workspace-grant epiagent \
  --authorization-evidence "user explicitly granted EpiAgent path access in this conversation"
```

The first grant returns a high-entropy `session_id`. Keep it only in the current conversation context; later calls pass it explicitly (or through host-owned ephemeral `CODEX_LOOP_SESSION_ID`):

```bash
python3 scripts/codex_loop.py workspace-grants --session-id SESSION_NONCE
python3 scripts/codex_loop.py workspace-resolve epiagent --session-id SESSION_NONCE
```

The session file stores only the registered-workspace fingerprint and a digest of the evidence. Registry mutation makes an older grant stale. A new conversation has no old nonce and therefore no usable grant.

Before host filesystem access, combine semantic grant with actual host/RDC authorization. Pass only roots the host has independently observed as authorized and fail closed with `--require-access`:

```bash
python3 scripts/codex_loop.py workspace-resolve epiagent \
  --session-id SESSION_NONCE \
  --host-authorized-root /HOST/AUTHORIZED/ROOT \
  --require-access
```

This check cannot create RDC permission or change `allowedDirectories`. See `references/workspace-registry.md`.

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

Passing criteria and acknowledging steers require evidence at the current workspace generation. Any later workspace mutation makes prior pass/ack evidence stale; re-check the condition, then repeat `criterion --status pass` or `steer-ack` with fresh evidence. Working criteria guide execution but do not independently prove completion of the original objective.

## Objective completion audit

New tasks created through the Codex Loop CLI require a separate upstream-style objective audit before `completion` may return `PASS`. Re-derive the requirements from the original objective and referenced current files/plans/specifications/issues/user instructions; do not merely restate the bootstrap criteria. Read `upstream-codex-goal-continuation.md` and `upstream-adaptation.md` before changing this behavior.

Record the audit as JSON:

```bash
python scripts/codex_loop.py objective-audit --cwd REPO <<'JSON'
{
  "requirements": [
    {
      "requirement": "Use the named workflow to its required end state",
      "status": "proven",
      "evidence": "The workflow's authoritative completion receipt reports PASS.",
      "authoritative_source": "workflow completion receipt"
    }
  ]
}
JSON
```

Allowed statuses are `proven`, `contradicted`, `incomplete`, `weak`, and `missing`. A `proven` item requires non-empty evidence and an authoritative source. Every requirement must be `proven` for the audit to pass. The audit is bound to the stored objective, current workspace generation, and current `plan_revision`; a later workspace mutation or user steer makes it stale. Re-run the objective audit after those changes and before final `completion`.

The runtime deliberately does not understand domain-specific workflow internals. If the objective names another Skill, gate, invariant, or deliverable, record the authoritative evidence proving that requirement rather than adding a domain-specific dependency mechanism to Codex Loop.

## Progress visibility configuration

Progress behavior is host-facing policy with enhanced defaults for durable objectives and low-noise defaults for direct work. The effective user configuration lives outside the repository in the private host config.

```bash
python3 scripts/codex_loop.py progress-config
python3 scripts/codex_loop.py progress-policy --lifecycle-mode durable
python3 scripts/codex_loop.py progress-config --mode enhanced --interval-seconds 20 --tool-call-interval 4
python3 scripts/codex_loop.py progress-config --reset
```

`progress-config` writes only `~/.codex-loop/host.json` (or `CODEX_LOOP_HOME/host.json`) with private file permissions and preserves unrelated host config keys. Invalid existing JSON is never overwritten. `progress-policy` treats invalid/missing progress configuration as a non-blocking preference failure and falls back to enhanced defaults. See `progress-visibility.md`.

## Optional state-only persistence

Persistence is off by default and Drive credentials remain host-owned. For an explicitly enabled durable task:

```bash
python3 scripts/codex_loop.py persistence-export --cwd REPO --backend google_drive --repository OWNER/REPO
python3 scripts/codex_loop.py persistence-validate --manifest /PRIVATE/TEMP/state-only.json
python3 scripts/codex_loop.py persistence-cleanup-plan --manifest /PRIVATE/TEMP/state-only.json
```

`persistence-export` writes only to the task-private runtime directory and returns a path for host connector upload. `--backend off` creates no file and reports the default-disabled policy. The Google Drive connector owns upload/download/list/Trash operations and all authentication. A validated manifest is recovery evidence only; reconcile current workspace, instructions, and external actions before resuming. See `references/persistence.md`.

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

## Post-push workspace Skill deployment handoff

For a Web-mode task that edits the Skill already active/present in the current ChatGPT workspace, a verified source push is followed by a mandatory deployment handoff for the same published commit:

```bash
python3 scripts/codex_loop.py skill-deploy-handoff \
  --cwd REPO \
  --skill-name NAME \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA
```

The command requires an active Codex Loop task, synchronizes the current workspace generation, validates the Skill name/repository/full commit identity, and records an `external_non_idempotent` action with:

```text
kind     = chatgpt_skill_update
identity = chatgpt-skill:NAME@COMMIT
state    = planned
```

It returns `DEPLOY_PENDING`, a preferred supported host-managed Skill update action, and a `surface_save_update_ui` fallback. The planned external action is intentionally completion-blocking. If a host-managed update or Save/Update handoff is actually initiated, advance that same action to `dispatched`; record `terminal_success` only after observable evidence shows the intended Skill revision is active. Repeating the handoff for the same Skill/commit deduplicates to the existing action.

The handoff never manufactures deployment permission and never authorizes browser automation. If completing the update requires computer use, the normal explicit current-task computer-use gate still applies. If no update surface exists, leave the action unresolved and report `DEPLOY_PENDING` rather than silently accepting a newer GitHub revision than the active workspace Skill.

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

The canonical root and shared Git repository identity must remain stable for the task. HEAD/branch may move only through the existing Git-mutation workflow. Use Git worktrees for concurrent tasks. Installed Skills are deployment state and are never edited in place, but a verified-latest installed Skill may be copied once to bootstrap a fresh workspace under `references/source-acquisition.md`; after that copy, only the new workspace is authoritative. Copied full-source directories without that provenance/freshness proof, disposable release staging, and unpacked artifacts are never later development baselines. See `references/release-lineage.md`.

When Web mode needs source from GitHub, use the exact-revision workspace-download Actions artifact contract in `references/source-acquisition.md`. A shell/network inability to run `git clone` in the container is not a reason to invent another source transport. Likewise, inability of one connector query to observe a workflow run must be recorded as an observability limitation, not as proof that the workflow failed or never ran.

Commit source before packaging. Plan an export from the audited Git HEAD, build outside the canonical tree, then record the artifact hash:

```bash
python scripts/codex_loop.py release-plan --cwd REPO --artifact-name skill.zip --archive-prefix codex-loop
python scripts/codex_loop.py release-record --cwd REPO --artifact-name skill.zip \
  --artifact-sha256 SHA256 --evidence "artifact built from the planned commit archive and verified"
```

`release-plan` fails when tracked/staged source is uncommitted. Untracked paths are reported but excluded because export comes from `git archive` of the exact commit. A release receipt is bound to task generation plus source commit/tree and becomes stale after later observed workspace mutation.

Only when the current conversation is in Local mode, use native Git through Remote Desktop Commander on the persistent canonical repo under `LOCAL_ROOT` for repository publishing. A generic `push` in a conversation that is still in web mode does not silently select local mode. Observe the destination branch with native Git, then plan against that state:

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
python scripts/codex_loop.py relay-frame --cwd AUTHORIZED_ROOT --input SOURCE --output ENVELOPE.txt
python scripts/codex_loop.py relay-receive --cwd AUTHORIZED_ROOT --envelope ENVELOPE.txt --output DESTINATION --expected-size N --expected-sha256 SHA256
```

These commands do not create standing transfer permission and do not store payload bytes in task state. `--cwd` is the authorized filesystem root for the relay command: every resolved input/envelope/output path, including symlink targets, must remain below it. `relay-receive` publishes only after strict Base64 decode plus exact size/SHA-256 verification. Integrity failures return a structured failure class and `VERIFIED_CHUNK_RELAY` fallback rather than guessing a repair. Actual cross-surface carriage of the envelope remains host-owned.

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


## Execution outcome recording

`validation-record` accepts legacy `--exit-code` or richer execution fields: `--workload-status`, `--process-status`, `--cleanup-status`, `--evidence-kind`, plus workload/process/cleanup evidence. Terminal workload pass/fail requires authoritative evidence. `TEARDOWN_STALLED` requires a terminal workload and is not equivalent to workload failure. See `execution-supervision.md`.

## Host Profile and resume

Use `host-config show|get|set|unset|reset` for private Host Profile state; `progress-config` is a compatibility facade. Use `persistence-resume-plan` before `persistence-resume`; resume creates a fresh durable task rather than restoring stale validation/review/PASS state.
