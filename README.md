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
- committing and publishing source with verified Git lineage;
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

You do not need Remote Desktop Commander for Web mode.

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

`LOCAL_ROOT` is a runtime placeholder, not a path baked into the distributed Skill and not necessarily an operating-system environment variable. Configure that directory as an allowed directory in RDC, then tell Codex Loop the absolute path when you first select Local mode in a conversation.

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

Each durable runtime task still has its own repository/worktree binding even though the development-location choice persists for the conversation.

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
- Treat native Git commit/tree readback as publication success evidence.
- Do not invent a binary transfer route when no verified bridge exists.
- Do not treat an installed Skill, downloaded archive, or copied release folder as the canonical development source.

## Troubleshooting

**Codex Loop is trying to use the wrong local path.** Explicitly state your absolute RDC-authorized workspace root when entering Local mode. The distributed Skill should contain no author-specific home-directory path.

**RDC cannot access the repository.** Confirm that the repository is under the directory you authorized in Remote Desktop Commander and that the integration is connected.

**`git push` fails.** Fix the reported native Git authentication/network/permission/divergence problem on the RDC host. Codex Loop intentionally does not switch to a different source-upload transport.

**A pushed commit is not visible in ChatGPT.** Git push updates GitHub, not the current ChatGPT workspace. Ask to sync the pushed commit and make sure the repository has the audited workspace-download workflow.

**A new Skill version is not active after pushing.** Git publication and Skill deployment are separate. Build/validate `skill.zip`, then use a supported ChatGPT install/update action.

**Local mode disappeared in a new chat.** This is expected. Development mode is conversation-scoped; each new conversation starts in Web mode.

## Development

Run repository-native tests from the repository root. The compatibility suite lives under `tests/compat/`. Source-fidelity checks are required only when upstream-derived resources or their audited mappings change; README and local configuration documentation are local extensions.

See `ATTRIBUTION.md`, `LICENSE`, and `NOTICE` for provenance and licensing information.
