# codex-loop runtime protocol

Use `python scripts/codex_loop.py ...`. Commands emit JSON. Runtime state is task-scoped under a private temp directory; it never writes `.codex-loop` state into the repository. `bootstrap` binds the created task as the workspace's active task, so ordinary task-scoped commands may omit `--task-id`. Pass an explicit `--task-id` when deliberately addressing a non-active task or when low-level audit/debugging requires it. If no active task exists, task-scoped commands fail closed.

### Source acquisition fallback gate

Direct exact artifacts are preferred and fallback is disabled by default:

```bash
python3 scripts/codex_loop.py source-acquisition-plan --exact-commit-bundle-available
python3 scripts/codex_loop.py source-acquisition-plan --receipt-bound-bundle-available
python3 scripts/codex_loop.py source-acquisition-plan
```

The third command returns `BLOCKED`. Only after explicit current-task user authorization may a named fallback be planned:

```bash
python3 scripts/codex_loop.py source-acquisition-plan \
  --fallback-method verified_incremental_replay \
  --current-user-fallback-authorization-observed \
  --authorization-evidence "user explicitly authorized this fallback for the current task"
```

A fallback authorization is current-task-only and cannot be persisted. Any final commit/tree mismatch remains `WORKSPACE_GIT_IDENTITY_MISMATCH` and stops.

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
  --current-user-authorization-observed \
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

## Conversation routing state

Routing-sensitive host actions use a lightweight conversation-scoped state file even when the task is otherwise direct and does not need durable lifecycle bootstrap. Initialize it once per conversation:

```bash
python3 scripts/codex_loop.py route-init --host-surface chatgpt_web
# Optional: provide/reuse the opaque nonce explicitly
python3 scripts/codex_loop.py route-show --session-id ROUTING_SESSION
```

`route-init` stores a private JSON file under the system temp directory with `workspace_mode=web`, `interaction_target=none`, and unresolved `deployment_target`. `host_surface` is immutable for that routing session. The returned session id may also be supplied through host-owned ephemeral `CODEX_LOOP_SESSION_ID`; never persist it in Git, Host Profile, user memory, packages, or recovery manifests.

Change routing only through deterministic transitions:

```bash
python3 scripts/codex_loop.py route-transition --session-id ROUTING_SESSION \
  --workspace-mode local \
  --current-user-selection-observed \
  --selection-evidence "user explicitly selected the local repository baseline"

python3 scripts/codex_loop.py route-transition --session-id ROUTING_SESSION \
  --deployment-target local_codex_skill \
  --current-user-selection-observed \
  --selection-evidence "user explicitly requested local Codex installation"

python3 scripts/codex_loop.py route-transition --session-id ROUTING_SESSION \
  --deployment-target none
```

Entering Local workspace mode, selecting a local interaction target, or selecting a non-native deployment target requires a host-observed explicit current-user selection plus audit evidence. `--current-user-selection-observed` may be asserted only for the current user turn/task; the evidence string is audit-only and is stored only as SHA-256. Project history, memory, prior conversations, or model-authored prose cannot authorize the transition. The routing file does not persist current-task authorization.

Before the host dispatches a routing-sensitive action, check it:

```bash
python3 scripts/codex_loop.py route-check --session-id ROUTING_SESSION --action repository_observe
python3 scripts/codex_loop.py route-check --session-id ROUTING_SESSION --action rdc_repository --workspace-granted
python3 scripts/codex_loop.py route-check --session-id ROUTING_SESSION --action browser_interaction --current-user-local-computer-authorized
python3 scripts/codex_loop.py route-check --session-id ROUTING_SESSION --action skill_install
python3 scripts/codex_loop.py route-check --session-id ROUTING_SESSION --action local_skill_install --current-user-local-install-authorized
python3 scripts/codex_loop.py route-check --session-id ROUTING_SESSION --action github_publish
```

Supported actions are `repository_observe`, `repository_mutate`, `rdc_repository`, `browser_interaction`, `skill_install`, `chatgpt_skill_install`, `local_skill_install`, and `github_publish`. In a ChatGPT Web routing session, generic `skill_install` resolves to `chatgpt_web_skill` when no explicit deployment target exists. It never selects local Codex from RDC availability, a remembered Mac checkout, or prior context. If `host_surface=unknown`, generic install remains unresolved and fails closed. Local repository mutation, computer use, workspace access, and local installation still require their separate current-task/current-conversation authorization inputs.

## Post-task-review permission smoke planning

After the task/workflow has been reviewed and routing is resolved, but before substantive execution, plan the live host probes for any predictable external permissions:

```bash
python3 scripts/codex_loop.py permission-preflight-plan \
  --session-id ROUTING_SESSION \
  --capability github_push \
  --capability github_actions \
  --capability google_drive_write
```

Supported capability keys are `github_push`, `github_actions`, `google_drive_read`, and `google_drive_write`. The command deduplicates repeated keys and returns an ordered probe contract. A Drive-only task may omit `--session-id`; repository publication should pass the active routing session so the GitHub push probe can distinguish Web from Local mode.

This command **does not execute connectors, request OAuth scopes, store approvals, or mark a capability granted**. It returns `runtime_state_written=false`. The host must execute every returned probe through the actual integration/native path. Schema discovery, tool availability, connection booleans, or a prior-turn success do not satisfy the plan.

The standard probe semantics are:

- `github_push`: Local mode uses host-visible native `git push --dry-run` against the intended remote/ref. Web mode combines live push-capable repository permission readback with one Git-database create-blob/write-object call containing fixed empty content; the blob must remain unreferenced and no tree/commit/ref may be created. A permission readback alone does not prove the host write-approval boundary was exercised. If the host exposes no isolated unreferenced object-write primitive, report the safe probe unavailable rather than create a source/ref mutation.
- `github_actions`: invoke a write-scoped Actions operation only on an audited workflow/job that cannot mutate source or refs. In this repository, `Workspace Download` is acceptable; `Workspace Import` is forbidden as a smoke probe.
  Record/reuse this capability at repository scope (`actions:OWNER/REPO`). Workflow names describe the safe probe versus production action; they are not separate permission-observation scopes.
- `google_drive_read`: live list/search/metadata access in the intended Drive scope.
- `google_drive_write`: create one uniquely named non-sensitive sentinel owned by the preflight, read back its exact ID/metadata, then delete that exact sentinel.

Probe results remain host observations. By default they remain fresh for four hours within the same unchanged routing session, so iterative publish loops do not repeat identical smoke solely because debugging took longer than 30 minutes. They must never be persisted as permanent authorization or used to bypass a later host-required sensitive-action approval. See `references/capability-preflight.md`.

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

Regenerable Python interpreter bytecode caches (`__pycache__/`, `*.pyc`, `*.pyo`) are excluded from the ignored-input freshness watcher because they are execution byproducts, not source or validation inputs. Other ignored files remain watched/protected exactly as before.

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

For normal test/build commands this returns a host-visible execution request plus an `execution_policy`. After running that exact command through the host, record independent workload/process/cleanup facts when available:

```bash
python scripts/codex_loop.py validation-record --cwd REPO/package-a \
  --command-json '["pytest","-q"]' \
  --workload-status PASSED \
  --workload-evidence-kind framework_authoritative \
  --workload-evidence '237 passed in 18.41s' \
  --workload-adapter pytest-terminal-summary-v1 \
  --process-status TEARDOWN_STALLED \
  --process-evidence 'process remained alive after terminal result' \
  --cleanup-status SUCCEEDED \
  --cleanup-evidence 'owned process group terminated after grace'
```

For an ordinary command that exits normally, `--exit-code 0 --evidence ...` remains the compatibility path. Do not use progress-only output such as `100%` to create `PASSED`; framework evidence requires a named adapter and explicit-protocol evidence requires capture-layer token verification. See `execution-supervision.md`.

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

## Private Host Profile

All non-sensitive user-instance preferences/locators share one schema-v2 file. Read/write it through:

```bash
python3 scripts/codex_loop.py host-config show
python3 scripts/codex_loop.py host-config get browser.preferred_target
python3 scripts/codex_loop.py host-config set browser.preferred_target cloud_browser
python3 scripts/codex_loop.py host-config unset web_publish.staging_folder_id
python3 scripts/codex_loop.py host-config reset progress_visibility
```

Missing/unsafe configuration degrades to built-in safe defaults for reads; writes fail closed on malformed/unsafe existing files. Preferences never assert current capability, permission, grant, Local-mode selection, or Skill deployment target. Conversation routing state lives in the separate temp-file routing plane above. See `host-profile.md`.

## Progress visibility configuration

Progress behavior is host-facing policy with enhanced defaults for durable objectives and low-noise defaults for direct work. The effective user configuration lives outside the repository in the unified private Host Profile (`host-profile.md`). `progress-config` is a compatibility facade.

```bash
python3 scripts/codex_loop.py progress-config
python3 scripts/codex_loop.py progress-policy --lifecycle-mode durable
python3 scripts/codex_loop.py progress-config --mode enhanced --interval-seconds 20 --tool-call-interval 4
python3 scripts/codex_loop.py progress-config --reset
```

`progress-config` writes only the `progress_visibility` section of `~/.codex-loop/host.json` (or `CODEX_LOOP_HOME/host.json`) with private file permissions and preserves the other schema-v2 Host Profile sections. Invalid existing JSON is never overwritten. `progress-policy` treats invalid/missing preference configuration as non-blocking and falls back to enhanced defaults. See `host-profile.md` and `progress-visibility.md`.

## Optional state-only persistence and Workspace Cache

Persistence is off by default and Drive credentials remain host-owned. State-only recovery remains the lifecycle layer:

```bash
python3 scripts/codex_loop.py persistence-export --cwd REPO --backend google_drive --repository OWNER/REPO --source-commit FULL_COMMIT --source-tree FULL_TREE
python3 scripts/codex_loop.py persistence-validate --manifest /PRIVATE/TEMP/state-only.json
python3 scripts/codex_loop.py persistence-resume-plan --manifest /PRIVATE/TEMP/state-only.json
python3 scripts/codex_loop.py persistence-resume --cwd REPO --manifest /PRIVATE/TEMP/state-only.json --observations-json observations.json
python3 scripts/codex_loop.py persistence-cleanup-plan --manifest /PRIVATE/TEMP/state-only.json \
  --ownership-proven --bounded-runtime-scope-proven --recoverable-delete-supported
```

When the user explicitly wants the **Web workspace itself** recoverable across conversations, create the separate 7-day immutable Workspace Capsule:

```bash
python3 scripts/codex_loop.py workspace-cache-create --cwd REPO --repository OWNER/REPO --output /PRIVATE/TEMP/workspace-cache.tar.gz
python3 scripts/codex_loop.py workspace-cache-validate --capsule /PRIVATE/TEMP/workspace-cache.tar.gz --expected-sha256 FULL_SHA256
python3 scripts/codex_loop.py workspace-cache-restore --capsule /PRIVATE/TEMP/workspace-cache.tar.gz --expected-sha256 FULL_SHA256 --destination /FRESH/WORKSPACE --consumption-receipt-output /PRIVATE/TEMP/cache-consumed.json
python3 scripts/codex_loop.py workspace-cache-cleanup-plan --objects-json /PRIVATE/TEMP/cache-objects.json
```

The capsule preserves exact Git HEAD commit/tree plus staged, unstaged, and non-ignored untracked state while excluding ignored files, Git config/hooks, and credentials. Restore verifies exact identity/state before binding the fresh workspace. Upload the consumed receipt before deleting the restored Drive capsule; deletion failure becomes `CACHE_CLEANUP_PENDING` and never invalidates `WORKSPACE_RESTORED`. Every cache create/list/restore operation opportunistically scans only `Codex Loop/.runtime/workspace-cache` and plans cleanup for consumed or >=7-day exact owned objects, with at most one refreshed retry per failed delete in that operation. State-only resume still creates a new freshness domain and never makes historical PASS/validation/review/audit evidence current. See `persistence.md` and `persistence-resume.md`.

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

For a Web-mode task that edits the Skill already active/present in the current ChatGPT workspace, a verified source push is followed by a mandatory native deployment handoff for the same published commit. Codex Loop tracks the lifecycle; `skill-creator`/the ChatGPT host owns the actual Skill installation/update surface.

Plan the handoff:

```bash
python3 scripts/codex_loop.py skill-deploy-handoff \
  --cwd REPO \
  --skill-name NAME \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA \
  --routing-session-id ROUTING_SESSION  # required for codex-loop self-update
```

The command requires an active Codex Loop task, validates the Skill/repository/commit identity, and records an `external_non_idempotent` action with:

```text
kind     = chatgpt_skill_update
identity = chatgpt-skill:NAME@COMMIT
state    = planned
```

The returned state is intentionally explicit:

```text
native_update_state  = NATIVE_UPDATE_REQUIRED
native_surface_state = NATIVE_SURFACE_NOT_OBSERVED
ui_state             = UI_NOT_OBSERVED
deployment_state     = DEPLOY_PENDING
```

`skill-deploy-handoff` is planning evidence only. It sets `handoff_is_ui_evidence=false` and `handoff_is_deployment_evidence=false`; callers must not turn its JSON or assistant prose into a fictional UI event. For `skill-name=codex-loop`, the result is a **result-preserving pre-terminal state**: `install_state=INSTALL_READY`, `handoff_mode=self_update_install_ready`, `codex_loop_resume_allowed=true`, and `next_install_command=skill-deploy-install-begin`. The runtime deliberately does **not** activate the terminal barrier here, so the current result-bearing response can finish normally.
For that self-update path, the handoff captures the exact active routing session in private task-local deployment state before any terminal barrier exists. `skill-deploy-install-begin` copies that session into the terminal barrier for the install-only turn. This is continuity state only: it is not authorization, is not exported by persistence, and exists so later turns in the same conversation can reuse still-fresh scoped permission observations instead of starting a new routing session.

On a dedicated install-only turn, call `skill-deploy-install-begin` for the same Skill/repository/commit. That command activates the terminal self-update barrier and returns `INSTALL_TURN_STARTED`. Then invoke `skill-creator`/the native host install surface as the final install action. Do not run Codex Loop again after the native surface is initiated. On a later user/host turn, release the barrier before reconciliation:

```bash
python3 scripts/codex_loop.py skill-deploy-resume \
  --cwd REPO \
  --skill-name codex-loop \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA \
  --later-host-turn-observed \
  --same-conversation-observed \
  --evidence "new user/host turn in the same conversation after native install handoff"
```

`skill-deploy-resume` does not claim UI or deployment success; it only proves that Codex Loop is no longer continuing in the initiating turn. With `--same-conversation-observed`, it returns the exact handoff `routing_session_id`; continue using that id and do **not** call `route-init` again. Fresh exact-scope permission observations remain reusable subject to their TTL and routing generation. In a genuinely new conversation, omit `--same-conversation-observed`, initialize a new routing session, and probe only stale/missing capabilities. After that later-turn resume, if `skill-creator` or an equivalent native host primitive actually exposed/initiated the Skill update surface, record that observation:

```bash
python3 scripts/codex_loop.py skill-deploy-surface-record \
  --cwd REPO \
  --skill-name NAME \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA \
  --surface-kind skill_creator_install_ui \
  --evidence "host visibly surfaced the native Skill install/update control"
```

This advances the same external action to `dispatched` and returns `NATIVE_SURFACE_OBSERVED`, `UI_SURFACED`, and `DEPLOY_PENDING`. `--surface-kind host_managed_update` records `UI_NOT_REQUIRED` for a native update path that does not expose UI. Surface evidence is not deployment evidence.

After host-visible installed-revision evidence is available, finalize:

```bash
python3 scripts/codex_loop.py skill-deploy-complete \
  --cwd REPO \
  --skill-name NAME \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA \
  --evidence "current workspace Skill reports the intended revision"
```

`skill-deploy-complete` refuses a merely planned action; it requires the native surface to have crossed `dispatched` (or a previously dispatched outcome to be reconciled). It then records `terminal_success` and returns `DEPLOYED`.

The native installation/update surface is host-owned. For Skill creation/update tasks, compose with `skill-creator` rather than trying to manufacture a Save/Update control in Codex Loop. Browser automation is never implied. If no native surface is available, leave the action unresolved and report `DEPLOY_PENDING — HOST_SKILL_INSTALL_SURFACE_NOT_OBSERVED`.

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

The canonical root and shared Git repository identity must remain stable for the task. HEAD/branch may move only through the existing Git-mutation workflow. Use Git worktrees for concurrent tasks. Installed Skills are deployment state, are never edited in place, and are **default-off as source acquisition**. Only explicit current-turn user authorization may invoke the read-only installed-Skill copy exception in `references/source-acquisition.md`; current/latest claims still require exact remote equality, and explicitly accepted older/unknown provenance must be labeled honestly. Copied transport/release directories remain non-authoritative.

When Web mode needs source from GitHub, use the exact-revision **Git bundle** workspace-download Actions artifact contract in `references/source-acquisition.md`, restore a real Git repository, and require exact commit/tree equality before binding it. A shell/network inability to run `git clone` in the container is not a reason to invent another source transport. Likewise, inability of one connector query to observe a workflow run must be recorded as an observability limitation, not as proof that the workflow failed or never ran.

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
