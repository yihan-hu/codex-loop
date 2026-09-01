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

For the **active current-workspace Skill being maintained in Web mode**, Codex Loop now has a stronger post-push invariant: when you ask to push/publish the edited Skill, verified GitHub publication must be followed by deployment reconciliation for the same pushed revision. Codex Loop records a completion-blocking `chatgpt_skill_update` handoff, tries a supported host-managed update first, and otherwise surfaces the Save/Update UI handoff. If neither update path is available, the result stays `DEPLOY_PENDING` instead of silently finishing. This prevents the common state where GitHub cannot silently become newer than the Skill that is still active in the workspace.

Source publication and deployment are still separate evidence states. Surfacing a Save/Update handoff is not browser automation; if actual Chrome/macOS interaction is needed to click through the UI, explicit current-task computer-use authorization is still required. A separately installed external Skill copy remains a distinct deployment target and is not updated merely because GitHub changed.

## Quick start

Codex Loop is designed for **implicit invocation**. In normal use, you should not need to type `@Codex Loop` or name the Skill. ChatGPT should select it broadly for non-trivial objectives that plausibly contain multiple dependent steps or need durable evidence/state, iterative review, delegation, external-action bookkeeping, managed processes, or cross-tool coordination. That includes research, analysis, writing, scientific work, artifact creation, operations, repository/software development, Git lifecycle work, Skill maintenance, and Computer Use. The bundled lifecycle assessment then decides whether execution stays direct or bootstraps durable state.

Short follow-ups such as `revise`, `verify`, `export`, `push`, `sync`, or `open this in Chrome` should continue through Codex Loop when the active objective is clear from context. Automatic invocation does **not** bypass permissions: local source mutation and actual Computer Use remain explicitly authorized per task under the existing safety gates.

For repository or Skill-development requests, **Web mode** is the default development location in every new conversation. Pure research, writing, analysis, artifact, or operations objectives do not need Web/Local repository routing unless a later step actually becomes development-location-sensitive.

**Recommended path:** keep ordinary repository development in the ChatGPT/chatbox workspace and connect that Web workspace to GitHub when publication is needed. This is usually faster and simpler than Mac Local mode because it avoids the extra RDC hop, host-filesystem authorization, native-Git host state, and Mac-to-workspace synchronization steps.

When a Web task starts from source that currently lives on GitHub, Codex Loop does **not** treat container `git clone` as the standard acquisition path. It materializes the exact GitHub revision through the audited `.github/workflows/workspace-download.yml` Actions artifact, downloads that artifact through the GitHub Connector, verifies the artifact digest and source archive SHA-256, and extracts it into a fresh Web workspace.

For Skill maintenance, an installed Skill may be copied into a fresh workspace only as a narrow bootstrap optimization when its deployment provenance proves that it is the latest observed target-branch revision. The installed directory stays read-only deployment state; after copying, only the new workspace is authoritative. If freshness is uncertain, acquire the source from GitHub through the verified Actions-artifact route.

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

The host config is private runtime state outside the repository and outside `skill.zip`. It may coexist with non-sensitive workspace-routing defaults, but must never contain credentials, approval/session tokens, or other secrets.

## Optional cross-conversation persistence

Web conversations and ephemeral workspaces are not a durable storage contract. Codex Loop therefore supports an **optional, default-off `state_only` persistence adapter** for long objectives. The first adapter is Google Drive, but Drive is only the storage transport: ChatGPT owns OAuth and connector credentials, while Codex Loop creates a small schema-whitelisted recovery manifest. Nothing about the user's Drive connection, folder IDs, task manifests, tokens, or connector session is committed to GitHub.

`python3 scripts/codex_loop.py persistence-export --cwd REPO --backend google_drive --repository OWNER/REPO` creates the private temporary manifest for a durable task. The host can upload it to a private `Codex Loop/.runtime/...` folder. A later conversation downloads it and runs `persistence-validate`; the recovered data is evidence for bootstrap/reconciliation, never a second source of truth. The manifest deliberately excludes chain of thought, hidden instructions, credentials, raw tool transcripts, local roots, and raw external-action identities.

Cleanup uses refreshable TTLs plus opportunistic garbage collection. Expired clean objects are moved to Trash rather than permanently deleted; an expired manifest with unresolved dispatched/outcome-unknown external actions is retained until reconciliation. Missing Drive access degrades recoverability only and does not block normal work unless the user explicitly required cross-conversation recovery. See `references/persistence.md`.

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

The host-local config and registry are deliberately outside every repository and outside the packaged Skill. Git commits, GitHub pushes, Web-mode source archives, and `skill.zip` must not include them. Do not put tokens, passwords, cookies, OAuth credentials, approval state, or session-grant nonces in either file.

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

Codex Loop treats **where the repository lives** and **which computer/browser is being controlled** as separate axes:

```text
workspace_mode:      web | local
interaction_target:  none | cloud_browser | local_chrome | local_mac_gui
```

For example, `workspace_mode=web` plus `interaction_target=local_chrome` means the repository remains in the current ChatGPT workspace while ChatGPT uses your Mac only to interact with your signed-in local Chrome. Using RDC for that interaction does not make the Mac checkout authoritative.

For `local_chrome`, Codex Loop keeps ChatGPT as the reasoning authority and does not launch a local Codex agent. Browser Control requires an official/supported host-exposed Chrome/Computer Use executor or native bridge that is actually attached to the current conversation. RDC/AppleScript, Chrome `execute javascript`, generic screenshot/mouse/keyboard automation, and private Browser/Codex sockets are not Browser Control fallbacks and must not be reported as Browser capability success.

**Computer use is opt-in per task.** Codex Loop must not interact with local Chrome or the macOS GUI until you explicitly authorize computer use for that task, for example: `Use my local Chrome to verify this signed-in flow.` A connected RDC/Chrome session, prior computer-use success, or the agent deciding that browser interaction would be useful is not authorization. Once authorized, low-risk actions within that task scope can continue without asking before every individual click/tab action; host-required sensitive confirmations still apply.

Codex Loop distinguishes `browser_host_health` (Chrome, extension, native host) from `browser_session_health` (whether this conversation has a callable Browser executor). A healthy host with no attached executor is `SESSION_BROWSER_CAPABILITY_MISSING`, not a broken Chrome installation. See `references/browser-control-recovery.md`.

### Native macOS Computer Use (`local_mac_gui`)

For native macOS UI tasks, `local_mac_gui` is a separate explicitly authorized Computer Use path. It does not require Mac Codex and does not change `workspace_mode`: a Web-workspace task can use the Mac GUI for interaction while source remains in the ChatGPT workspace.

The verified control pattern is **semantic target -> dynamic geometry -> real mouse event -> independent readback**. Codex Loop prefers Accessibility (`AXRole`/`AXIdentifier`) to locate the intended control, derives click coordinates from the element's live position/size, dispatches the minimum CoreGraphics mouse move/down/up event when a real click is needed, and then verifies the resulting application state through Accessibility or another structured surface. It restores transient cursor/focus state after smoke tests when practical. Global keystrokes are a last resort and require freshly verified target focus.

A Calculator smoke test verified this end to end: resolve `AllClear`/`Two`/`Add`/`Equals` from the live Accessibility tree, click `AC -> 2 -> + -> 2 -> =` with real mouse events, then read back `4` from Calculator's current result view. The coordinates are intentionally not part of the contract and must be resolved dynamically each time.

This path is **not Browser Control** and does not satisfy Browser capability checks. It must not be used to disguise a missing Browser executor. Silent/background, locked-Mac, screenshot-only, and cross-display behavior remain unverified. See `references/local-mac-gui.md`.

## Capability and permission preflight

For multi-step work, Codex Loop should determine the required integrations before substantive execution and check them together. Depending on the planned workflow this can include RDC, GitHub, Google Drive, local Chrome, native Git authentication, or macOS GUI permissions.

The goal is to avoid stopping halfway through a task to ask for predictable setup. Capabilities that are already connected and still valid are reused during the task. If several connections are missing and the host allows it, Codex Loop should present them as one setup/preflight stage rather than discovering them one by one later.

Preflight does not disable ChatGPT or operating-system security. If the host requires a fresh confirmation for a sensitive individual action, that confirmation still happens at the required boundary. Credentials and approval tokens are never stored in Codex Loop's local config.

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

For requests such as “pull this repository into the Web workspace”, “open the GitHub version here”, or “sync this exact commit into ChatGPT”, Codex Loop uses one verified materialization path:

```text
exact GitHub commit
  -> .github/workflows/workspace-download.yml
  -> commit-bound GitHub Actions artifact
  -> GitHub Connector artifact download
  -> artifact ZIP digest verification
  -> source tarball SHA-256 verification from the same job log
  -> safe extraction into a fresh ChatGPT workspace
```

The workflow should support push-triggered packaging and `workflow_dispatch` for hosts that can explicitly request a fresh artifact. Codex Loop must bind the selected workflow run to the exact `head_sha`; choosing the newest artifact is not enough. If no exact run can be produced or observed, report that acquisition/observability blocker instead of falling back to shell `git clone`, GitHub per-file reconstruction, or generic repository archive URLs.

If an installed Skill is proven by deployment evidence or an audited full manifest to be exactly the latest observed GitHub revision, Codex Loop may copy it once into a fresh workspace as a bootstrap shortcut. This is not allowed when the user explicitly asked to acquire from GitHub, and it never permits editing the installed Skill directory itself.

## Publishing from Web mode

For a repository being developed in the current ChatGPT workspace, the standard GitHub publication path is:

```text
ChatGPT workspace
  -> deterministic source archive + exact size/SHA-256
  -> Google Drive `ChatGPT-GitHub-Staging` via binary file_uri
  -> inherited anyone-with-link read permission verified
  -> tiny GitHub import-request commit
  -> audited `.github/workflows/workspace-import.yml`
  -> runner size/SHA verification + safe extraction
  -> source commit/push
  -> GitHub commit/tree readback
  -> delete the temporary Drive archive
```

### One-time Web-mode setup

This path does **not** require Remote Desktop Commander, a local checkout, local Git, or your computer to stay online. The ChatGPT workspace remains the source of truth and the transfer is completed by connected cloud services.

#### 1. Connect Google Drive to ChatGPT

Connect Google Drive with permission to upload and delete files. In Drive, create a dedicated folder named `ChatGPT-GitHub-Staging` (or another explicitly configured name), then set **Share -> General access -> Anyone with the link -> Viewer**. Keep this folder dedicated to temporary publication archives.

Codex Loop does not hard-code your Drive folder ID. It resolves the configured folder by name or by a folder URL/ID supplied in the conversation, verifies that the folder is `anyone: reader`, uploads the real workspace archive through the connector's binary `file_uri` input, and reads metadata back to confirm the parent folder and byte size.

#### 2. Connect GitHub to ChatGPT

The GitHub connection must have access to the target repository and permission to create or update the small control-plane files used by the importer. Web-mode publication does not require a local `gh` login, a local Git credential helper, or the OAuth `workflow` scope used by Local-mode native Git.

#### 3. Configure GitHub Actions for each target repository

Open **Repository -> Settings -> Actions -> General** and check the following:

- **Actions permissions:** allow GitHub Actions to run for the repository. `Allow all actions and reusable workflows` is the simplest compatible setting unless your organization has a stricter approved policy.
- **Workflow permissions:** select **Read and write permissions** so the import workflow's `GITHUB_TOKEN` can create the verified source commit.
- **Branch rules:** the destination branch must permit the workflow's normal non-force push. Codex Loop never disables branch protection or force-pushes around it. If organization policy blocks the workflow, change the repository/organization policy rather than weakening the importer.

The repository also needs the audited `.github/workflows/workspace-import.yml`. On first use, if it is absent, Codex Loop may bootstrap that small trusted workflow through the GitHub Connector. In an empty repository this control-plane bootstrap can be the first commit; source files themselves must still arrive through Drive -> Actions, not through GitHub contents/blob APIs.

#### 4. What happens on the first and later pushes

When you ask Codex Loop to push a Web-mode workspace, it will:

1. build one deterministic `tar.gz` with exactly one top-level source directory;
2. record the archive byte size and SHA-256;
3. upload the binary archive to the dedicated Drive staging folder and verify inherited public-read metadata;
4. observe the exact GitHub branch head and create one small import-request JSON bound to that base commit, target branch, Drive file ID, size, and SHA-256;
5. wait for the audited Actions workflow to download the archive, verify size/SHA-256, reject unsafe archive entries, and perform a non-force source commit/push;
6. verify the workflow receipt and independently read back the target GitHub branch commit/tree;
7. delete the temporary Drive archive after verified success.

A workflow conclusion of `success` alone is not enough: Codex Loop requires the receipt-bound commit/tree to match the actual target branch before reporting `SOURCE_PUSHED`.

### Web-mode setup checklist

Before the first push to a repository, confirm:

- [ ] Google Drive is connected to ChatGPT with file upload/delete capability.
- [ ] `ChatGPT-GitHub-Staging` exists and is **Anyone with the link -> Viewer**.
- [ ] GitHub is connected to ChatGPT and can write the target repository's small control-plane files.
- [ ] GitHub Actions is enabled for the repository.
- [ ] Workflow permissions are **Read and write permissions**.
- [ ] Branch rules allow the audited workflow's ordinary non-force push.
- [ ] The source can tolerate temporary anyone-with-link readability while staged.

The Drive archive is temporarily anyone-with-link readable. Do not use this path for credentials, private keys, secrets, or source that cannot tolerate that temporary exposure. GitHub Connector writes are control plane only; repository source bytes do not travel through connector-created blobs/trees, model text, or Base64.

A Web-mode `push` does not switch the conversation into Local mode. If the prerequisites are missing or the staging trust boundary is unacceptable, Codex Loop reports the blocker and preserves the Web workspace.

Example prompt:

```text
Use Codex Loop in Web mode to update this repository, test it, and push the current workspace to OWNER/REPO main.
```

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
  -> GitHub Actions source artifact
  -> GitHub Connector artifact download
  -> artifact digest verification
  -> source archive SHA-256 verification
  -> current ChatGPT workspace
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
SOURCE_PUSHED      GitHub matches the audited local commit/tree
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

If your ChatGPT environment exposes no callable Skill-install action, use the product's Save/Update or Skill-install handoff with the validated `skill.zip` when required. For an active current-workspace Skill after a Web-mode push, Codex Loop must surface that handoff rather than merely mention it in a closing note. Do not report `DEPLOYED` merely because Git push, handoff display, or packaging succeeded; require observed update evidence.

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
- Treat native Git commit/tree readback as Local-mode publication success evidence; for Web mode require the archive-bound Actions receipt plus GitHub branch commit/tree readback.
- Treat the public-read Google Drive staging folder as a temporary publication trust boundary and delete staged archives after verified success.
- Do not invent a binary transfer route when no verified bridge exists.
- Never edit an installed Skill in place or treat it as ongoing source authority. A verified-latest installed Skill may only bootstrap a fresh workspace once; downloaded artifacts and copied release folders remain transport/release material rather than development baselines.
- Materialize GitHub source into Web mode through the exact-commit `workspace-download.yml` Actions artifact path, not shell `git clone` or per-file reconstruction.

## Troubleshooting

**Chrome extension is installed but Browser Control is unavailable.** First distinguish host health from session health. If the native messaging host is missing/invalid, use `ChatGPT / Codex -> Settings -> Computer use -> Google Chrome -> Manage / Reconnect`, then recheck. Do not hand-create the manifest or use AppleScript/internal sockets as a substitute. If host health is good but the current conversation still has no Browser executor, classify `SESSION_BROWSER_CAPABILITY_MISSING` and retry from a Browser-capable conversation rather than repairing Chrome again.

**Codex Loop is trying to use the wrong local path.** Explicitly state your absolute RDC-authorized workspace root when entering Local mode. The distributed Skill should contain no author-specific home-directory path.

**RDC cannot access the repository.** Confirm that the repository is under the directory you authorized in Remote Desktop Commander and that the integration is connected.

**A Web-mode push does not start.** Confirm Google Drive is connected, `ChatGPT-GitHub-Staging` is anyone-with-link readable, the target repository has Actions enabled, and workflow permissions allow read/write.

**`git push` fails.** Fix the reported native Git authentication/network/permission/divergence problem on the RDC host. Codex Loop intentionally does not switch to a different source-upload transport.

**A pushed commit is not visible in ChatGPT.** Git push updates GitHub, not the current ChatGPT workspace. Ask to sync the pushed commit and make sure the repository has the audited workspace-download workflow.

**GitHub source cannot be materialized into the Web workspace.** Confirm the repository has the audited `workspace-download.yml`, locate or produce a run bound to the exact target `head_sha`, and verify the artifact can be downloaded through the GitHub Connector. If one query surface cannot observe a push-triggered run, classify that as an observability limitation and inspect the repository's Actions runs through a compatible endpoint; do not conclude that the workflow failed merely from an empty incompatible query.

**A new Skill version is not active after pushing.** For the active Skill being maintained in the current Web workspace, this should now remain an unfinished `DEPLOY_PENDING` workflow rather than a silent success: Codex Loop creates `skill-deploy-handoff`, prefers a supported host-managed update, and otherwise surfaces the Save/Update UI handoff. For other/external Skill copies, Git publication and deployment remain separately requested.

**Local mode disappeared in a new chat.** This is expected. Development mode is conversation-scoped; each new conversation starts in Web mode.

## Development

Run repository-native tests from the repository root. The compatibility suite lives under `tests/compat/`. Source-fidelity checks are required only when upstream-derived resources or their audited mappings change; README and local configuration documentation are local extensions.

See `ATTRIBUTION.md`, `LICENSE`, and `NOTICE` for provenance and licensing information.
