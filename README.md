# Codex Loop

Codex Loop is a ChatGPT Skill that gives every selected objective one lightweight Codex-style lifecycle while keeping ChatGPT as the host for reasoning, tools, approvals, connectors, and conversation state.

Selection always requires lifecycle admission. For a new objective, lifecycle bootstrap is the first task action; if the host cannot enter the runtime, Codex Loop fails closed instead of silently running the objective outside the lifecycle. Simple work stays lightweight because plans, workspace binding, checkpoints, persistence, extra review, managed processes, and external-action bookkeeping are activated only when needed—not because the lifecycle itself is optional.

## Runtime control plane v2

Codex Loop separates repeatable control-plane mechanics from host/model reasoning. The current runtime adds coordinated surfaces for **Execution Outcome Separation** (`workload != process != cleanup`), a unified **Private Host Profile** with Cloud-Browser-first interaction preference, deterministic **Durable Resume**, and split Skill distribution profiles: repository-neutral consumer packages plus explicit maintainer provenance packages. These are thin ChatGPT-host adaptations; existing upstream host gaps remain explicitly labeled rather than being promoted to false parity.

Key references: `references/execution-supervision.md`, `references/host-profile.md`, `references/persistence-resume.md`, and `references/deployment-provenance.md`.

## Consumer quick start

For normal use in ChatGPT, install Codex Loop and start using it. **You do not need GitHub, Google Drive, RDC, a local checkout, or access to `yihan-hu/codex-loop`.** The maintainer repository is not a consumer repository binding.

Add integrations only when the task needs them:

- GitHub: repository reads/source acquisition/Actions/publication.
- Google Drive: verified binary staging for Web -> GitHub publication and Web -> local/Mac synchronization. First-time use needs a dedicated staging folder with the temporary read policy required by the receiving host/workflow.
- Remote Desktop Commander: only for local files, native Git, local Chrome, or macOS GUI interaction.

See `references/consumer-onboarding.md` for the staged setup checklist and exact permission boundaries. Codex Loop should disclose only the dependencies required by the current task and can preflight those capabilities before substantive work.

## What it can do

Use Codex Loop for objectives such as:

- staged research or analysis that moves from evidence gathering to synthesis, drafting, and audit;
- scientific or long-form writing workflows where source fidelity, revisions, and completion criteria must survive several stages;
- document, slide, spreadsheet, and other artifact workflows that include build, render/inspect, QA, and export;
- cross-tool operational work where later actions depend on earlier observed state;
- implementing features and refactors;
- fixing bugs, tests, and CI failures;
- investigating or reviewing a codebase;
- running repository-native validation;
- tracking acceptance criteria and review freshness;
- remembering stable local workspace aliases without turning remembered paths into standing access permission;
- keeping repository `workspace_mode` independent from browser/computer `interaction_target`;
- controlling a user's local Chrome through a supported Browser/Chrome bridge attached to the current conversation, with separate host-health and session-capability recovery;
- resolving GitHub/Drive permissions only when the objective reaches a side-effect boundary that needs them;
- publishing Web-mode workspace source through verified Drive staging + GitHub Actions, or Local-mode source through native Git;
- packaging ChatGPT Skills;
- packaging an updated Codex Loop workspace into an official validated `skill.zip`, then exposing the same bytes as `codex-loop.zip` through a fresh current-conversation artifact;
- synchronizing a verified local GitHub commit back into the current ChatGPT workspace;
- degrading requested reviewer/researcher/tester delegation to a bounded logical isolation when native subagents are unavailable.

Codex Loop is not Codex CLI and does not contain a model runtime. ChatGPT remains the execution host.

## Install as a ChatGPT Skill

This repository is the Skill source. Codex Loop does not install or update itself.

After any Codex Loop source update, finish validation/review and produce a complete official validated `skill.zip`. If the user also requested publication, prove the source push first, then package the updated workspace. Copy the finished `skill.zip` byte-for-byte to `codex-loop.zip`, verify the SHA-256 is unchanged, and expose that exact `codex-loop.zip` as a **fresh current-conversation download artifact**. Do not use a presumed Library object or reuse an old attachment/reference.

The user installs or replaces the Skill manually through `Plugins -> Plugin Directory -> Skills -> Create -> Upload from your computer`. `SKILL_PACKAGED` proves the archive bytes; a downloadable artifact requires a current host-provided file reference, and neither one proves installation.

## Quick start

Codex Loop is designed for **implicit invocation**. In normal use, you should not need to type `@Codex Loop` or name the Skill. Once selected, lifecycle admission is mandatory: after the Skill entrypoint is loaded, a new objective bootstraps before any substantive task action and keeps the returned `task_id` authoritative across continuation. If the host cannot invoke the runtime entrypoint, Codex Loop fails closed rather than silently continuing as ordinary chat/tool execution. Planning, workspace binding, validation bookkeeping, delegation, checkpoints, cross-chat persistence, and managed-process machinery remain lazy and activate only when the objective needs them.

Short follow-ups such as `continue`, `继续`, `revise`, `verify`, `export`, `push`, `sync`, or `open this in Chrome` continue the existing lifecycle when the active objective is clear. A continuation first inspects the retained lifecycle state and current external reality; it does not create a replacement lifecycle or redo completed work. Automatic invocation does **not** bypass permissions: side-effect permissions are resolved when the task actually reaches that boundary.

For repository or Skill-development requests, **Web mode** is the default development location in every new conversation. Pure research, writing, analysis, artifact, or operations objectives do not need Web/Local repository routing unless a later step actually becomes development-location-sensitive.

**Recommended path:** keep ordinary repository development in the ChatGPT/chatbox workspace and connect that Web workspace to GitHub when publication is needed. This is usually faster and simpler than Local mode because it avoids the extra RDC hop, host-filesystem authorization, native-Git host state, and local-host-to-workspace synchronization steps.

Repository work now enters through `repository-enter`: **HOT -> WARM -> COLD**. If the existing real Git workspace is still valid, Codex Loop reuses it directly and ordinary edit/commit/push remains incremental. If the temporary workspace disappeared, Codex Loop restores a verified Workspace Cache (when unpublished state was explicitly preserved) or the `published-source-<run_id>` Git bundle emitted by the last successful Web publish. Only when neither HOT nor WARM Git state exists does it enter the cold Workspace Download/source-acquisition path. Remote HEAD movement means incremental fetch/fast-forward/rebase/merge, not “download the repository again.”

For Skill maintenance, normal source choices are user upload, Google Drive, or GitHub. An installed Skill is deployment state and is **not** an automatic source fallback. It may be copied read-only into a fresh workspace only when you explicitly tell Codex Loop to use that installed copy as source in the current conversation; current/latest claims still require exact remote equality, while an explicitly accepted older revision is labeled historical rather than silently upgraded.

Example prompts (explicit Skill naming is optional):

```text
Review these papers, synthesize the evidence, draft the grant section, and audit it against the sources.
Turn this outline into a slide deck, render it, inspect the output, and fix layout issues.
Analyze this spreadsheet, build the requested model and charts, then verify the final workbook.
Fix this bug and run the relevant tests.
Push the current workspace to GitHub and verify the remote commit.
Use my local Chrome to verify this signed-in flow.
```

You do not need Remote Desktop Commander for ordinary Web-mode repository work. However, Web mode may still use RDC for **interaction-only** tasks such as controlling your local Chrome or macOS UI; that does not move the repository source of truth onto the Mac.

If you ask to push, Codex Loop intercepts the publication intent before literal Git, resolves Web versus Local, then uses the selected mode's canonical path. Web mode uses the verified Google Drive -> GitHub Actions exact-identity path. Local mode uses native Git from the bound worktree plus exact remote commit/tree readback. Ordinary target repositories do not need to contain Codex Loop runtime files. If Codex Loop itself was edited, a successful requested source push is followed by packaging the updated workspace into the official validated `skill.zip` and byte-identical `codex-loop.zip`.

**Local mode is a first-class mode after explicit user selection.** Use it when a task genuinely needs persistent files or tools on an RDC-backed computer, or when you deliberately want that local checkout to be the repository source of truth. macOS is the verified reference host. Windows repository Local mode is also allowed on a best-effort/beta basis: unsupported Windows-specific primitives degrade to host-visible execution or fail only the affected operation. For ordinary development Local mode is usually slower than the Web workspace + GitHub path because each task can add RDC and permission checks, native-host coordination, and extra push/synchronization round trips.

To enter **Local mode**, explicitly select it:

```text
Use local development for this repository.
Use Codex Loop locally under /Users/alice/PiWork and fix this bug.
Use Codex Loop locally under C:\Users\Alice\PiWork and fix this bug.
```

Once Local mode is selected, later repository tasks in the same conversation keep using that local repository as the baseline unless you explicitly switch back to Web mode. **That does not carry forward permission to modify local source.** Each task that would edit/create/delete/overwrite local source files must explicitly authorize local mutation again, for example: `Fix this locally and push.` A generic `push`, read-only inspection, RDC availability, or earlier local edits do not authorize new source changes. A new conversation starts in Web mode again.

## Adaptive progress visibility

Codex Loop increases user-visible progress for substantive multi-step objectives by default so a long Web task does not look stalled. The built-in enhanced policy uses an approximate **15-second / 3-substantive-tool-call** cadence (whichever comes first), plus immediate concise updates for material findings or blockers. Lightweight tasks remain low-noise. This is host-facing guidance: ChatGPT owns actual message timing and tool dispatch.

The preference is user-specific and is never committed. `python3 scripts/codex_loop.py progress-config` shows the effective values; `progress-config --mode enhanced --interval-seconds 20 --tool-call-interval 4` writes overrides atomically to `~/.codex-loop/host.json` (or `CODEX_LOOP_HOME/host.json`). The supported modes are `enhanced`, `standard`, and `quiet`; upfront planning and material-event updates can be toggled independently. `progress-config --reset` removes only the progress override and returns to built-in defaults. See `references/progress-visibility.md`.

The host config is private runtime state outside the repository and outside `skill.zip`. It may coexist with non-sensitive workspace locators/preferences, but it does not store current `workspace_mode`, `interaction_target`, or `deployment_target`; those live in the conversation routing file. Host config must never contain credentials, approval/session tokens, or other secrets.

## Optional cross-conversation persistence

Web conversations and ephemeral workspaces are not a durable storage contract. Codex Loop therefore separates two optional, default-off Drive recovery layers. `state_only` stores a small schema-whitelisted lifecycle/reconciliation manifest. **Workspace Cache** stores an immutable 7-day Git/worktree capsule so a later conversation can restore the actual development workspace.

`python3 scripts/codex_loop.py workspace-cache-create --cwd REPO --repository OWNER/REPO --output /PRIVATE/TEMP/workspace-cache.tar.gz` preserves the exact HEAD commit/tree plus staged, unstaged, and non-ignored untracked state. It excludes ignored build/runtime material, Git config/hooks, and credentials. Upload the returned binary privately to `Codex Loop/.runtime/workspace-cache` through the Drive connector.

On restore, verify the externally retained capsule SHA-256, run `workspace-cache-validate`, restore into a fresh directory with `workspace-cache-restore`, and require exact HEAD/tree + state fingerprint before binding the new workspace. After success, upload the small consumed receipt and delete the exact capsule. If deletion fails, the restore remains successful and cleanup becomes `CACHE_CLEANUP_PENDING`; every later cache create/list/restore operation opportunistically scans only the bounded cache folder and retries cleanup of consumed or >=7-day exact owned objects. Consumed cache IDs are excluded from automatic restore selection even when their capsule could not be deleted.

State-only manifests retain their separate TTL/reconciliation rules and always resume into a new freshness domain. Drive is recovery transport, not a second mutable truth source. See `references/persistence.md` and `references/persistence-resume.md`.

## Architecture fidelity governance

Codex Loop tracks not only source lineage but also behavioral/control-plane alignment with upstream Codex. `references/architecture-fidelity.yaml` records watched upstream surfaces and whether Codex Loop is aligned, partial, host-gapped, or intentionally divergent, together with the degradation and upgrade path. Upstream audits review **Source Delta + Control-plane Delta + Concept Delta**; unresolved `NEEDS_REVIEW` entries fail the audit. The governing rule is semantic parity before implementation parity.

## Local mode requirements

Local mode requires a connected **Remote Desktop Commander (RDC)** integration because ChatGPT needs a host-authorized bridge to the persistent filesystem and native Git installation on your computer. The end-to-end verified reference path is macOS + RDC + native Git. Windows + RDC + native Git is explicitly allowed as a best-effort/beta repository host even before full parity testing; Windows-only gaps must be surfaced per operation instead of rejecting Local mode globally.

Choose one absolute directory to be your persistent local workspace root. Codex Loop calls this `LOCAL_ROOT`. For example:

```text
/Users/alice/PiWork
C:\Users\Alice\PiWork
```

`LOCAL_ROOT` is a runtime placeholder, not a path baked into the distributed Skill and not necessarily an operating-system environment variable. Configure that directory as an allowed directory in RDC. You may provide it when selecting Local mode, or persist a non-sensitive default in `~/.codex-loop/host.json` so later conversations can reuse it after you explicitly choose Local development.

A persisted root does **not** make new conversations start in Local mode. New conversations still start in Web mode; the host-local default is consulted only after explicit Local repository-development intent.

You should not edit the Skill to replace another user's home directory. Different users can choose different roots.

Keep repositories, worktrees, scratch data, and release staging that Codex Loop operates on inside `LOCAL_ROOT`. Paths outside it require separate explicit authorization.

See `references/local-mode-setup.md` for the exact agent-side resolution and safety contract.

## Setting up Local mode

1. Connect Remote Desktop Commander to ChatGPT and authorize your chosen `LOCAL_ROOT` directory.
2. Put or clone the repositories you want Codex Loop to edit under that root.
3. In a new ChatGPT conversation, explicitly select Local mode and provide the root if it has not already been established, for example: `Use local development under /Users/alice/PiWork.` or `Use local development under C:\Users\Alice\PiWork.`
4. Codex Loop binds each repository task to one canonical Git working tree under that root. It does not treat copied archives, installed Skills, or release staging folders as later development baselines.
5. If you want to push to GitHub, make sure native Git on the RDC host is authenticated. The verified path uses native Git and remote commit/tree readback; credentials remain host-owned.

For GitHub CLI authentication, an interactive setup can use:

```bash
gh auth login --web --git-protocol https
```

Do not paste tokens or credentials into ChatGPT. Let Git, `gh`, the OS credential helper, or the host integration consume them normally.

If `LOCAL_ROOT` is missing or RDC has not authorized it, Local mode fails closed instead of guessing another directory. On Windows, prefer host-visible PowerShell/native Git for shell and Git actions. Managed interactive/background sessions remain host-visible, and guarded replacement of an existing file may use RDC's host-visible file/edit path when the bundled atomic compare-exchange primitive is unavailable; re-observe the resulting file hash/change set afterward rather than weakening the guarded-write guarantee.

### Remembering `LOCAL_ROOT` across conversations

Codex Loop now prefers a **Known Workspace Registry** for stable local paths. The registry lives at `~/.codex-loop/workspace-registry.json` on the host. Register a development root once:

```bash
python3 scripts/codex_loop.py workspace-register \
  --name piwork \
  --path "/absolute/path/to/PiWork" \
  --kind development_root
```

Then `~/.codex-loop/host.json` can remember only the preferred alias:

```json
{
  "schema_version": 1,
  "default_local_workspace": "piwork"
}
```

Older installations may still contain `"default_local_root"`. Codex Loop treats that as a compatibility/migration input after you explicitly choose Local mode; it does not itself select Local mode or grant access. Register the path as `piwork` and prefer `default_local_workspace` afterward.

The host-local config and registry are deliberately outside every repository and outside the packaged Skill. Git commits, GitHub pushes, Web-mode Git bundles, and `skill.zip` must not include them. Do not put tokens, passwords, cookies, OAuth credentials, approval state, or session-grant nonces in either file.

### Remembering local workspaces without permanent access

You can register a frequently used repository once:

```bash
python3 scripts/codex_loop.py workspace-register \
  --name epiagent \
  --path "/absolute/path/to/EpiAgent" \
  --kind repository
```

That makes the workspace **KNOWN**, not authorized. In a later conversation you can simply say:

```text
Give EpiAgent path permission.
```

Codex Loop records that explicit grant only for the current conversation. You do not need to paste the absolute path again. A new conversation keeps the alias/path knowledge but starts with no usable grants.

The three states stay separate:

```text
KNOWN    I know where the workspace is.
GRANTED  This conversation may use that exact registered workspace.
BOUND    The current lifecycle uses one canonical Git working tree.
```

A request such as `modify EpiAgent` does not by itself grant the path. If the alias is registered but not granted, Codex Loop asks for current-conversation path permission instead of asking for the path again. Host/RDC authorization is still required after the semantic grant, and host denial always wins.

For Local mode, the access model is `Primary Local Root + Session Granted Roots = Effective Local Roots`. Multiple roots can be accessible in one conversation, but each task still binds to one canonical Git working tree. See `references/workspace-registry.md`.

## Workspace mode versus interaction target

Codex Loop treats **where the repository lives**, **which computer/browser is being controlled**, and **where a Skill should be deployed** as separate axes. These values live in a private conversation-scoped routing JSON file created by `route-init`, rather than being reconstructed from long conversation context:

```text
workspace_mode:      web | local
interaction_target:  none | cloud_browser | local_chrome | local_mac_gui
deployment_target:   unresolved | artifact_only | chatgpt_web_skill | local_codex_skill
```

A new routing session starts with `workspace_mode=web`, `interaction_target=none`, and unresolved deployment target. In ChatGPT Web, initialize with `python3 scripts/codex_loop.py route-init --host-surface chatgpt_web`. Before a repository, browser/computer, installation, or publication host action, use `route-check`; local/cross-surface changes go through `route-transition` only after host-observed current-user selection, recorded with `--current-user-selection-observed` plus audit evidence. Evidence text alone cannot switch the file-backed route. Current-task permissions are not persisted by the routing file.

For example, `workspace_mode=web` plus `interaction_target=local_chrome` means the repository remains in the current ChatGPT workspace while ChatGPT uses your Mac only to interact with your signed-in local Chrome. Using RDC for that interaction does not make the Mac checkout authoritative.

Likewise, `workspace_mode=web` does not by itself determine installation destination. A bare Skill `install` on `host_surface=chatgpt_web` deterministically targets `chatgpt_web_skill`; selecting `local_codex_skill` from that host requires an explicit deployment transition, and the actual local install still requires current-task authorization. This prevents Mac/RDC history from becoming an accidental deployment instruction.

For `local_chrome`, Codex Loop keeps ChatGPT as the reasoning authority and does not launch a local Codex agent. Browser Control requires an official/supported host-exposed Chrome/Computer Use executor or native bridge that is actually attached to the current conversation. RDC/AppleScript, Chrome `execute javascript`, generic screenshot/mouse/keyboard automation, and private Browser/Codex sockets are not Browser Control fallbacks and must not be reported as Browser capability success.

**Computer use is opt-in per task.** Codex Loop must not interact with local Chrome or the macOS GUI until you explicitly authorize computer use for that task, for example: `Use my local Chrome to verify this signed-in flow.` A connected RDC/Chrome session, prior computer-use success, or the agent deciding that browser interaction would be useful is not authorization. Once authorized, low-risk actions within that task scope can continue without asking before every individual click/tab action; host-required sensitive confirmations still apply.

Codex Loop distinguishes `browser_host_health` (Chrome, extension, native host) from `browser_session_health` (whether this conversation has a callable Browser executor). A healthy host with no attached executor is `SESSION_BROWSER_CAPABILITY_MISSING`, not a broken Chrome installation. See `references/browser-control-recovery.md`.

### Native macOS Computer Use (`local_mac_gui`)

For native macOS UI tasks, `local_mac_gui` is a separate explicitly authorized Computer Use path. It does not require Mac Codex and does not change `workspace_mode`: a Web-workspace task can use the Mac GUI for interaction while source remains in the ChatGPT workspace.

The verified control pattern is **semantic target -> dynamic geometry -> real mouse event -> independent readback**. Codex Loop prefers Accessibility (`AXRole`/`AXIdentifier`) to locate the intended control, derives click coordinates from the element's live position/size, dispatches the minimum CoreGraphics mouse move/down/up event when a real click is needed, and then verifies the resulting application state through Accessibility or another structured surface. It restores transient cursor/focus state after smoke tests when practical. Global keystrokes are a last resort and require freshly verified target focus.

A Calculator smoke test verified this end to end: resolve `AllClear`/`Two`/`Add`/`Equals` from the live Accessibility tree, click `AC -> 2 -> + -> 2 -> =` with real mouse events, then read back `4` from Calculator's current result view. The coordinates are intentionally not part of the contract and must be resolved dynamically each time.

This path is **not Browser Control** and does not satisfy Browser capability checks. It must not be used to disguise a missing Browser executor. Silent/background, locked-Mac, screenshot-only, and cross-display behavior remain unverified. See `references/local-mac-gui.md`.

## Capability and permission preflight

Codex Loop resolves external capability checks at the side-effect boundary that actually needs them. Read-only reasoning, inspection, editing, and validation should not trigger unrelated permission probes merely because a later external action is predictable.

When the bundled runtime is available, the host can make that stage explicit:

```bash
python3 scripts/codex_loop.py permission-preflight-plan \
  --session-id ROUTING_SESSION \
  --capability github_push \
  --capability github_actions \
  --capability google_drive_write
```

The command only plans probes; it does **not** grant or persist permission. ChatGPT must then execute each probe through the live host integration. Seeing a connector in the tool list, reading its schema, or observing a cached `connected=true`-style flag does not count.

Typical probes are deliberately low-risk: Local GitHub publication uses `git push --dry-run`; Web GitHub publication combines live push-capable repository permission readback with one Git-database create-blob/write-object call containing fixed empty content that remains unreferenced, so no tree/commit/ref or source is changed; GitHub Actions uses only an audited read-only/ref-nonmutating workflow job (for this repository, `Workspace Download`, never `Workspace Import`); Drive write access creates one uniquely named non-sensitive sentinel, reads back its exact ID/metadata, and deletes that exact sentinel immediately. A repository permission readback alone may prove access, but does not prove the later host write boundary; probe that boundary only when the side effect is imminent.

For push-triggered Web publication, the common early host-permission set is `github_push + google_drive_write`; GitHub Actions is proved after the request push by observing the matching run/receipt rather than by requiring a separate Actions write probe. For tasks that do not publish, Codex Loop does not request those permissions just because the integrations exist. Live successful observations may be reused during the current task/session while they remain valid.

Preflight is early permission discovery, not a security bypass. A later sensitive action can still require a fresh ChatGPT/OS/provider confirmation. Credentials, OAuth tokens, approval tokens, and claims of permanent authorization are never stored in Codex Loop's local config or runtime state. See `references/capability-preflight.md` for the full probe contract.

## Web mode versus Local mode

Web and Local are distinct first-class execution modes. A new conversation starts in Web mode, but an explicit Local selection immediately makes the local checkout authoritative for that conversation. RDC availability or an existing checkout never selects Local by itself, and neither mode may silently replace the other to escape a blocker.

```text
new conversation
  -> Web mode

explicit local-development request
  -> Local mode
  -> remains Local for later repository tasks in this conversation

explicit switch back to Web
  -> Web mode

new conversation
  -> Web mode again
```

A generic `push` request does not silently move a Web-mode task onto your computer. Local mode must have been explicitly selected in the current conversation first.

Codex Loop treats repository development-mode selection as a **pre-tool routing gate**. Before it searches a repository, mutates files, packages a release, runs Git, or transfers/synchronizes source, it resolves whether the conversation is still in Web mode or has explicitly entered Local mode. A connected local host, a visible local checkout, an RDC request, or the absence of an obvious Web write bridge is never enough to switch modes. Interaction-only RDC/Chrome/macOS work is routed independently and may run while the repository remains in Web mode; it must not inspect the local checkout unless Local development was separately selected.

If you explicitly ask to fix something in the current ChatGPT workspace, push it, **then** save/sync it to your local host, the ordering is fixed: Web edit/validate/review -> verified Web publish -> `web-local-sync-plan` -> exact self-contained Git bundle -> Google Drive staging -> RDC download to the authorized local path -> local hash/bundle verification. The local copy is downstream synchronization state, not the source baseline for that already-audited Web change.

For every push, the bundled Codex Loop controller resolves the routing state before transport; `publish-enter --controller-abi 1` is its deterministic helper, not a file required from the target repository. Web mode may reuse fresh publish-only evidence and invoke FAST_PUBLISH; Local mode uses native Git. Low-level `web-publish-*` commands remain implementation/debugging primitives. A missing `scripts/codex_loop.py` in an ordinary target repo is never a blocker; only a failure of the bundled controller/runtime itself can block this entry step.

If FAST_PUBLISH fails closed, Codex Loop still exposes only the router's modeled recovery choices; it never silently jumps modes or invents a transport. GitHub not already containing the audited source commit object is **not** a failure condition: the verified Git bundle carries that exact object to the importer. See `references/publication-router.md` and `references/web-mode-publish.md`.

When you ask to save/synchronize the current Web repository to a Mac/local host, the transfer path is fixed: exact self-contained Git bundle -> Google Drive binary staging -> RDC download to the explicitly authorized local path -> local size/SHA-256 + `git bundle verify` -> staging cleanup. This uses the separate `rdc_transfer` route and keeps `workspace_mode=web`; it does not make the local checkout authoritative. GitHub artifacts, direct unmodeled bridges, model relay, and source regeneration are not automatic alternatives. See `references/web-to-local-handoff.md`.

Each durable runtime task still has its own repository/worktree binding even though the development-location choice persists for the conversation.

## Acquiring GitHub source into Web mode

For “pull this repository into the Web workspace”, “open the GitHub version here”, or “sync this exact commit into ChatGPT”, Codex Loop preserves Git identity end to end:

```text
exact GitHub commit
  -> .github/workflows/workspace-download.yml
  -> commit-bound Git bundle artifact
  -> GitHub Connector artifact download
  -> artifact ZIP digest verification
  -> bundle SHA-256/size + logged commit/tree verification
  -> git bundle verify
  -> fresh real Git repository
  -> exact restored HEAD commit/tree verification
```

The workflow supports push-triggered packaging and `workflow_dispatch`. Codex Loop binds the selected run to the exact `head_sha`; choosing the newest artifact is not enough. If one specialized query cannot observe the relevant trigger, Codex Loop continues through compatible read-only Actions-run observations within the same GitHub authority and checks exact receipt-bound published-source artifacts. It reports the acquisition blocker only after those direct paths are exhausted, instead of falling back to shell `git clone`, per-file reconstruction, or source-only archives.

Installed Skills are excluded from normal source resolution. Only an explicit current-conversation instruction such as “use the installed Codex Loop as this workspace source” invokes the read-only copy exception. See `references/source-acquisition.md`.

## Publishing from Web mode

For a repository developed in the current ChatGPT Web workspace, publication now preserves the **audited Git commit object itself**:

```text
ChatGPT Web Git workspace
  -> validated clean audited commit/tree
  -> verified Git bundle + exact size/SHA-256
  -> Google Drive `ChatGPT-GitHub-Staging` via binary file_uri
  -> tiny GitHub import-request trigger commit
  -> audited `.github/workflows/workspace-import.yml`
  -> bundle verify + source commit/tree + ancestry verification
  -> bounded force-with-lease replacing only that trigger commit
  -> remote branch points to the original audited commit
  -> require remote commit == audited commit and remote tree == audited tree
  -> permanently delete the temporary Drive bundle
```

The GitHub Connector remains control plane only; source Git objects travel through the Drive binary bridge. The staging folder is a temporary anyone-with-link trust boundary for the GitHub-hosted runner. If that is unacceptable for the source, stop rather than invent another transport.

`publish-enter --controller-abi 1` is the normal publication entry and delegates to the controller-owned Web planner. `web-publish-bundle` creates the exact bundle. A verified remote base may be supplied as a Git bundle prerequisite when an acquired Web workspace intentionally lacks older history; the prerequisite must be an exact ancestor of audited HEAD. The remote short-circuit is valid only when **both** commit and tree already equal the audited source; the remote does not need to contain the source commit object beforehand because the bundle introduces it.

The importer is allowed one narrowly scoped non-fast-forward action: it may use `force-with-lease` only to remove the single request trigger commit it just received, after proving that trigger's parent equals the previously observed branch base and its only file delta is the request JSON. Any branch concurrency, extra trigger delta, ancestry failure, bundle mismatch, or lease failure stops publication. This is not general force-push permission.

Repository setup therefore needs Actions enabled, `contents: write` for the audited importer, and branch policy that permits this exact lease-guarded trigger replacement. The workflow never creates a new source commit; its receipt and independent remote readback must both equal the audited workspace commit/tree. See `references/web-mode-publish.md`.

## Publishing from Local mode

This section documents Local publication after explicit Local selection. Native Git is the canonical Local transport, not a fallback.

For a local repository, the bundled controller selects Codex Loop's verified native-Git publication path; the target repository itself does not need Codex Loop runtime files:

```text
LOCAL_ROOT repository
  -> validate / review
  -> git commit
  -> native git push through RDC
  -> native git fetch/readback
  -> require remote commit and tree == audited local commit and tree
```

Source bytes stay in Git's data plane. GitHub connector/object APIs, model-carried Base64, copied source trees, and release ZIP contents are not fallback publication transports.

Example prompts:

```text
Modify this locally and push.
Commit these local changes and push them to main.
```

If native Git fails because of authentication, network access, permissions, branch protection, or divergence, Codex Loop reports that exact blocker rather than silently switching transports.

## Optional post-push sync back to ChatGPT

After a verified local push, Codex Loop can offer to synchronize that exact commit into the current ChatGPT workspace. Synchronization is opt-in; a push does not automatically download the repository back into ChatGPT.

The verified path is:

```text
verified pushed commit
  -> GitHub Actions Git bundle artifact
  -> GitHub Connector artifact download
  -> artifact digest + bundle SHA-256/size verification
  -> git bundle verify
  -> fresh real Git repository
  -> exact restored HEAD commit/tree verification
```

The workflow run must be bound to the exact pushed `head_sha`. The target repository needs `.github/workflows/workspace-download.yml` or an explicitly equivalent audited workflow. This repository contains a working example.

Example:

```text
Sync the pushed commit back to this workspace.
```

Workspace synchronization works for ordinary repositories as well as Skills. It is not the same as installing a Skill.

## Skill packaging and installation

Source publication, workspace synchronization, and Skill packaging are separate states.

```text
SOURCE_PUSHED      GitHub matches the exact audited source commit/tree
WORKSPACE_SYNCED   that exact commit has been verified in the ChatGPT workspace
SKILL_PACKAGED     a validated skill.zip exists; consumer packages are repository-neutral
```

When packaging Codex Loop as a ChatGPT Skill, build the runtime-only archive rather than zipping the whole development repository:

```bash
python3 tools/build_skill_zip.py --source . --output /tmp/skill.zip
```

The default build is a **consumer** package: its build-generated manifest uses `repository_binding=none` and contains no `source.repository`, commit, or tree fields. `yihan-hu/codex-loop` therefore remains maintainer/release context, not an installation-time repository requirement. Use `--distribution-profile maintainer --source-repository ... --source-commit ... --source-tree ...` only for an explicit provenance artifact.

The builder emits exactly one top-level `codex-loop/` directory and includes only runtime Skill files (`SKILL.md`, `agents/`, `assets/`, `references/`, `scripts/`, plus license/attribution files). It excludes `.github/`, `tests/`, `README.md`, repository tooling, `__pycache__`, and compiled Python caches. This separation matters because a repository-valid ZIP is not necessarily a ChatGPT-installable Skill package.

For every Codex Loop update, validate the resulting Skill with Skill Creator so the canonical package is `skill.zip`. Then run `python3 scripts/prepare_codex_loop_download.py --source /path/to/skill.zip --output /path/to/codex-loop.zip`, which copies the file without recompression and verifies byte identity. Expose only that exact `codex-loop.zip` as a fresh current-conversation artifact; its SHA-256 must equal the official `skill.zip` SHA-256. Never synthesize or reuse a Library URL/reference for the generated package. The user then installs it manually through `Plugins -> Plugin Directory -> Skills -> Create -> Upload from your computer`.

## Useful prompts

```text
Use Codex Loop to implement this feature and test it.
Keep the repository in Web mode, but use my local Chrome to verify the signed-in flow.
Preflight every integration this task will need before you start changing files.
Use local development under /Users/alice/PiWork for this repository.
Fix this locally and push.
Sync the pushed commit back to the current workspace.
Package this repository as a ChatGPT Skill.
Switch back to Web mode for the next task.
```

## How Codex Loop works

The deterministic runtime tracks repository/task facts such as workspace binding, mutation generation, validation evidence, acceptance criteria, review freshness, process state, and external-action state. ChatGPT still decides what to do and dispatches the actual host tools.

The normal lifecycle is:

```text
assess -> observe -> act -> integrate -> validate -> review -> evidence -> completion gate
```

Simple explanation-only requests can stay on a direct path without bootstrapping durable runtime state.

For implementation details, start with `SKILL.md`. Deeper contracts live under `references/`, and executable runtime code lives under `scripts/`.

## Safety boundaries

- Preserve pre-existing user changes and untracked files.
- Treat RDC host roots as capability ceilings. Once a repository task is bound, keep filesystem/search/process access inside that canonical worktree or an explicitly named task-owned path; sibling repositories remain out of scope unless separately granted.
- Never read credential files directly.
- Treat exact commit/tree readback as publication success evidence in both modes: native Git readback in Local mode, and bundle-bound workflow receipt plus independent GitHub branch readback in Web mode.
- Treat the public-read Google Drive staging folder as a temporary publication trust boundary and delete staged Git bundles after verified success.
- Do not invent a binary transfer route when no verified bridge exists.
- Never edit an installed Skill in place or treat it as ongoing source authority. An installed Skill may bootstrap a fresh workspace only after explicit current-conversation source authorization; downloaded artifacts and copied release folders remain transport/release material rather than development baselines.
- Materialize GitHub source into Web mode through the exact-commit `workspace-download.yml` Actions artifact path, not shell `git clone` or per-file reconstruction.

## Troubleshooting

**Chrome extension is installed but Browser Control is unavailable.** First distinguish host health from session health. If the native messaging host is missing/invalid, use `ChatGPT / Codex -> Settings -> Computer use -> Google Chrome -> Manage / Reconnect`, then recheck. Do not hand-create the manifest or use AppleScript/internal sockets as a substitute. If host health is good but the current conversation still has no Browser executor, classify `SESSION_BROWSER_CAPABILITY_MISSING` and retry from a Browser-capable conversation rather than repairing Chrome again.

**Codex Loop is trying to use the wrong local path.** Explicitly state your absolute RDC-authorized workspace root when entering Local mode. The distributed Skill should contain no author-specific home-directory path.

**RDC cannot access the repository.** Confirm that the repository is under the directory you authorized in Remote Desktop Commander and that the integration is connected.

**A Web-mode push does not start.** Confirm Google Drive is connected, `ChatGPT-GitHub-Staging` is anyone-with-link readable, the target repository has Actions enabled, and workflow permissions allow read/write.

**`git push` fails.** Fix the reported native Git authentication/network/permission/divergence problem on the RDC host. Codex Loop intentionally does not switch to a different source-upload transport.

**A pushed commit is not visible in ChatGPT.** Git push updates GitHub, not the current ChatGPT workspace. Ask to sync the pushed commit and make sure the repository has the audited workspace-download workflow.

**GitHub source cannot be materialized into the Web workspace.** Confirm the repository has the audited `workspace-download.yml`, locate or produce a run bound to the exact target `head_sha`, and verify the artifact can be downloaded through the GitHub Connector. If one query surface cannot observe a push-triggered run, classify that as an observability limitation and continue through a compatible read-only Actions-runs endpoint within the same GitHub authority; also inspect successful import-run receipts for an exact receipt-bound published-source artifact. Do not conclude that the workflow failed or the direct artifact is absent merely from an empty incompatible query.

**Installing a returned Codex Loop package.** Download the fresh `codex-loop.zip` artifact from the current conversation, then use `Plugins -> Plugin Directory -> Skills -> Create -> Upload from your computer`. `codex-loop.zip` is byte-identical to the official Skill Creator `skill.zip`; package generation and artifact delivery are not installation. Do not route the generated package through a presumed Library deep link.

**Local mode disappeared in a new chat.** This is expected. Development mode is conversation-scoped; each new conversation starts in Web mode.

## Development

Run repository-native tests from the repository root. The compatibility suite lives under `tests/compat/`. Source-fidelity checks are required only when upstream-derived resources or their audited mappings change; README and local configuration documentation are local extensions.

See `ATTRIBUTION.md`, `LICENSE`, and `NOTICE` for provenance and licensing information.
