# Codex Loop

Codex Loop is a ChatGPT Skill that applies Codex-style objective continuation to non-trivial multi-step work across domains while keeping ChatGPT as the host for reasoning, tools, approvals, connectors, and conversation state.

It uses broad invocation with adaptive direct-vs-durable lifecycle assessment. Trivial one-step work stays lightweight; dependency-bearing work can preserve objective state, evidence, review, external actions, and completion across multiple stages without launching Codex CLI or another model runtime.

## Runtime control plane v2

Codex Loop separates repeatable control-plane mechanics from host/model reasoning. The current runtime adds four coordinated surfaces: **Execution Outcome Separation** (`workload != process != cleanup`), a unified **Private Host Profile** with Cloud-Browser-first interaction preference, deterministic **Durable Resume** that reconciles current reality instead of reviving stale PASS evidence, and provenance-bound Skill packages that identify their exact Git source revision. These are thin ChatGPT-host adaptations; existing upstream host gaps remain explicitly labeled rather than being promoted to false parity.

Key references: `references/execution-supervision.md`, `references/host-profile.md`, `references/persistence-resume.md`, and `references/deployment-provenance.md`.

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
- preflighting required RDC, GitHub, Google Drive, browser, and host permissions before substantive multi-step execution;
- publishing Web-mode workspace source through verified Drive staging + GitHub Actions, or Local-mode source through native Git;
- packaging ChatGPT Skills;
- refreshing an active current-workspace Skill after its Web-mode source is pushed, with a completion-blocking deployment handoff;
- synchronizing a verified local GitHub commit back into the current ChatGPT workspace;
- degrading requested reviewer/researcher/tester delegation to a bounded logical isolation when native subagents are unavailable.

Codex Loop is not Codex CLI and does not contain a model runtime. ChatGPT remains the execution host.

## Install as a ChatGPT Skill

This repository is the Skill source. In a normal external deployment, a Git checkout or ordinary source ZIP is not automatically an installed ChatGPT Skill: package the repository into a validated `skill.zip`, then use a supported install/update action or the ChatGPT Skills UI.

There is one important workspace-hosted rule that applies to **all Skills and Skill installation packages**: if the Skill/package is already present or active in the current workspace or host-managed Skill environment, prefer supported host-managed non-browser update operations and never treat deployment intent as permission to automate browser clicks.

Codex Loop now also keeps the install destination in a **conversation-scoped deterministic routing file**. In ChatGPT Web, a generic `install` resolves to the native `chatgpt_web_skill` target unless the user explicitly selects another deployment target. RDC availability, a remembered Mac checkout, or an existing `~/.codex/skills` directory cannot silently redirect that request to local Codex. The routing file is private temp state and resets with a new routing session; it is not stored in Host Profile or Git.

For the **active current-workspace Skill being maintained in Web mode**, Codex Loop now has a stronger post-push invariant: when you ask to push/publish the edited Skill, verified GitHub publication must be followed by deployment reconciliation for the same pushed revision. Codex Loop records a completion-blocking `chatgpt_skill_update` planning handoff, but the native Skill installation/update surface is owned by `skill-creator`/the ChatGPT host. The handoff itself cannot count as UI evidence. If the host never exposes/initiates a native update surface, the result stays `DEPLOY_PENDING — HOST_SKILL_INSTALL_SURFACE_NOT_OBSERVED` instead of silently finishing.

For **Codex Loop updating itself**, that handoff is terminal for the initiating turn. `skill-deploy-handoff` activates a terminal self-update barrier, `skill-creator`/the native installer must be the final current-turn owner, and Codex Loop must not issue another command or append its own closing/status response after the install surface is initiated. Reconciliation starts only on a later user/host turn with `skill-deploy-resume --later-host-turn-observed`. This prevents the orchestrator from reclaiming the response slot and displacing a just-surfaced Web install control.

Source publication, native UI/surface observation, and deployment are separate evidence states. Codex Loop must not emulate the product UI in prose: after the later-turn resume, `skill-deploy-surface-record` is valid only when `skill-creator` or an equivalent native host primitive actually exposed/initiated the update surface, and `skill-deploy-complete` requires installed-revision evidence. Browser automation remains separately authorized.

## Quick start

Codex Loop is designed for **implicit invocation**. In normal use, you should not need to type `@Codex Loop` or name the Skill. ChatGPT should select it broadly for non-trivial objectives that plausibly contain multiple dependent steps or need durable evidence/state, iterative review, delegation, external-action bookkeeping, managed processes, or cross-tool coordination. That includes research, analysis, writing, scientific work, artifact creation, operations, repository/software development, Git lifecycle work, Skill maintenance, and Computer Use. The bundled lifecycle assessment then decides whether execution stays direct or bootstraps durable state.

Short follow-ups such as `revise`, `verify`, `export`, `push`, `sync`, or `open this in Chrome` should continue through Codex Loop when the active objective is clear from context. Automatic invocation does **not** bypass permissions: local source mutation and actual Computer Use remain explicitly authorized per task under the existing safety gates.

For repository or Skill-development requests, **Web mode** is the default development location in every new conversation. Pure research, writing, analysis, artifact, or operations objectives do not need Web/Local repository routing unless a later step actually becomes development-location-sensitive.

**Recommended path:** keep ordinary repository development in the ChatGPT/chatbox workspace and connect that Web workspace to GitHub when publication is needed. This is usually faster and simpler than Mac Local mode because it avoids the extra RDC hop, host-filesystem authorization, native-Git host state, and Mac-to-workspace synchronization steps.

When a Web task starts from source on GitHub, Codex Loop does **not** treat container `git clone` as the standard acquisition path. It materializes the exact revision through the audited `.github/workflows/workspace-download.yml`, downloads the commit-bound **Git bundle** artifact through the GitHub Connector, verifies artifact + bundle integrity, runs `git bundle verify`, restores a fresh real Git repository, and requires exact HEAD commit/tree equality before binding it.

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

If you ask to push from Web mode, Codex Loop keeps the current workspace authoritative and uses the verified Google Drive -> GitHub Actions publication path when its prerequisites are configured. If that workspace is the active Skill being edited, a successful source push immediately enters the mandatory Skill refresh handoff for the exact published commit; `SOURCE_PUSHED` alone is not the end of the task.

**Local mode is a supported backup / escape hatch, not the recommended day-to-day path.** Use it when a task genuinely needs persistent files or tools on your Mac, or when you deliberately want the Mac checkout to be the repository source of truth. For ordinary development it is usually slower than the Web workspace + GitHub path because each task can add RDC and permission checks, native-host coordination, and extra push/synchronization round trips.

To use that backup path, explicitly enter **Local mode**:

```text
Use local development for this repository.
Use Codex Loop locally under /Users/alice/PiWork and fix this bug.
```

Once Local mode is selected, later repository tasks in the same conversation keep using that local repository as the baseline unless you explicitly switch back to Web mode. **That does not carry forward permission to modify local source.** Each task that would edit/create/delete/overwrite local source files must explicitly authorize local mutation again, for example: `Fix this locally and push.` A generic `push`, read-only inspection, RDC availability, or earlier local edits do not authorize new source changes. A new conversation starts in Web mode again.

## Adaptive progress visibility

Codex Loop increases user-visible progress for real multi-step/durable objectives by default so a long Web task does not look stalled. The built-in enhanced policy uses an approximate **15-second / 3-substantive-tool-call** cadence (whichever comes first), plus immediate concise updates for material findings or blockers. Trivial/direct tasks remain low-noise. This is host-facing guidance: ChatGPT owns actual message timing and tool dispatch.

The preference is user-specific and is never committed. `python3 scripts/codex_loop.py progress-config` shows the effective values; `progress-config --mode enhanced --interval-seconds 20 --tool-call-interval 4` writes overrides atomically to `~/.codex-loop/host.json` (or `CODEX_LOOP_HOME/host.json`). The supported modes are `enhanced`, `standard`, and `quiet`; upfront planning and material-event updates can be toggled independently. `progress-config --reset` removes only the progress override and returns to built-in defaults. See `references/progress-visibility.md`.

The host config is private runtime state outside the repository and outside `skill.zip`. It may coexist with non-sensitive workspace locators/preferences, but it does not store current `workspace_mode`, `interaction_target`, or `deployment_target`; those live in the conversation routing file. Host config must never contain credentials, approval/session tokens, or other secrets.

## Optional cross-conversation persistence

Web conversations and ephemeral workspaces are not a durable storage contract. Codex Loop therefore separates two optional, default-off Drive recovery layers. `state_only` stores a small schema-whitelisted lifecycle/reconciliation manifest. **Workspace Cache** stores an immutable 7-day Git/worktree capsule so a later conversation can restore the actual development workspace.

`python3 scripts/codex_loop.py workspace-cache-create --cwd REPO --repository OWNER/REPO --output /PRIVATE/TEMP/workspace-cache.tar.gz` preserves the exact HEAD commit/tree plus staged, unstaged, and non-ignored untracked state. It excludes ignored build/runtime material, Git config/hooks, and credentials. Upload the returned binary privately to `Codex Loop/.runtime/workspace-cache` through the Drive connector.

On restore, verify the externally retained capsule SHA-256, run `workspace-cache-validate`, restore into a fresh directory with `workspace-cache-restore`, and require exact HEAD/tree + state fingerprint before binding the new workspace. After success, upload the small consumed receipt and delete the exact capsule. If deletion fails, the restore remains successful and cleanup becomes `CACHE_CLEANUP_PENDING`; every later cache create/list/restore operation opportunistically scans only the bounded cache folder and retries cleanup of consumed or >=7-day exact owned objects. Consumed cache IDs are excluded from automatic restore selection even when their capsule could not be deleted.

State-only manifests retain their separate TTL/reconciliation rules and always resume into a new freshness domain. Drive is recovery transport, not a second mutable truth source. See `references/persistence.md` and `references/persistence-resume.md`.

## Architecture fidelity governance

Codex Loop tracks not only source lineage but also behavioral/control-plane alignment with upstream Codex. `references/architecture-fidelity.yaml` records watched upstream surfaces and whether Codex Loop is aligned, partial, host-gapped, or intentionally divergent, together with the degradation and upgrade path. Upstream audits review **Source Delta + Control-plane Delta + Concept Delta**; unresolved `NEEDS_REVIEW` entries fail the audit. The governing rule is semantic parity before implementation parity.

## Local mode requirements (backup path)

Local mode requires a connected **Remote Desktop Commander (RDC)** integration because ChatGPT needs a host-authorized bridge to the persistent filesystem and native Git installation on your computer. The end-to-end path documented and verified in this repository is macOS + RDC + native Git; other hosts should be treated as unverified until their equivalent behavior is tested.

Choose one absolute directory to be your persistent local workspace root. Codex Loop calls this `LOCAL_ROOT`. For example:

```text
/Users/alice/PiWork
```

`LOCAL_ROOT` is a runtime placeholder, not a path baked into the distributed Skill and not necessarily an operating-system environment variable. Configure that directory as an allowed directory in RDC. You may provide it when selecting Local mode, or persist a non-sensitive default in `~/.codex-loop/host.json` so later conversations can reuse it after you explicitly choose Local development.

A persisted root does **not** make new conversations start in Local mode. New conversations still start in Web mode; the host-local default is consulted only after explicit Local repository-development intent.

You should not edit the Skill to replace another user's home directory. Different users can choose different roots.

Keep repositories, worktrees, scratch data, and release staging that Codex Loop operates on inside `LOCAL_ROOT`. Paths outside it require separate explicit authorization.

See `references/local-mode-setup.md` for the exact agent-side resolution and safety contract.

## Setting up Local mode

1. Connect Remote Desktop Commander to ChatGPT and authorize your chosen `LOCAL_ROOT` directory.
2. Put or clone the repositories you want Codex Loop to edit under that root.
3. In a new ChatGPT conversation, explicitly select Local mode and provide the root if it has not already been established, for example: `Use local development under /Users/alice/PiWork.`
4. Codex Loop binds each repository task to one canonical Git working tree under that root. It does not treat copied archives, installed Skills, or release staging folders as later development baselines.
5. If you want to push to GitHub, make sure native Git on the RDC host is authenticated. The verified path uses native Git and remote commit/tree readback; credentials remain host-owned.

For GitHub CLI authentication, an interactive setup can use:

```bash
gh auth login --web --git-protocol https
```

Do not paste tokens or credentials into ChatGPT. Let Git, `gh`, the OS credential helper, or the host integration consume them normally.

If `LOCAL_ROOT` is missing or RDC has not authorized it, Local mode fails closed instead of guessing another directory.

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
BOUND    The current durable task uses one canonical Git working tree.
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

A new routing session starts with `workspace_mode=web`, `interaction_target=none`, and unresolved deployment target. In ChatGPT Web, initialize with `python3 scripts/codex_loop.py route-init --host-surface chatgpt_web`. Before a repository, browser/computer, installation, or publication host action, use `route-check`; local/cross-surface changes go through `route-transition` with explicit user-selection evidence. Current-task permissions are not persisted by the routing file.

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

For multi-step work, Codex Loop reviews the intended workflow early, resolves routing, and then runs a **real permission smoke test before substantive execution**. This early task review is separate from the final code/change review. The goal is to surface predictable GitHub/Actions/Drive/RDC/browser permission prompts before the task has already spent most of its work budget.

When the bundled runtime is available, the host can make that stage explicit:

```bash
python3 scripts/codex_loop.py permission-preflight-plan \
  --session-id ROUTING_SESSION \
  --capability github_push \
  --capability github_actions \
  --capability google_drive_write
```

The command only plans probes; it does **not** grant or persist permission. ChatGPT must then execute each probe through the live host integration. Seeing a connector in the tool list, reading its schema, or observing a cached `connected=true`-style flag does not count.

Typical probes are deliberately low-risk: Local GitHub publication uses `git push --dry-run`; Web GitHub publication combines live push-capable repository permission readback with one Git-database create-blob/write-object call containing fixed empty content that remains unreferenced, so no tree/commit/ref or source is changed; GitHub Actions uses only an audited read-only/ref-nonmutating workflow job (for this repository, `Workspace Download`, never `Workspace Import`); Drive write access creates one uniquely named non-sensitive sentinel, reads back its exact ID/metadata, and deletes that exact sentinel immediately. A repository permission readback alone may prove access, but does not count as prewarming the host's write approval.

For Web-mode publication, the common early set is `github_push + github_actions + google_drive_write`. For tasks that do not publish, Codex Loop does not request those permissions just because the integrations exist. Live successful observations may be reused during the current task/session while they remain valid.

Preflight is early permission discovery, not a security bypass. A later sensitive action can still require a fresh ChatGPT/OS/provider confirmation. Credentials, OAuth tokens, approval tokens, and claims of permanent authorization are never stored in Codex Loop's local config or runtime state. See `references/capability-preflight.md` for the full probe contract.

## Web mode versus Local mode

Treat the two modes asymmetrically: **Web mode is the recommended primary development route; Mac Local mode is an explicit backup.** A connected RDC integration or an existing Mac checkout is never, by itself, a reason to recommend Local mode or switch to it.

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

Codex Loop treats repository development-mode selection as a **pre-tool routing gate**. Before it searches a repository, mutates files, packages a release, runs Git, or transfers/synchronizes source, it resolves whether the conversation is still in Web mode or has explicitly entered Local mode. A connected Mac, a visible local checkout, an RDC request, or the absence of an obvious Web write bridge is never enough to switch modes. Interaction-only RDC/Chrome/macOS work is routed independently and may run while the repository remains in Web mode; it must not inspect the local checkout unless Local development was separately selected.

If you explicitly ask to fix something in the current ChatGPT workspace, push it, **then** sync the pushed result to your Mac, the ordering is fixed: Web edit/validate/review -> verified Web publish -> resolve authorized `LOCAL_ROOT` -> update the Mac repository from the exact pushed commit. The Mac checkout is downstream synchronization state, not the source baseline for that already-audited Web change.

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

The workflow supports push-triggered packaging and `workflow_dispatch`. Codex Loop binds the selected run to the exact `head_sha`; choosing the newest artifact is not enough. If no exact run can be produced or observed, it reports the acquisition/observability blocker instead of falling back to shell `git clone`, per-file reconstruction, or source-only archives.

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

`web-publish-bundle` creates the exact bundle. A verified remote base may be supplied as a Git bundle prerequisite when an acquired Web workspace intentionally lacks older history; the prerequisite must be an exact ancestor of audited HEAD. `web-publish-plan --verified-tree-fast-path` may reuse fresh validation/review/capability evidence and an unchanged bundle receipt, but it never weakens identity requirements. The remote short-circuit is valid only when **both** commit and tree already equal the audited source.

The importer is allowed one narrowly scoped non-fast-forward action: it may use `force-with-lease` only to remove the single request trigger commit it just received, after proving that trigger's parent equals the previously observed branch base and its only file delta is the request JSON. Any branch concurrency, extra trigger delta, ancestry failure, bundle mismatch, or lease failure stops publication. This is not general force-push permission.

Repository setup therefore needs Actions enabled, `contents: write` for the audited importer, and branch policy that permits this exact lease-guarded trigger replacement. The workflow never creates a new source commit; its receipt and independent remote readback must both equal the audited workspace commit/tree. See `references/web-mode-publish.md`.

## Publishing from Local mode

This section documents the supported backup path. For ordinary work, prefer Web workspace -> GitHub publishing unless you explicitly need the Mac checkout as the development baseline.

For a local repository, Codex Loop's verified publication path is:

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

Source publication, workspace synchronization, Skill packaging, and ChatGPT installation are separate states.

```text
SOURCE_PUSHED      GitHub matches the exact audited source commit/tree
WORKSPACE_SYNCED   that exact commit has been verified in the ChatGPT workspace
SKILL_PACKAGED     a validated skill.zip exists for the intended commit
DEPLOY_PENDING     the intended Skill revision still needs an observed current/installed-Skill update
DEPLOYED           an explicit supported install/update action or user confirmation proves installation
```

When packaging Codex Loop as a ChatGPT Skill, build the runtime-only archive rather than zipping the whole development repository:

```bash
python3 tools/build_skill_zip.py --source . --output /tmp/skill.zip
```

The builder emits exactly one top-level `codex-loop/` directory and includes only runtime Skill files (`SKILL.md`, `agents/`, `assets/`, `references/`, `scripts/`, plus license/attribution files). It excludes `.github/`, `tests/`, `README.md`, repository tooling, `__pycache__`, and compiled Python caches. This separation matters because a repository-valid ZIP is not necessarily a ChatGPT-installable Skill package. The repository source itself is not proof of installation.

For Skill creation/update tasks, hand the validated `skill.zip`/source generation to the platform `skill-creator` workflow or an explicitly equivalent native host-managed update primitive. Codex Loop's own `skill-deploy-handoff` is planning only and must not be rendered or described as if it were the product Install/Update UI. Record an actually observed native surface with `skill-deploy-surface-record`, then record `DEPLOYED` only after installed-revision evidence with `skill-deploy-complete`.

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

The normal durable lifecycle is:

```text
assess -> observe -> act -> integrate -> validate -> review -> evidence -> completion gate
```

Simple explanation-only requests can stay on a direct path without bootstrapping durable runtime state.

For implementation details, start with `SKILL.md`. Deeper contracts live under `references/`, and executable runtime code lives under `scripts/`.

## Safety boundaries

- Preserve pre-existing user changes and untracked files.
- Keep local filesystem access inside the resolved RDC-authorized `LOCAL_ROOT` unless the user explicitly authorizes another narrow root.
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

**GitHub source cannot be materialized into the Web workspace.** Confirm the repository has the audited `workspace-download.yml`, locate or produce a run bound to the exact target `head_sha`, and verify the artifact can be downloaded through the GitHub Connector. If one query surface cannot observe a push-triggered run, classify that as an observability limitation and inspect the repository's Actions runs through a compatible endpoint; do not conclude that the workflow failed merely from an empty incompatible query.

**A new Skill version is not active after pushing.** For the active Skill being maintained in the current Web workspace, this should remain an unfinished `DEPLOY_PENDING` workflow until the native Skill installation/update surface is actually invoked and the intended revision is observably active. `skill-deploy-handoff` alone never counts as UI evidence. For Codex Loop self-update, let `skill-creator`/the host installer be the final owner of that turn; on the next user/host turn run `skill-deploy-resume`, then reconcile observed surface/deployment evidence with `skill-deploy-surface-record` and `skill-deploy-complete`.

**The same-name Skill update UI appears and immediately disappears.** Validate the production package first. If it passes, allow at most one exact-content repack with Skill Creator's official packager, then use a minimal disposable new-name Skill as an A/B host-surface probe. If the new-name install UI is stable while the same-name update UI disappears, classify `HOST_SAME_NAME_SKILL_UPDATE_SURFACE_UNSTABLE`, stop modifying the canonical package to chase the symptom, and keep the probe diagnostic-only. Do not rename the production Skill or remove/replace the installed Skill without a separate explicit deployment instruction. See `references/skill-deployment.md`. After that diagnosis succeeds, use the fixed **Codex Loop Update Bridge** recovery and preserve the experimentally successful bridge shape: exactly two files (`SKILL.md`, `agents/openai.yaml`), explicit-only invocation, the supported `policy.products`, and a self-referencing `$codex-loop-update-bridge` `default_prompt`; keep its body minimal and limited to presenting the already-validated canonical package, with no scripts/references/assets or generalized updater logic. A richer bridge that returns `Library not found` should be reduced to this known-good shape instead of triggering production ZIP surgery. Install the bridge through the proven new-name surface, then on a later bridge-owned turn present only the canonical Codex Loop package for update and terminate after the native surface starts.

**Local mode disappeared in a new chat.** This is expected. Development mode is conversation-scoped; each new conversation starts in Web mode.

## Development

Run repository-native tests from the repository root. The compatibility suite lives under `tests/compat/`. Source-fidelity checks are required only when upstream-derived resources or their audited mappings change; README and local configuration documentation are local extensions.

See `ATTRIBUTION.md`, `LICENSE`, and `NOTICE` for provenance and licensing information.
