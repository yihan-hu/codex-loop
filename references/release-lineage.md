# Canonical workspace and release lineage

Use Git identity to keep source, audit, packaging, and publishing on one lineage when the current conversation has entered Local mode. This is a Codex Loop local extension; network access, GitHub credentials, connector dispatch, and approval remain host-owned.

## Invariants

1. One task is bound at bootstrap to one canonical Git working tree.
2. All edits, validation, review, release export, and publish planning derive from that bound tree.
3. Installed Skills, copied source directories, release staging directories, and `skill.zip` are artifacts or runtime installations, never later development baselines.
4. Source push, Skill packaging, and ChatGPT deployment are distinct states; success in one does not imply success in the next.
5. Concurrent tasks on one repository use branches plus `git worktree`, so they share Git history and repository identity without sharing one mutable working tree.
6. Release identity is a Git commit/tree pair. Directory mtimes, bundle names, and “latest folder” guesses are not lineage evidence.

The bootstrap binding records the canonical root, a repository id derived from the shared Git common directory, the initial branch, and the base commit/tree. Linked worktrees from one persistent Git repository share the repository id; independent copied/cloned repositories do not.

## Workspace binding

Inspect the task binding with:

```bash
python scripts/codex_loop.py workspace-binding --cwd REPO
```

A task may intentionally move HEAD or branch when Git mutation is authorized, but the canonical root and shared repository identity must continue to match. If the repository behind the bound path is replaced, package/publish operations fail closed.

For multiple conversations/tasks, prefer:

```text
persistent Git repository
  +-- worktree task-A   branch task-A
  +-- worktree task-B   branch task-B
  +-- worktree task-C   branch task-C
```

Do not create `final`, `publish`, `package-src`, or similar full-source copies and then continue development from them.

When the canonical workspace is accessed through Remote Desktop Commander, apply `remote-desktop-boundary.md` first. Keep the canonical repository and every Git worktree inside the task-scoped allowed roots. Do not search outside those roots for another checkout, credential file, release artifact, or package cache. Place disposable release staging, exported receipts, and artifacts only in an explicitly authorized scratch/artifact root.

## Source-only push fast path

In explicit local mode, when the user asks only to commit/push source, keep artifact release work out of the critical path. Validate and review the intended content once, commit it, fetch/observe the remote branch, then plan with:

```bash
python3 scripts/codex_loop.py publish-plan --cwd REPO \
  --repository OWNER/REPO --branch main \
  --remote-head REMOTE_COMMIT --remote-tree REMOTE_TREE --source-only
```

`--source-only` publishes the current clean committed HEAD/tree directly after the normal validation/review and workspace-binding gates. It does not require `release-plan`, `skill.zip`, or `release-record`. Keep packaging/deployment as a later independent stage if the user asks for it.

Freshness is content-addressed. A commit that merely records the already-reviewed Git index while preserving index/worktree/untracked/monitored-ignored content does not invalidate validation or review. A checkout/reset/content change still changes the content fingerprint and stales that evidence.

## Commit-bound release

Release planning requires tracked/staged source to be committed. Untracked files are reported but excluded because export comes from the Git commit, not from a recursive directory copy.

```bash
python scripts/codex_loop.py release-plan --cwd REPO \
  --artifact-name skill.zip --archive-prefix codex-loop
```

The plan returns the canonical commit/tree plus a host-visible `git archive` command. Extract that archive into a disposable directory outside the canonical worktree, run the artifact packager there, verify the artifact, then record the receipt:

```bash
python scripts/codex_loop.py release-record --cwd REPO \
  --artifact-name skill.zip \
  --artifact-sha256 SHA256 \
  --evidence "artifact was built from the planned archive and verified"
```

The receipt is bound to task generation, source commit, source tree, artifact name, and artifact SHA-256. Any later observed workspace mutation makes the receipt stale for publishing. Re-export and re-record instead of treating an old package as a new source baseline.

## Integrated publish flow

For Local mode, Codex Loop uses one verified publish transport only: native Git executed through Remote Desktop Commander on the persistent canonical repository under `LOCAL_ROOT`. GitHub connector/object-API source upload is not a supported fallback. Read `verified-native-git.md` for the end-to-end verified host authentication, native push, and commit/tree readback sequence.

First use native Git in the canonical worktree to fetch/observe the destination branch, then call:

```bash
python scripts/codex_loop.py publish-plan --cwd REPO \
  --repository OWNER/REPO --branch main \
  --remote-head REMOTE_COMMIT --remote-tree REMOTE_TREE
```

The planner reuses the existing audit gates: current-generation validation must pass when required and the final change generation must be reviewed. The observed remote head must be an ancestor of the audited release commit. If not, integrate the remote change in the same canonical worktree and re-run validation/review/release planning. Never force-push around this condition.

A ready plan returns exactly one transport, `git`, with an exact host-visible push command. Before mutation:

```bash
python scripts/codex_loop.py publish-dispatch --cwd REPO \
  --action-id ACTION --transport git
```

Run the returned `git push --porcelain ...` through Remote Desktop Commander from the canonical worktree. Do not reconstruct or relay file payloads through the model. Do not use GitHub object APIs, contents APIs, connector-created blobs/trees/commits, copied directories, release ZIP contents, or model-generated base64 as a publish data plane.

If native Git cannot push because of network, authentication, permissions, branch protection, divergence, or any other error, stop and surface that exact blocker. Do not automatically switch transport. Keep the canonical repo intact so the next session can resume with normal Git.

After a successful push, read back the target ref and tree with native Git. Record success only when both match the audited local release identity exactly:

```bash
python scripts/codex_loop.py publish-record --cwd REPO \
  --action-id ACTION --state terminal_success --transport git \
  --remote-commit AUDITED_LOCAL_COMMIT \
  --remote-tree AUDITED_LOCAL_TREE \
  --evidence "native git remote readback matched the audited commit and tree"
```

If the push outcome is ambiguous, inspect the real remote state with native Git before retrying. Never blindly retry a non-idempotent ref update and never force-push merely to recover from uncertainty.

## Packaging versus ChatGPT deployment

Treat the packaged `skill.zip` as an immutable release artifact derived from the audited Git commit, not as proof that the installed ChatGPT Skill changed. Do not assume local source changes or a successful GitHub push synchronize into ChatGPT automatically. When deployment matters, read `skill-deployment.md`, report the deployment state separately, and require an explicit supported installation/update action or observed user confirmation before calling the Skill deployed.

If an artifact exists only on one side of a ChatGPT/local-host boundary and no verified binary file-transfer bridge is available, stop and explain that boundary. Do not reconstruct the artifact through model-carried chunks, base64, heredocs, repeated file writes, or connector payloads merely to bridge the gap. Use such an alternate data plane only when the user explicitly authorizes that exact method after the limitation and integrity risk are stated.

## Responsibility split

```text
Codex Loop        -> canonical workspace, Git lineage, audit/release receipts, publish plan/state
Git               -> files, modes, commits, trees, ancestry, diffs
Packager          -> audited HEAD export -> skill.zip release artifact
RDC host          -> persistent LOCAL_ROOT filesystem, native Git/network execution, and host-managed credentials
ChatGPT deployment -> explicit install/update of the packaged Skill; never the source baseline
```

This replaces the old “find a folder, compare everything, rebuild a tree, push” pattern. Do not add an implicit transport fallback to hide a missing file-transfer capability.
