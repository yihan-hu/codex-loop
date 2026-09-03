# Verified RDC native Git path

Use this only after the current conversation has entered Local mode and resolved an RDC-authorized `LOCAL_ROOT`. It is the publishing path for a persistent local Git workflow on RDC-backed macOS or Windows hosts. The end-to-end reference verification was performed on macOS with `yihan-hu/codex-loop`: a non-force native Git push succeeded from the canonical repository, then native Git readback returned the exact local commit and tree. Windows uses the same native-Git identity contract on a best-effort/beta basis; Windows-specific shell/runtime gaps stay host-visible or fail only the affected operation.

## Persistent source and authentication

- While the current conversation is in Local mode, keep each task's canonical repository under `LOCAL_ROOT` and make that task's source edits there after bootstrap.
- Let Git own repository transport. Do not send source bytes through GitHub connector/object APIs or model-carried payloads.
- Keep host authentication host-owned. Never read or print tokens, SSH keys, or credential-store contents.
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
2. Commit the source and record the local commit/tree identity. If the commit only records already-reviewed content, do not rerun validation/review solely because the commit SHA changed unless the runtime freshness gate requires it.
3. Run `git fetch origin main` and observe the current remote commit/tree. For source-only push requests, use `publish-plan --source-only`; do not package a Skill or create a release receipt first. If lineage diverged, integrate it locally and revalidate; never force around it.
4. Push with native Git from the canonical worktree, for example `GIT_TERMINAL_PROMPT=0 git push --porcelain origin main:main`, with a `GH_CONFIG_DIR` derived from `LOCAL_ROOT` when that helper layout is used.
5. Run native `git fetch origin main` after the push.
6. Require both `git rev-parse HEAD == git rev-parse origin/main` and `git rev-parse HEAD^{tree} == git rev-parse origin/main^{tree}` before recording success.

A transport command returning zero is not enough by itself; commit/tree readback is the success criterion.

## Failure and bootstrap boundaries

If native Git fails because of authentication, network, permissions, branch protection, or divergence, stop and report that blocker. Do not switch to connector source upload, object API writes, force push, or another unverified transport.

A one-time user-authorized bootstrap/handoff transfer may be used to seed or update the persistent canonical repository when the audited source exists on another surface. Prefer a real binary bridge: for Web -> Local recovery, build the exact verified Git bundle in Web mode, transfer that binary through the approved Drive/direct bridge, verify size + SHA-256 + `git bundle verify`, fetch the declared ref, and require local commit/tree == audited Web commit/tree before native Git publication. Do not regenerate, retype, or reconstruct repository source through model text. `references/web-to-local-handoff.md` defines this recovery path. A model-carried verified relay remains an explicit last-resort transport only when the user separately authorizes it.

Within a conversation that has explicitly entered Local mode, perform subsequent repository tasks through the persistent workspace under `LOCAL_ROOT` without requiring the user to repeat the mode selection. A new conversation starts in Web mode again; the existence of a local checkout never creates a permanent cross-conversation preference.

Keep ChatGPT Skill deployment separate from Git publication: build `skill.zip` from the audited final commit, then report deployment as pending until a supported install/update action or user confirmation establishes that the ChatGPT-installed Skill changed.
