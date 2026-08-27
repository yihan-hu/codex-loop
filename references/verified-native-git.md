# Verified RDC native Git path

Use this only after the user explicitly selects local/PiWork development for the current task. It is the proven publishing path for that persistent Mac workflow. This architecture was verified end to end with `yihan-hu/codex-loop`: a non-force native Git push succeeded from the PiWork canonical repository, then native Git readback returned the exact local commit and tree.

## Persistent source and authentication

- In the current local-mode task, keep the canonical repository under `/Users/yihanhu/PiWork` and make that task's source edits there after bootstrap.
- Let Git own repository transport. Do not send source bytes through GitHub connector/object APIs or model-carried payloads.
- Keep host authentication host-owned. Never read or print tokens, SSH keys, or credential-store contents.
- When a global GitHub CLI installation/config is not desired, keep the `gh` binary and config under PiWork, for example `GH_CONFIG_DIR=/Users/yihanhu/PiWork/.gh`.
- Authenticate interactively with `gh auth login --web --git-protocol https`; the user completes the browser/device approval and never sends credentials through chat.
- Bind the GitHub credential helper repo-locally. Clear inherited helper behavior for `https://github.com` before adding a PiWork-local `gh auth git-credential` helper. Do not modify global Git config merely to publish one repository.

A repo-local helper may follow this pattern, with `GH_BIN` resolved to the actual PiWork-managed binary:

```bash
GH_BIN=/Users/yihanhu/PiWork/tools/gh/.../bin/gh
git config --local credential.https://github.com.helper ""
git config --local --add credential.https://github.com.helper \
  "!GH_CONFIG_DIR=/Users/yihanhu/PiWork/.gh $GH_BIN auth git-credential"
```

## Verified push sequence

1. Validate and review the intended final content in the canonical worktree.
2. Commit the source and record the local commit/tree identity. If the commit only records the already-reviewed content, the content-addressed freshness fingerprint remains unchanged; do not rerun validation/review solely because the commit SHA changed.
3. Run `git fetch origin main` and observe the current remote commit/tree. For source-only push requests, use `publish-plan --source-only`; do not package a Skill or create a release receipt first. If lineage diverged, integrate it locally and revalidate; never force around it.
4. Push with native Git from the canonical worktree, for example `GIT_TERMINAL_PROMPT=0 git push --porcelain origin main:main` with the PiWork `GH_CONFIG_DIR` exported when that helper is used.
5. Run native `git fetch origin main` after the push.
6. Require both `git rev-parse HEAD == git rev-parse origin/main` and `git rev-parse HEAD^{tree} == git rev-parse origin/main^{tree}` before recording success.

A transport command returning zero is not enough by itself; commit/tree readback is the success criterion.

## Failure and bootstrap boundaries

If native Git fails because of authentication, network, permissions, branch protection, or divergence, stop and report that blocker. Do not switch to connector source upload, object API writes, force push, or another unverified transport.

A one-time user-authorized bootstrap transfer may be used only to seed a persistent canonical repository when the required source exists solely on another surface and no real binary bridge is available. Verify the transferred artifact/delta hash and the resulting full Git tree before committing. That exception is not part of the normal publish path and never becomes standing authorization for model-carried chunks, base64, heredocs, or repeated remote writes.

Within an explicitly selected local-mode task, perform subsequent edits, tests, commits, packaging, and pushes directly from that persistent repository. The mere existence of a PiWork checkout does not make later tasks local by default; later tasks return to web mode unless the user explicitly selects local development again.

Keep ChatGPT Skill deployment separate from Git publication: build `skill.zip` from the audited final commit, then report deployment as pending until a supported install/update action or user confirmation establishes that the ChatGPT-installed Skill changed.
