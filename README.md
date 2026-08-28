# Codex Loop

Codex Loop is a ChatGPT Skill that applies a Codex-style coding-agent loop to repository work while keeping ChatGPT as the host for reasoning, tools, approvals, connectors, and conversation state.

It combines a deterministic local runtime with host-visible execution so repository changes can be observed, validated, reviewed, committed, published, and audited without launching Codex CLI or another model runtime.

## What it can do

Use Codex Loop for end-to-end repository tasks such as:

- implementing features and refactors;
- fixing bugs, tests, and CI failures;
- investigating or reviewing a codebase;
- running repository-native validation;
- tracking acceptance criteria and review freshness;
- keeping repository `workspace_mode` independent from browser/computer `interaction_target`;
- controlling a user's local Chrome through a supported native bridge or RDC-backed structured Chrome automation without launching a local Codex agent;
- preflighting required RDC, GitHub, Google Drive, browser, and host permissions before substantive multi-step execution;
- publishing Web-mode workspace source through verified Drive staging + GitHub Actions, or Local-mode source through native Git;
- packaging ChatGPT Skills;
- synchronizing a verified local GitHub commit back into the current ChatGPT workspace;
- degrading requested reviewer/researcher/tester delegation to a bounded logical isolation when native subagents are unavailable.

Codex Loop is not Codex CLI and does not contain a model runtime. ChatGPT remains the execution host.

## Install as a ChatGPT Skill

This repository is the Skill source. A Git checkout or ordinary source ZIP is not automatically an installed ChatGPT Skill. Package the repository with the standard ChatGPT Skill packaging flow into a validated archive named exactly `skill.zip`, then upload/update that package in the ChatGPT Skills UI (or use a supported install/update action when your environment exposes one).

Keep source publication and Skill installation separate: pushing this repository to GitHub does not update an installed copy by itself.

## Quick start

After installing the Skill, ordinary coding requests use **Web mode** by default in every new conversation. Work happens in the current ChatGPT workspace and the result is returned with normal downloadable files or links.

Example prompts:

```text
Use Codex Loop to fix this bug.
Add this feature and run the relevant tests.
Review this repository and fix the issues you find.
```

You do not need Remote Desktop Commander for ordinary Web-mode repository work. However, Web mode may still use RDC for **interaction-only** tasks such as controlling your local Chrome or macOS UI; that does not move the repository source of truth onto the Mac.

If you ask to push from Web mode, Codex Loop keeps the current workspace authoritative and uses the verified Google Drive -> GitHub Actions publication path when its prerequisites are configured.

To use a persistent repository on your own computer, explicitly enter **Local mode**:

```text
Use local development for this repository.
Use Codex Loop locally under /Users/alice/PiWork and fix this bug.
```

Once Local mode is selected, later repository tasks in the same conversation keep using Local mode unless you explicitly switch back to Web mode. A new conversation starts in Web mode again.

## Local mode requirements

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

To remember a non-sensitive default root on one computer, create the host-local file `~/.codex-loop/host.json`:

```json
{
  "schema_version": 1,
  "default_local_root": "/Users/alice/PiWork"
}
```

This file is deliberately outside every repository and outside the packaged Skill. Git commits, GitHub pushes, Web-mode source archives, and `skill.zip` must not include it. Do not put tokens, passwords, cookies, OAuth credentials, or approval state in this file.

## Workspace mode versus interaction target

Codex Loop treats **where the repository lives** and **which computer/browser is being controlled** as separate axes:

```text
workspace_mode:      web | local
interaction_target:  none | cloud_browser | local_chrome | local_mac_gui
```

For example, `workspace_mode=web` plus `interaction_target=local_chrome` means the repository remains in the current ChatGPT workspace while ChatGPT uses your Mac only to interact with your signed-in local Chrome. Using RDC for that interaction does not make the Mac checkout authoritative.

For `local_chrome`, Codex Loop keeps ChatGPT as the reasoning authority and does not launch a local Codex agent. It prefers an official host-exposed Chrome/Computer Use bridge when available; otherwise on macOS it can use RDC-backed structured Chrome automation. Generic screenshot plus mouse/keyboard automation is a fallback only when structured control is insufficient.

The RDC-backed Chrome path has been validated end to end with a harmless test: create `about:blank`, independently confirm the tab exists, close only that test tab, then independently confirm it is gone.

## Capability and permission preflight

For multi-step work, Codex Loop should determine the required integrations before substantive execution and check them together. Depending on the planned workflow this can include RDC, GitHub, Google Drive, local Chrome, native Git authentication, or macOS GUI permissions.

The goal is to avoid stopping halfway through a task to ask for predictable setup. Capabilities that are already connected and still valid are reused during the task. If several connections are missing and the host allows it, Codex Loop should present them as one setup/preflight stage rather than discovering them one by one later.

Preflight does not disable ChatGPT or operating-system security. If the host requires a fresh confirmation for a sensitive individual action, that confirmation still happens at the required boundary. Credentials and approval tokens are never stored in Codex Loop's local config.

## Web mode versus Local mode

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
DEPLOY_PENDING     package exists but the installed Skill is not yet confirmed updated
DEPLOYED           an explicit supported install/update action or user confirmation proves installation
```

When packaging Codex Loop as a ChatGPT Skill, validate the Skill directory and produce a ZIP named exactly `skill.zip`. The repository source itself is not proof of installation.

If your ChatGPT environment exposes no callable Skill-install action, upload the validated `skill.zip` through the ChatGPT Skills UI. Do not report `DEPLOYED` merely because Git push or packaging succeeded.

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
- Do not treat an installed Skill, downloaded archive, or copied release folder as the canonical development source.

## Troubleshooting

**Codex Loop is trying to use the wrong local path.** Explicitly state your absolute RDC-authorized workspace root when entering Local mode. The distributed Skill should contain no author-specific home-directory path.

**RDC cannot access the repository.** Confirm that the repository is under the directory you authorized in Remote Desktop Commander and that the integration is connected.

**A Web-mode push does not start.** Confirm Google Drive is connected, `ChatGPT-GitHub-Staging` is anyone-with-link readable, the target repository has Actions enabled, and workflow permissions allow read/write.

**`git push` fails.** Fix the reported native Git authentication/network/permission/divergence problem on the RDC host. Codex Loop intentionally does not switch to a different source-upload transport.

**A pushed commit is not visible in ChatGPT.** Git push updates GitHub, not the current ChatGPT workspace. Ask to sync the pushed commit and make sure the repository has the audited workspace-download workflow.

**A new Skill version is not active after pushing.** Git publication and Skill deployment are separate. Build/validate `skill.zip`, then use a supported ChatGPT install/update action.

**Local mode disappeared in a new chat.** This is expected. Development mode is conversation-scoped; each new conversation starts in Web mode.

## Development

Run repository-native tests from the repository root. The compatibility suite lives under `tests/compat/`. Source-fidelity checks are required only when upstream-derived resources or their audited mappings change; README and local configuration documentation are local extensions.

See `ATTRIBUTION.md`, `LICENSE`, and `NOTICE` for provenance and licensing information.
