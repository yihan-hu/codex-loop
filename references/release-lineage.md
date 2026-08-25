# Canonical workspace and release lineage

Use Git identity to keep source, audit, packaging, and publishing on one lineage. This is a Codex Loop local extension; network access, GitHub credentials, connector dispatch, and approval remain host-owned.

## Invariants

1. One task is bound at bootstrap to one canonical Git working tree.
2. All edits, validation, review, release export, and publish planning derive from that bound tree.
3. Installed Skills, copied source directories, release staging directories, and `skill.zip` are artifacts or runtime installations, never later development baselines.
4. Concurrent tasks on one repository use branches plus `git worktree`, so they share Git history and repository identity without sharing one mutable working tree.
5. Release identity is a Git commit/tree pair. Directory mtimes, bundle names, and “latest folder” guesses are not lineage evidence.

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

Codex Loop owns publish lineage and planning. The host owns transport.

First observe the destination branch's current commit (and tree when connector fallback may be needed). Then call:

```bash
python scripts/codex_loop.py publish-plan --cwd REPO \
  --repository OWNER/REPO --branch main \
  --remote-head REMOTE_COMMIT --remote-tree REMOTE_TREE
```

The planner reuses the existing audit gates rather than inventing a second release checklist: current-generation validation must pass when validation is required, and the current change generation must be reviewed. It also requires the observed remote head to be an ancestor of the audited release commit. If it is not, stop publishing and integrate the remote change in the same canonical worktree. Never force-push merely to bypass this condition. The non-idempotent publish identity is bound to repository, branch, and source commit (not only the tree), so two release commits with identical file trees cannot silently reuse one external action.

The plan prefers ordinary Git when a configured remote plus host network/credentials make it available:

```text
verify remote head still matches plan
-> publish-dispatch --transport git
-> run the exact host-visible git push
-> read back remote ref/tree
-> publish-record terminal_success
```

Before the external mutation:

```bash
python scripts/codex_loop.py publish-dispatch --cwd REPO \
  --action-id ACTION --transport git
```

After readback:

```bash
python scripts/codex_loop.py publish-record --cwd REPO \
  --action-id ACTION --state terminal_success --transport git \
  --remote-commit COMMIT --remote-tree TREE \
  --evidence "remote ref/tree read back after push"
```

For ordinary Git transport, successful readback must show the exact audited local commit and tree.

## GitHub object API fallback

If ordinary Git transport is unavailable but a GitHub connector is available, use the plan's `github_object_api` section. Do not rescan the working directory or reconstruct “latest files” independently.

The fallback manifest comes from `git diff-tree` between the observed remote head and the audited release commit. For each changed path it identifies Git mode, old/new object SHA, deletion state, and blob size, then classifies the transport as `inline_utf8`, `create_blob`, `tree_delete`, or `unsupported` using the committed Git object bytes. The base tree is derived from the locally known observed-remote-head commit; a separately observed remote tree is optional consistency evidence, not a second source of truth. Use that manifest as the source of truth:

1. Recheck that the remote branch still points at the planned remote head.
2. Mark the publish action dispatched with `--transport github_object_api` immediately before the first write.
3. Follow the manifest's transfer classification without rescanning the working directory:
   - `inline_utf8`: materialize the exact target Git blob bytes by object id, strict-decode UTF-8, and place the file `content` directly in the single `create_tree` request. Codex Loop budgets this fast path conservatively at <=128 KiB per entry, <=512 KiB total inline content, and <=128 inline entries.
   - `create_blob`: upload that Git blob separately (UTF-8 or base64 as appropriate), then reference the returned/verified blob SHA from the tree entry. Binary/non-UTF-8, NUL-containing, oversized, or over-budget content uses this path.
   - `tree_delete`: represent the deletion in the same `create_tree` request with a null SHA.
   - `unsupported`: stop connector fallback; never flatten gitlinks/submodules or unsupported Git object types.
When the host connector itself is fast but every call is serialized through the model, prefer the short-term **model-dispatch queue** instead of repeatedly probing for missing blobs. This path intentionally uploads every changed blob, even if GitHub may already have the same content, because `create_blob` is content-addressed/idempotent and avoiding per-object existence probes removes an entire connector round trip per file. It uses exact Git blob bytes, base64-encodes them, and exposes bounded batches (default: at most 8 items and about 96 KiB raw content per batch; one oversized item may occupy a batch alone).

```bash
python scripts/codex_loop.py publish-transfer-start --cwd REPO --action-id ACTION
# Dispatch the returned create_blob calls in order, with no intermediate reasoning/tree probe.
python scripts/codex_loop.py publish-transfer-ack --cwd REPO --action-id ACTION \
  --returned-shas-json '["SHA1","SHA2"]'
# Repeat the returned next batch; use status to resume after interruption.
python scripts/codex_loop.py publish-transfer-status --cwd REPO --action-id ACTION
# After all blobs are acknowledged, dispatch the single returned create_tree call.
python scripts/codex_loop.py publish-transfer-tree-ack --cwd REPO --action-id ACTION \
  --returned-tree TREE_SHA
```

The queue stores only a Git-derived queue digest, cursor, and compact progress metadata in task state; source payloads are regenerated from immutable Git objects on demand and are never persisted in SQLite. A batch acknowledgement must contain exactly the returned SHAs for the current batch in order. Any mismatch or out-of-order acknowledgement fails without advancing the cursor. Re-running `publish-transfer-start` or `publish-transfer-status` is resumable. Once all blob batches are verified, the runtime emits exactly one `create_tree` request whose entries reference the expected Git blob SHAs and represent deletions with `sha: null`; there is no per-blob tree probe. Blob and tree creation are replay-safe because the objects are content-addressed. The dispatcher stops after exact tree verification and only returns a commit plan; `create_commit` remains under the normal non-idempotent outcome discipline and must not be blindly replayed after an unknown result.

4. Create exactly one tree using the observed remote tree as the base, combining all inline text entries, separately uploaded blob SHAs, and deletions. Never send both `sha` and `content` for one entry. Require the returned tree SHA to equal the audited target tree SHA before creating a commit.
5. Create one commit with the observed remote head as parent, using the local commit metadata when the connector supports it.
6. Recheck the remote head if concurrent change is plausible, then perform one non-force branch-ref update.
7. Read back the remote commit/tree and record the terminal outcome.

The object API may synthesize a commit SHA different from the local commit if the connector cannot reproduce all commit headers. That is acceptable only when readback proves the remote tree equals the audited release tree **and** the synthesized commit parent equals the planned remote head. The receipt records the local source commit, remote transport commit, remote tree, and observed parent. The source/audit identity remains the local commit/tree pair. When the transport commit differs, `publish-record` reports `requires_local_reconciliation: true`; import/integrate that observed remote commit into the canonical repository before planning another publish, so connector fallback never creates a silent long-lived lineage fork.

Example terminal record:

```bash
python scripts/codex_loop.py publish-record --cwd REPO \
  --action-id ACTION --state terminal_success --transport github_object_api \
  --remote-commit REMOTE_COMMIT --remote-tree AUDITED_TREE \
  --remote-parent PLANNED_REMOTE_HEAD \
  --evidence "connector ref readback matches the audited release tree and parent"
```

If the outcome is ambiguous, record `outcome_unknown`, inspect the real remote state, and reconcile from observation. Never blindly retry a non-idempotent publish.

## Responsibility split

```text
Codex Loop   -> canonical workspace, Git lineage, audit/release receipts, publish plan/state
Git          -> files, modes, commits, trees, ancestry, diffs
Packager     -> audited HEAD export -> artifact
Host         -> Git/network/connector execution and credentials
```

This replaces the old “find a folder, compare everything, rebuild a tree, push” pattern. A transfer helper may still exist as a transport adapter, but it must consume Codex Loop's Git-derived plan rather than deciding source lineage itself.
