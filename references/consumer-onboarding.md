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

### Level 2 — Use the Web binary staging bridge / publish back to GitHub

Ordinary Web -> Mac/local file transfer and Web publication use Google Drive as the verified binary staging bridge. Web publication additionally uses the audited GitHub control plane.

One-time setup:

1. Connect/install the Google Drive integration available to ChatGPT.
2. In Google Drive, create the fixed temporary root `ChatGPT-Temporary`, then create `codex-loop/github-staging` beneath it. Keep the temporary root itself private; only the publication staging child needs the configured anyone-with-link read boundary.
3. Set that folder to **Anyone with the link -> Viewer/reader**. This is required so the audited GitHub-hosted runner can download the staged bundle without Google credentials. The current Drive connector may not expose public folder-sharing controls, so this permission can require a one-time manual Drive UI step.
4. Copy the folder ID from its Drive URL. Optionally store the non-sensitive locator in Codex Loop's private Host Profile:

```bash
python3 scripts/codex_loop.py host-config set web_publish.staging_folder_id DRIVE_FOLDER_ID
```

5. Ensure the target repository has GitHub Actions enabled and contains the audited import workflow used by Codex Loop. The standard `workspace-import.yml` / `workspace-import-fast.yml` path requires `contents: write`; `workspace-download.yml` needs `contents: read`.
6. If repository or organization policy restricts the workflow token to read-only, change the repository/organization Actions workflow-permission policy so the import workflow can receive the declared write permission. Do not weaken unrelated branch or organization protections.
7. Keep branch/ruleset protections compatible with Codex Loop's verified, lease-guarded publication path. If policy blocks it, report that exact blocker rather than bypassing protections.

Security boundary: files staged in `ChatGPT-Temporary/codex-loop/github-staging` are temporarily readable by anyone who has the link. Ordinary Web -> local transfer uses the sibling `ChatGPT-Temporary/codex-loop/handoff` boundary; both remain under the one fixed temporary root. Codex Loop cleans up only the exact staging object after verified consumption, subject to the global Drive cleanup gate; the explicit transfer/publish request supplies the per-object cleanup intent, so no second cleanup confirmation is required. Do not use this staging boundary for source or files that cannot tolerate that temporary exposure.

Before the first publish, a useful request is: `Check my Codex Loop Web publishing setup before changing anything.` Codex Loop should preflight GitHub push permission, GitHub Actions, and Google Drive write access and report only the missing prerequisites.

### Level 3 — Control a local Mac / use a persistent local repository

Local connections are optional. For local files/native Git, prefer a custom file/shell MCP, then Remote Desktop Commander (RDC). Browser/GUI control needs its own supported capability. Read `local-connections.md` for connection priorities and private execution defaults.

For guided macOS setup, use [the local MCP tutorial](local-mcp-tutorial.md), including the restricted runtime key, ChatGPT workspace association, actual file/shell verification, payment-stop rule, and private preference registration. Do not require this setup for ordinary Web objectives.

1. Connect the selected custom MCP (or RDC) to the intended computer; observe its actual file/shell capabilities.
2. Choose a persistent development root (`LOCAL_ROOT`) and confirm the selected connector permits that directory. Keep repositories used by Codex Loop under that root unless a narrower extra path is explicitly granted.
3. If helpful, register the root as a private alias such as `piwork`; registration remembers identity, not access permission.
4. Ensure native Git authentication on that host works for the repositories the user intends to publish.
5. Select Local for this task, or save that computer as `execution.default_target`. A one-task override does not overwrite the saved default; connectivity alone does not select Local.
6. Local source edits still require current-task authorization. Local Chrome or macOS GUI interaction also requires explicit computer-use authorization for that task.

RDC can also be used only as an interaction adapter while repository development remains in Web mode. Do not equate “use my Mac/Chrome” with “make my Mac checkout the source of truth.”

## First-run behavior for Codex Loop

When setup is missing, disclose dependencies progressively:

- Base ChatGPT objective: ask for nothing extra.
- GitHub repository task: ask only for the relevant GitHub connection/access.
- Web publication: additionally explain the Drive staging folder and Actions write-policy prerequisites.
- Local filesystem/native Git/browser/GUI task: additionally explain the selected local connector and the relevant path/computer authorization.

Never present all four integrations as a mandatory installation checklist. Prefer a bounded preflight that tests the exact capabilities needed by the current task and tells the user what remains to configure.

For preferences across new chats, follow [Drive-first Host Profile recovery](host-profile-drive.md). It uses only the current connected user's fixed `codex-loop/settings/host-profile.json`, before selecting Web or a computer. Disconnected Drive uses defaults; recovery errors are reported. This does not resume tasks.
