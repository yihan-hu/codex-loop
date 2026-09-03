# Codex Loop consumer onboarding

Use this guide only when the user is setting up Codex Loop or when the current task first needs one of these capabilities. Do not make optional integrations prerequisites for ordinary Codex Loop use.

## Choose the smallest setup that matches the task

### Level 0 — Use Codex Loop in ChatGPT

Required: the Codex Loop Skill only.

Not required: GitHub, Google Drive, access to or a fork of the maintainer repository, Remote Desktop Commander (RDC), a local checkout, or any repository-specific setup.

A consumer installation has no default repository binding. Any maintainer/release repository is provenance context, not the consumer's repository. Never ask a consumer to connect, fork, or authorize that repository merely to use Codex Loop.

### Level 1 — Work with a repository from ChatGPT Web

Add GitHub only when the task needs repository reads, source acquisition, Actions, or publication.

1. Connect the GitHub integration that ChatGPT will use.
2. Grant access only to the repository or repositories the user actually wants Codex Loop to work with.
3. Do not infer a repository from Codex Loop's package, release metadata, a maintainer repository, memory, or another conversation. Resolve it from the current task.
4. For exact GitHub -> Web source acquisition, the target repository needs the audited `.github/workflows/workspace-download.yml` contract or an explicitly equivalent supported source artifact path.

If the task only reads a repository, stop here. Google Drive is not required for read-only GitHub work.

### Level 2 — Publish a Web workspace back to GitHub

Web publication adds Google Drive because Codex Loop uses a binary staging bridge rather than sending source bytes through GitHub connector payloads.

One-time setup:

1. Connect/install the Google Drive integration available to ChatGPT.
2. In Google Drive, create a dedicated folder named `ChatGPT-GitHub-Staging`.
3. Set that folder to **Anyone with the link -> Viewer/reader**. This is required so the audited GitHub-hosted runner can download the staged bundle without Google credentials. The current Drive connector may not expose public folder-sharing controls, so this permission can require a one-time manual Drive UI step.
4. Copy the folder ID from its Drive URL. Optionally store the non-sensitive locator in Codex Loop's private Host Profile:

```bash
python3 scripts/codex_loop.py host-config set web_publish.staging_folder_id DRIVE_FOLDER_ID
```

5. Ensure the target repository has GitHub Actions enabled and contains the audited import workflow used by Codex Loop. The standard `workspace-import.yml` / `workspace-import-fast.yml` path requires `contents: write`; `workspace-download.yml` needs `contents: read`.
6. If repository or organization policy restricts the workflow token to read-only, change the repository/organization Actions workflow-permission policy so the import workflow can receive the declared write permission. Do not weaken unrelated branch or organization protections.
7. Keep branch/ruleset protections compatible with Codex Loop's verified, lease-guarded publication path. If policy blocks it, report that exact blocker rather than bypassing protections.

Security boundary: files staged in `ChatGPT-GitHub-Staging` are temporarily readable by anyone who has the link. Codex Loop deletes the exact staging object after verified consumption. Do not use this Web publication path for source that cannot tolerate that temporary exposure.

Before the first publish, a useful request is: `Check my Codex Loop Web publishing setup before changing anything.` Codex Loop should preflight GitHub push permission, GitHub Actions, and Google Drive write access and report only the missing prerequisites.

### Level 3 — Control a local Mac / use a persistent local repository

RDC is optional. Set it up only when the user explicitly wants local files, native Git, local Chrome, or macOS GUI control.

1. Install/connect Remote Desktop Commander to the Mac or other supported machine.
2. Choose a persistent development root (`LOCAL_ROOT`) and authorize that directory in RDC. Keep repositories used by Codex Loop under that root unless a narrower extra path is explicitly granted.
3. If helpful, register the root as a private alias such as `piwork`; registration remembers identity, not access permission.
4. Ensure native Git authentication on that host works for the repositories the user intends to publish.
5. Explicitly select Local workspace mode when the local checkout should become the development baseline. RDC availability by itself never selects Local mode.
6. Local source edits still require current-task authorization. Local Chrome or macOS GUI interaction also requires explicit computer-use authorization for that task.

RDC can also be used only as an interaction adapter while repository development remains in Web mode. Do not equate “use my Mac/Chrome” with “make my Mac checkout the source of truth.”

## First-run behavior for Codex Loop

When setup is missing, disclose dependencies progressively:

- Base ChatGPT objective: ask for nothing extra.
- GitHub repository task: ask only for the relevant GitHub connection/access.
- Web publication: additionally explain the Drive staging folder and Actions write-policy prerequisites.
- Local filesystem/native Git/browser/GUI task: additionally explain RDC and the relevant path/computer authorization.

Never present all four integrations as a mandatory installation checklist. Prefer a bounded preflight that tests the exact capabilities needed by the current task and tells the user what remains to configure.
