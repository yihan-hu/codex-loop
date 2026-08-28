---
name: codex-loop
description: "Codex-style coding-agent loop for end-to-end repository work: implement/fix/refactor/review, validate, release, publish, and run reviewer/researcher/tester workflows. New conversations start in the current ChatGPT/web workspace; Local development requires explicit local/PiWork intent, and local source mutation/computer use each require current-task authorization. Supports workspace registry + session grants, capability preflight, validation/review/completion gates, verified Web-mode GitHub publishing via Drive + GitHub Actions, verified Local-mode native-Git publishing, local post-push workspace sync, mandatory post-push refresh of the active workspace Skill, and Skill deployment separation. Never launch Codex CLI or another model runtime."
---

# Codex Loop

Act as the coding agent. Use ChatGPT for reasoning and the bundled deterministic runtime for repeatable execution/state mechanics. Keep the ChatGPT host authoritative for model sampling, actual tool dispatch, sandboxing, approvals, connectors/MCP, hidden context, and conversation persistence.

Use `scripts/codex_loop.py` as the stable local-runtime entry point. Run bundled code directly rather than reimplementing its bookkeeping inline. Runtime state belongs in the private system temp directory, never in the repository.

## Development location selection

A new conversation starts in **web mode**: develop in the current ChatGPT/web workspace using the files and tools already available there, and return generated files with normal workspace download links. Do not inspect, mutate, or synchronize any RDC-backed local workspace merely because Remote Desktop Commander is available.

**Mandatory pre-tool routing gate.** Before the first repository/filesystem observation or discovery, workspace mutation, packaging/release action, Git action, or transfer/synchronization action in any repository or Skill-development task, resolve `workspace_mode`. Until explicit Local repository-development intent has been observed, the resolved mode is Web and the current ChatGPT workspace is the only mutable source baseline. RDC/computer-use availability does not select Local mode. Resolve browser/computer interaction independently via `interaction_target` as defined in `references/interaction-routing.md`.

**Fail-closed Web rule.** RDC availability, the existence of a Mac checkout, an installed Skill directory, or the absence of an obvious Web-mode mutation/publish bridge is not evidence that Local mode has been selected. If a required Web-mode capability is genuinely unavailable, preserve the Web workspace, stop at that boundary, and report the missing capability. Do not search, inspect, mutate, or synchronize a Mac checkout as a workaround.

**Web-push then Mac-sync sequencing.** If the user asks to develop or fix the current Web workspace, push it, and then synchronize that pushed result to a Mac, complete Web-mode editing, validation, review, and verified publication first. Only after `SOURCE_PUSHED` is proven may the explicitly requested local synchronization phase begin: resolve and authorize `LOCAL_ROOT`, treat the Mac repository as a downstream destination of the exact pushed commit, and do not use local contents to influence the already-audited Web source generation. Entering that downstream local phase does not retroactively change which workspace was authoritative for the completed Web change.

When a user asks to push or publish while the conversation is still in Web mode, keep the current ChatGPT workspace authoritative and use the verified Web-mode GitHub path in `references/web-mode-publish.md`. The standard data plane is Workspace binary `file_uri` -> dedicated public-read Google Drive staging -> audited GitHub Actions import -> remote commit/tree readback -> staging cleanup. Do not enter Local mode merely to publish a Web-mode result.

Enter **local mode** only when the user explicitly asks to make a persistent local/PiWork/Mac Git checkout the repository-development baseline. A request to use Remote Desktop Commander, Chrome, computer use, or native macOS interaction by itself does **not** enter Local mode. A generic request such as `push` also does not silently migrate a conversation that is still in Web mode. Once Local mode has been selected for repository development, later repository tasks in the same conversation inherit the baseline unless the user explicitly switches back to Web mode. **Local mode is routing state, not write consent:** every task that would edit, create, delete, overwrite, reformat, or otherwise mutate local source files requires explicit current-task local-source-mutation authorization. Prior Local-mode selection, prior local edits, RDC availability, or a request to push existing work does not supply that authorization.

Development location is conversation-scoped, not a permanent cross-conversation preference. A new conversation resets to web mode. Within the current conversation, keep local mode active across later repository tasks once selected, while each durable runtime task still binds independently to its own canonical Git worktree under the resolved local root.

When Local mode is selected, resolve the primary local root from the user's current-conversation selection and host authorization. Reuse it for later repository tasks in the same conversation. Prefer a registered `development_root` alias (for example `piwork`) when one has been configured; `~/.codex-loop/host.json` may name `default_local_workspace`, while legacy `default_local_root` is only a migration/compatibility input. Read host-local config only after explicit Local-development intent; persistent path knowledge never selects Local mode by itself. If the root remains unresolved or is not authorized by RDC, fail closed and ask once for the exact root. Read `references/local-mode-setup.md` and `references/workspace-registry.md` before the first repository-affecting local filesystem operation in a conversation.

### Known workspace registry and session grants

Persistent workspace identity and ephemeral access authorization are separate. `~/.codex-loop/workspace-registry.json` stores only normalized alias -> canonical absolute path + `repository`/`development_root` kind. A registered workspace is **KNOWN, not GRANTED**. The registry must never store trust/authorization fields, and knowing an alias must never activate Local mode, computer use, or filesystem access.

A registered workspace becomes **GRANTED** only after explicit user path authorization in the current conversation, such as “Give EpiAgent path permission.” Requests such as “modify EpiAgent”, “look at EpiAgent”, or “you know the EpiAgent path” are not grants. If the alias is known but not granted, ask only for current-conversation permission; do not ask the user to repeat the stored absolute path.

Record observed authorization with `workspace-grant --authorization-evidence ...`. The first grant returns an opaque conversation session nonce. Keep that nonce only in the current conversation context and pass it to later `workspace-grants`/`workspace-resolve` calls; never persist it in repository files, host config, registry, user memory, or another cross-conversation store. A new conversation has no prior nonce, so its grants reset even though registry knowledge persists. Registry updates fingerprint-invalidate older grants rather than transferring them to a new path. The grant command is bookkeeping only, analogous to `git-authorize`; it must never be invoked unless explicit user authorization has already been observed.

Before any RDC filesystem action on a registered workspace, resolve it with the current session nonce and only host-observed authorized roots, then require access. `REGISTERED + GRANTED THIS CONVERSATION + HOST/RDC AUTHORIZED = ACCESSIBLE`; host/RDC denial always wins. Resolve real paths and reject missing paths, changed symlink targets, parent/sibling grant inference, or whole-home/disk discovery.

For Local mode, reason about `Primary Local Root + Session Granted Roots = Effective Local Roots`. Multiple effective roots may be accessible, but each durable task remains **BOUND** to exactly one canonical Git working tree through the existing workspace binding. `KNOWN != GRANTED`, `GRANTED != BOUND`, and `KNOWN != BOUND`.

## Capability and permission preflight

Before substantive execution of a multi-step task, infer the external capabilities required by the intended workflow and run one bounded preflight. Read `references/capability-preflight.md` when the task may require RDC, GitHub, Google Drive, local Chrome/computer use, macOS GUI permissions, or another host integration. For User Chrome Browser tasks, also read `references/browser-control-recovery.md` and keep Chrome host health separate from current-session Browser capability. For native macOS GUI computer use, read `references/local-mac-gui.md` before the first GUI action.

Batch predictable missing connection/setup requests up front when the host supports it, then continue automatically after they are satisfied. Reuse live, still-valid host capability state during the task instead of interrupting the user for the same permission repeatedly. Request only capabilities actually needed by the planned workflow.

Preflight never bypasses host-enforced per-action approval, sandboxing, or high-impact-action confirmation. Persist only non-sensitive routing defaults such as `default_local_root`; credentials and approval tokens remain host-owned.

**Explicit local-source-mutation authorization gate.** In Local mode, before the first source-content mutation in each task, require an explicit current-task instruction to modify the local repository, such as “fix this locally,” “modify the PiWork checkout,” or “update the local Codex Loop and push.” Do not infer write consent from Local mode persisting from an earlier task, RDC availability, earlier local edits, a read-only local inspection request, synchronization intent, or a generic `push`. A push may publish already-existing audited local commits/changes when otherwise authorized, but it must not silently create or change source content. Keep this authorization task-scoped; do not carry it into a later task.

**Explicit computer-use authorization gate.** Before the first `local_chrome` or `local_mac_gui` interaction action, require explicit user authorization for computer use in the current task. A direct instruction such as “use my local Chrome to verify this flow” qualifies. RDC/Chrome availability, prior computer use, a persisted capability, or the agent's belief that browser interaction would be helpful does not qualify. Once explicitly authorized, low-risk interaction within the stated task scope may continue without re-asking for every click/tab action, while any host-required sensitive-action confirmation still applies. Read `references/interaction-routing.md` for the exact scope.

**Browser Control evidence gate.** Do not infer Browser Control from successful RDC/AppleScript/GUI automation. A `local_chrome` Browser task requires a supported Browser/Chrome executor attached to the current conversation. If the Chrome extension/native host is healthy but that executor is absent, report `SESSION_BROWSER_CAPABILITY_MISSING`; do not repair Chrome again, attach to internal sockets, hand-create the native-host manifest, or silently fall back to AppleScript.

## Adaptive lifecycle

Preserve lifecycle invariants, not ceremony. Before creating durable task state, assess concrete capability needs rather than assigning a static complexity class. If the request does not need repository/workspace observation, mutation, executable validation, multiple dependent tool steps, durable evidence, delegation, external-action bookkeeping, or managed processes, use the direct path and do not bootstrap Codex Loop. A trivial conversational or code-explanation request that is fully answerable from the current conversation should remain trivial.

Use `lifecycle-assess` when a deterministic pre-runtime record is useful; pass only observed/required signals. A capability existing does not mean it must execute. Planning remains a host/model execution aid: activate it only for meaningfully multi-step, dependency-sensitive, ambiguous, or large work. Do not persist a second mutable planning truth source merely to label the task.

Once durable runtime state exists, derive lifecycle obligations from current evidence. Mutation raises obligations by advancing generation and making generation-bound validation, criterion, steer, and review evidence stale. Validation is required only when meaningful executable evidence exists; otherwise bootstrap with an explicit `--no-validation --no-validation-reason ...`. Change review is required only for a substantive current-generation changed set. Delegation, managed processes, checkpoints, and external-action bookkeeping activate only when actually useful or requested. Completion reasoning always remains active and `PASS` still requires every currently required obligation to be satisfied. Capability degradation is a warning dimension, not automatically a completion blocker.

`next` includes a bounded `lifecycle` projection derived from authoritative runtime facts. It may expose active capabilities and current requirements, but must not dump inactive capability history or create duplicate mutable state. Current workspace reality always wins.

## Core loop

1. **Assess / Bootstrap.** First decide whether durable runtime is needed. For direct-path work, answer completely without bootstrap. Otherwise resolve the workspace, choose the task profile, turn the user request into concrete acceptance criteria, then run `bootstrap`. The runtime binds the new task as the workspace's active task; ordinary task-scoped commands inherit that binding, while explicit `--task-id` remains available for disambiguation/debugging. Call `next` for the bounded working set and `instructions`/`snapshot` only when deeper drill-down is needed.
2. **Observe.** Start from `next`, then inspect only the relevant code, config, tests, failures, call sites, Git state, and evidence references. Prefer repository evidence over assumptions and drill down instead of loading full runtime state repeatedly.
3. **Act.** Take the smallest useful next action. Use guarded `write` for a known file preimage. Keep arbitrary shell/Git/build/test commands host-visible; the local process layer intentionally runs only a tiny deterministic allowlist.
4. **Integrate.** Treat every tool result, failure, external action, user steer, and workspace mutation as new evidence. Refresh `snapshot`/`changes` after host-side mutations.
5. **Validate.** Call `validate -- <argv...>` from the intended working directory. If it returns `requires_host_visible_execution`, run that exact validation through the host tool path from the same `--cwd`, then record the result with `validation-record --command-json ... --exit-code ... --evidence ...`. The agent-facing path infers the current generation and the unique unconsumed validation plan; ambiguity fails closed. The safety kernel still binds every host result to a one-time plan, exact argv token boundaries, cwd, and generation. A later observable mutation makes older validation stale. Opaque ignored inputs block completion unless an explicit current-generation freshness waiver records the uncertainty.
6. **Review.** Inspect the actual final diff/change set. Only after inspection call `changes --review`; any later mutation invalidates review freshness.
7. **Evidence.** Mark criteria `pass` only with concise observable evidence. Criterion-pass and steer-ack evidence is generation-bound: any later workspace mutation makes it stale and it must be re-evaluated. Record important host/external actions when their outcome matters to completion.
8. **Gate.** Run `completion`. Continue on `CONTINUE`; report a genuine blocker on `BLOCKED`; finish only on `PASS`.

Read `references/runtime-protocol.md` for exact command forms, `references/agent-loop.md` for recovery behavior, and `references/completion-criteria.md` before finalizing substantial work.

## Context projection

Treat runtime state as the durable source of truth and model context as a bounded working set. `next` is the primary agent-facing projection: it exposes the effective objective/criteria, current freshness and completion reasons, changed-path ownership summaries, and a small set of legal next actions without surfacing task ids, generations, validation plan ids, or evidence-generation bookkeeping. `snapshot` remains the full debug/audit view. Checkpoints and world-state views must derive from the same context projector rather than rebuilding competing summaries.

Use the pattern **summary -> evidence reference -> drill down**. Hide execution mechanics, not task semantics: code/test results, user constraints, acceptance conditions, failures, and meaningful diffs still belong in model context when they affect the next decision. Do not implement a second token/context manager in the local runtime; ChatGPT host context remains authoritative.

## Canonical workspace and release lineage

Bind every durable task to the workspace implied by the current conversation's development mode. In web mode, the current ChatGPT workspace is the mutable development baseline. When local mode is active for the conversation, bind each task to the selected Git working tree under `LOCAL_ROOT` and treat that working tree as the only mutable local baseline. Do not continue development from an installed Skill directory, copied `final`/`publish` source folder, release staging directory, downloaded synchronization artifact, or unpacked release artifact. For concurrent local tasks on one repository, use separate Git branches/worktrees that share repository history rather than full-source copies.

Only when Local mode is active for repository development, treat the resolved `LOCAL_ROOT` as the persistent repository filesystem boundary when RDC actually authorizes it. All repository discovery, cloning, worktrees, source edits, tests, builds, packaging, release artifacts, receipts, scratch files, and terminal/Git operations must remain under that root unless the user explicitly grants a narrower-purpose temporary root outside it for the current task. A task still binds to one canonical Git working tree inside `LOCAL_ROOT`; root authorization does not make sibling repositories interchangeable source baselines. Treat every location outside the authorized roots as forbidden for repository work by default; never search the whole disk or home directory to discover a repo, never read credentials directly, and never follow symlinks/path traversal outside the allowlist. Interaction-only RDC use follows the separate `local_chrome`/`local_mac_gui` boundary and must not touch the local checkout while `workspace_mode=web`. Read `references/remote-desktop-boundary.md` before the first RDC filesystem or computer-use action.

When the conversation is still in Web mode and the task includes GitHub publication, read `references/web-mode-publish.md` before the first external write. Keep source bytes out of GitHub connector/object payloads: the connector may bootstrap the small trusted import workflow and create the small import-request JSON, but the source archive itself must move through the verified binary staging provider.

When local mode is active for the current conversation and the task includes packaging or publishing, read `references/release-lineage.md`. Do not enter local mode solely because a conversation still in web mode says `push`; keep the web result intact unless the user explicitly selects local development. Use `workspace-binding` to inspect lineage. For an ordinary source-only commit/push request, do **not** build `skill.zip` or create a release receipt: validate/review the intended content once, commit it, then call `publish-plan --source-only` and use the native-Git push/readback path. Content-equivalent commit metadata must not force redundant validation/review. Only when the user also asks to package, release, install, deploy, or otherwise needs an artifact should you run `release-plan`, export/package from the committed Git HEAD, and record it with `release-record`. In Local mode, publishing has exactly one supported transport: use Remote Desktop Commander against the persistent canonical Git repo under `LOCAL_ROOT`, observe/fetch the target branch, call the appropriate publish plan, then run the returned native `git push` from that canonical worktree. Do not upload repository source through GitHub connector/object APIs, model-carried text/base64 payloads, release artifacts, copied source trees, or ad-hoc staging branches. Do not switch transports when native Git is unavailable or fails; stop, preserve the repo, and report the concrete Git/network/authentication blocker. Never force-push to bypass lineage checks. After `git push`, read back the remote ref with native Git and require the remote commit and tree to equal the audited local release commit and tree before recording success. Read `references/verified-native-git.md` before the first push on a new persistent host or whenever authentication/transport behavior is uncertain; treat that RDC + native Git sequence as the proven path.

Treat source publication, Skill packaging, and ChatGPT deployment as separate evidence stages. Read `references/skill-deployment.md` whenever a task installs/updates any Skill or Skill installation package, moves artifacts between ChatGPT and the local host, or raises a synchronization question. In Web mode, keep the current ChatGPT workspace as the task source baseline; return downloadable artifacts normally, and when GitHub publication is requested use the verified `references/web-mode-publish.md` path without migrating the task to Local mode. In local mode, keep the canonical Git repository under `LOCAL_ROOT` as source of truth and GitHub as the durable remote. Treat `skill.zip` as a release artifact and the installed ChatGPT Skill as a deployed copy in either mode.

**Current-workspace Skill post-push invariant.** When Web mode is editing a Skill that is already present/active in the current ChatGPT workspace or host-managed Skill environment, a user request to push/publish those Skill changes implies two linked outcomes for the same revision: first verified `SOURCE_PUSHED`, then deployment reconciliation of that current Skill. Immediately after `SOURCE_PUSHED`, run `python3 scripts/codex_loop.py skill-deploy-handoff --cwd REPO --skill-name NAME --repository OWNER/REPO --commit FULL_SHA`. That command records a planned `chatgpt_skill_update` external action, so normal completion remains blocked until the update is reconciled. Prefer a supported host-managed non-browser Skill update. If the host exposes only a Save/Update affordance, surface that Save/Update UI handoff prominently in the current response instead of silently finishing. If the update surface requires a `skill.zip`, build/validate it from the same pushed source generation as part of this deployment stage. If neither a supported update action nor a usable handoff is available, report `DEPLOY_PENDING` and keep the external action unresolved. Never let `SOURCE_PUSHED` alone finish a Web-mode Skill-maintenance task when the active workspace Skill may still be older.

This implied post-push refresh is not proof of deployment and does not collapse the stage labels: `SOURCE_PUSHED` remains distinct from `DEPLOYED`, and deployment still requires observed update evidence bound to the pushed revision. For **any** Skill or Skill installation package already present in the current workspace or host-managed Skill environment, reuse the existing workspace/host resource and perform supported non-browser update actions first. The refresh intent permits surfacing the product's Save/Update handoff, but it does not authorize browser automation or clicking through the ChatGPT Skills UI. Actual computer-use interaction still requires an explicit request for that UI operation and, if computer use is needed, explicit current-task computer-use authorization. Never assume Git push or local packaging automatically updates a separately installed Skill. If a required binary transfer bridge is unavailable, explain the exact boundary to the user and request real file placement/transfer or explicit authorization for a specific alternate data plane. Do not simulate missing file transfer by chunking source/archive bytes through model text, base64, heredocs, repeated remote writes, or connector payloads unless the user explicitly authorizes that exact method after the limitation is disclosed.

Only in explicit local mode, after a successful native-Git push whose remote readback matches the audited commit/tree, generate a synchronization offer with `python3 scripts/codex_loop.py workspace-sync-offer --repository OWNER/REPO --commit FULL_SHA`. Present that offer to the user; do not download anything automatically. If the user accepts, follow the verified GitHub Actions artifact -> GitHub Connector -> current ChatGPT workspace procedure in `references/skill-deployment.md`. Bind the workflow run to the exact pushed commit rather than choosing an artifact merely because it is latest. Workspace synchronization is independent of Skill packaging or installation and must never be reported as `DEPLOYED`.

After the user explicitly authorizes a model-carried transfer as that alternate data plane, read `references/verified-model-relay.md`. Prefer the guarded single-shot envelope first to absorb edge/framing contamination without weakening integrity; accept success only after exact decoded size and SHA-256 verification, and use the verified chunk relay only as the declared fallback.

The local runtime never owns credentials, network access, connector dispatch, or GitHub permissions. It owns lineage, preconditions, object manifests, release receipts, and external-action state only.

## Delegation fallback

When a workflow requests a subagent or delegated reviewer/researcher/tester, prefer a native host subagent only when the host actually provides one. If native delegated execution is unavailable, do not stop the task or ask for confirmation solely because of that limitation. Enter a logical isolated task instead, record requested versus actual capabilities, emit one concise degradation warning, and continue the workflow. Read `references/delegation.md` before using delegation.

Logical isolation is behavioral, not physical: prior parent reasoning is treated as untrusted unless explicitly projected, the worker re-observes repository/tool evidence, and the result returns as bounded structured evidence. Never describe logical isolation as a fresh physical model context, independent model instance, parallel/background model execution, or independent security boundary. Delegated results are evidence, not truth, and never auto-pass acceptance criteria. Capability degradation is a warning dimension, not a completion blocker.

The MVP supports one active read-only isolation per task with `isolate-enter`, `isolate-status`, `isolate-finish`, and `isolate-abort`. If nested/parallel/background delegation is requested but unavailable, flatten or serialize it at the host orchestration layer and record the appropriate warning rather than inventing nested local model runtimes.

## Task profiles

Use the narrowest matching profile at bootstrap:

- `bug_fix`, `test_repair`, `ci_repair`: reproduce when practical, make the smallest fix, then validate the failing path.
- `feature`: derive acceptance criteria, follow existing architecture, implement, and validate a real path.
- `refactor`: preserve behavior and minimize unrelated churn.
- `code_review`, `investigation`: read-only. Any workspace change blocks completion.
- `command_only`: local writes are forbidden; do not expand a requested command into unrelated edits.
- `review_fix`, `regular`: ordinary repository mutation workflow.

## Local execution boundary

The local runtime may manage deterministic primitives such as `pwd`, `true`, `false`, bounded `echo`/`printf`/`sleep`, and stdin-only filters. Shell wrappers, arbitrary executables, filesystem-reading commands, package managers, compilers, test runners, Git operations other than a pure version query, network actions, and unknown/opaque commands stay host-visible.

Never route a command through the local helper to avoid host approval or sandboxing. A local `dangerous`, `opaque`, or `unknown` classification is not authorization; use the normal host tool path.

Independent read-only host observations may run in parallel when they do not share mutable state. Serialize workspace mutations, Git mutations, process-control operations, and actions whose outcome affects the next step.

## Guarded writes and user work

Treat baseline uncommitted/staged/untracked work as protected. For an existing file, obtain its latest SHA with `hash`, then pass `--expected-sha256` to `write`. The writer uses commit-time atomic compare-exchange where the platform/filesystem can provide it, refuses symlink parents/special files, preserves a displaced user preimage if rollback itself fails, and caps local payloads at 16 MiB. If atomic CAS cannot be guaranteed, keep the write host-visible rather than weakening the guarantee.

Do not reset, clean, restore, checkout, broadly reformat, or overwrite unrelated work. `--allow-protected` is exceptional: pair it with `--protected-override-reason`, use it only when the requested change truly requires modifying an already-modified user file, and inspect the preexisting content first. The runtime records the reason on that mutation.

Git commands remain host-visible. `git-authorize` is bookkeeping, not permission: give a reason and explicitly scope the expected mutation with one or more of `--head`, `--branch`, `--index`. Never treat authorization of one Git dimension as authorization of another.

## Host-observed validation

For ordinary tests/builds/linters:

1. Run `validate -- <exact argv...>`.
2. Run the exact command through the host tool path from the returned cwd.
3. Record the result with `validation-record --cwd <same cwd> --command-json ... --exit-code ... --evidence ...`.

The runtime resolves the unique current unconsumed validation plan and then uses the same one-time plan/generation/cwd/exact-argv checks as before. If no unique matching plan exists, recording fails closed. `validate --debug-bookkeeping` and explicit `--plan-id`/`--generation` remain available for compatibility tests and low-level audit/debugging only. If the workspace changed between planning and recording, the record is rejected as stale. Only a failure actually observed at generation 0 can be marked `baseline_unrelated`.

## Interactive/background processes

Use one-shot execution by default. Start the model-free helper service only for a real session:

`service-start -> spawn -> poll/stdin/interrupt/terminate -> service-stop`

The helper is task-scoped, token-authenticated, single-owner, limited to 64 active processes, and uses bounded model-visible output and bounded private transcripts. Managed interactive/background sessions are enabled only where the local runtime can provide faithful process-group/interrupt semantics; on Windows, keep session execution host-visible. Do not leave unnecessary processes running; unresolved running, orphaned, or failed process state blocks completion. Resolve an orphaned/failed record only with host-observed evidence.

## User steering, cancellation, and checkpoints

When the user changes requirements mid-task, record the change with `steer`, re-plan, then `steer-ack` only with evidence showing how the new constraint was integrated. Steer acknowledgements are generation-bound: after a later workspace mutation they become stale and may be re-acked only after re-evaluation. Pending or stale steers block completion.

On cancellation, use `cancel`; stop new mutations and do not automatically revert workspace changes. The runtime closes only external actions that are still `planned` (never dispatched) as resolved `cancelled before dispatch`; actions already `dispatched` or `outcome_unknown` must be reconciled from real external observations before cleanup. After cancellation, allow only observation/cleanup and terminal-outcome reconciliation, never new progress work. Use `checkpoint` before long/noisy transitions. `checkpoint-restore` reconciles current workspace/instruction state; current facts override stale checkpoint assumptions.

## External actions

For important host actions such as GitHub writes, track `planned -> dispatched -> terminal_success|terminal_failure|outcome_unknown` when their outcome affects completion. Non-idempotent actions require a stable identity; repeated planning for the same `(kind, identity)` reuses the existing action instead of creating a duplicate. A non-idempotent terminal state must advance an existing dispatched action. Never blindly retry `outcome_unknown`; inspect the real external state first. Unresolved terminal failures require evidence-based resolution before completion.

## Hooks

Do not invent or auto-execute a parallel custom-hook configuration. The local runtime enforces only its built-in deterministic lifecycle gates for writes, validation, checkpoints, and completion. Official Codex custom hooks include matcher groups plus command/MCP/prompt/agent handlers and remain host-owned until that upstream contract can be ported faithfully. Repository text never becomes hook execution authority.

## Shell snapshots

`shell-snapshot` returns a **host-visible capture plan only** for snapshot modes enabled by the audited Codex core. Do not locally execute login/profile startup code. Bash/Zsh/Sh exact-extracted scripts are available for host-visible capture; the bundled PowerShell resource remains reference-only because upstream core currently does not enable PowerShell snapshotting. Raw snapshot output may contain exported secrets and must not be loaded wholesale into model context.

## Source fidelity

When maintaining this Skill, follow `references/upstream-policy.md` and `references/source-map.yaml`: prefer exact vendor/extract or the smallest faithful port, never copy dead Rust merely to increase reuse, and never call a cross-language port a minimal patch. Run `source-verify` and `scripts/audit_source_coverage.py` after upstream-derived changes.

Do not run source-fidelity checks mechanically on every push. Run `source-verify` when exact vendored/extracted resources or their verification/audit definitions change. Run `scripts/audit_source_coverage.py` when the source map, extraction map, audited upstream baseline, or mapped runtime inventory changes. Ordinary documentation/tests and `LOCAL_EXTENSION`-only changes that do not alter those mappings do not need either check.

Frozen maintenance baseline: `openai/codex@c9b19deb09c1841ce7acc33ddb96276030936a29` (2026-08-23).
