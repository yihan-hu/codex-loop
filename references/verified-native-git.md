# Verified local native Git path

Use this only after the current conversation has entered Local mode and resolved an local connector-authorized `LOCAL_ROOT`. It is the publishing path for a persistent local Git workflow on local-connector-backed macOS or Windows hosts. The end-to-end reference verification was performed on macOS against the canonical maintainer repository: a non-force native Git push succeeded from the canonical repository, then native Git readback returned the exact local commit and tree. Windows uses the same native-Git identity contract on a best-effort/beta basis; Windows-specific shell/runtime gaps stay host-visible or fail only the affected operation.

## Persistent source and authentication

- While the current conversation is in Local mode, keep each task's canonical repository under `LOCAL_ROOT` and make that task's source edits there after bootstrap.
- Let Git own repository transport. Do not send source bytes through GitHub connector/object APIs or model-carried payloads.
- Keep host authentication host-owned. Never read or print tokens, SSH keys, or credential-store contents.
- Host Profile `workspace.environments[computer].git_auth` records the last successful nonsecret credential source: `gh_cli`, `osxkeychain`, or `windows_gcm`. The Local publication controller applies it directly to the native push command, overriding conflicting repository helper settings for that command. Do not probe helper configuration or run a dry-run on every push. Credentials remain in the host credential store; Host Profile never contains tokens.
- When a global GitHub CLI installation/config is not desired, a `gh` binary and config may be kept under `LOCAL_ROOT`, for example `GH_CONFIG_DIR="$LOCAL_ROOT/.gh"`.
- Authenticate interactively with `gh auth login --web --git-protocol https`; the user completes the browser/device approval and never sends credentials through chat.
- Bind the GitHub credential helper repo-locally when needed. Do not modify global Git config merely to publish one repository.

A repo-local helper may follow this POSIX/macOS pattern after substituting the real root in the host shell. On Windows, prefer the host's normal Git Credential Manager / `gh auth login --web --git-protocol https` flow from PowerShell instead of translating this shell snippet literally:

```bash
LOCAL_ROOT=/Users/alice/PiWork
GH_BIN="$LOCAL_ROOT/tools/gh/.../bin/gh"
git config --local credential.https://github.com.helper ""
git config --local --add credential.https://github.com.helper \
  "!GH_CONFIG_DIR=$LOCAL_ROOT/.gh $GH_BIN auth git-credential"
```

The example root is illustrative only; use the root resolved for the current conversation.

## Verified push sequence

1. Validate and review the intended final content in the canonical worktree.
2. Commit the source and record the local commit/tree identity. If the commit only records already-reviewed content, do not rerun validation solely because the commit SHA changed unless the runtime freshness gate requires it.
3. Run `git fetch origin main` and observe the current remote commit/tree before publication. Route the push through the **bundled Codex Loop controller**; its Local `publish-enter --controller-abi 1 --workspace-granted` helper may plan the exact native-Git action, but the target repository itself does not need `scripts/codex_loop.py` or any Codex Loop runtime file. Do not package a Skill or create a release receipt first. If lineage diverged, integrate it locally and revalidate; never force around it.
4. Execute `planner_result.git.argv` with its returned environment directly on the pinned host. Never silently switch host or use GitHub connector object uploads. If authentication clearly fails, diagnose and try another already-available credential source on **the same host**; reconcile an ambiguous push with the exact target remote ref before any retry. Do not force-push or alter the source commit.
5. If native Git returns a clean terminal success and porcelain reports the intended ref update as accepted, accept it without a redundant readback. For an ambiguous result, inspect `git ls-remote origin refs/heads/main` before any retry and accept success only if the exact audited commit matches.
6. After successful publication, if `git_auth` was missing or stale, save the effective nonsecret credential source into only `workspace.environments[computer].git_auth` of the controller-restored Host Profile. Export, update the original verified private Drive file ID, and fetch/compare complete bytes, preserving unrelated settings. Never persist credentials or repeat a successful push merely because the preference save failed; report push success and profile persistence separately.

Do not turn a clean successful push into a mandatory second readback ceremony. Remote observation is an exception path for ambiguity/concurrency or when the user explicitly asks for current remote state.

## Failure and bootstrap boundaries

If the first native Git push fails, diagnose on the same host and retry only after resolving a clear failure and checking any ambiguous remote outcome. If network, permissions, branch protection, or divergence remain blocked, stop and report that blocker. Do not switch to connector source upload, object API writes, force push, or another unverified transport.

A one-time user-authorized bootstrap/handoff transfer may be used to seed or update the persistent canonical repository when the audited source exists on another surface. For Web -> Local/Mac transfer there is one fixed path: exact verified self-contained Git bundle -> Google Drive binary staging -> local connector download to the explicitly authorized local path -> local size/SHA-256 + `git bundle verify`. Require local commit/tree == audited Web commit/tree before native Git publication. Do not substitute a direct bridge, GitHub artifact/archive, model relay, or source reconstruction. `references/web-to-local-handoff.md` defines this path.

Within a conversation that has entered Local mode through an explicit choice or saved default, perform subsequent repository tasks through the persistent workspace under `LOCAL_ROOT` without requiring the user to repeat the mode selection. A new conversation uses the saved execution default, otherwise Web; a checkout’s existence alone never selects a computer. Connection choice follows `local-connections.md`.

Keep ChatGPT Skill deployment separate from Git publication: build `skill.zip` from the audited final commit, then report deployment as pending until a supported install/update action or user confirmation establishes that the ChatGPT-installed Skill changed.
