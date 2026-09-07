# Repository continuity: HOT -> WARM -> COLD

Use this reference at the start of repository-development work after routing and before source acquisition. The objective is Git-like continuity: once a canonical Git workspace exists, ordinary `edit -> commit -> push` must remain incremental. Full source acquisition is disaster recovery, not the normal entry path.

## Core invariant

```text
repository-enter
  -> HOT_REUSE
  -> WARM_RESTORE_WORKSPACE_CACHE
  -> WARM_RESTORE_PUBLISHED_SOURCE
  -> COLD_ACQUIRE_REQUIRED
```

`HOT_REUSE` always wins. A real existing Git worktree is reusable when the canonical repository origin and branch match, history is non-shallow, and the current HEAD still descends from the verified provenance base when provenance is supplied.

The runtime separates two identities:

- `source_provenance`: repository/branch/base commit/base tree proof. It is deliberately `path_bound=false` and can survive a new workspace path.
- `workspace_lease`: the current concrete Git working tree (`canonical_root`, Git common-dir identity, current HEAD/tree). It is `path_bound=true` and may be reissued after a verified restore.

A missing path or changed temporary directory therefore invalidates only the old workspace lease. It does not erase verified Git provenance.

## Command

```bash
python3 scripts/codex_loop.py repository-enter \
  --session-id ROUTING_SESSION \
  --cwd /CURRENT/OR/EXPECTED/WORKSPACE \
  --repository OWNER/REPO \
  --branch main \
  --remote-head FULL_REMOTE_COMMIT \
  --remote-tree FULL_REMOTE_TREE \
  [--source-provenance-json provenance.json] \
  [--workspace-cache-json cache-metadata.json] \
  [--published-source-json fast-import-receipt.json]
```

`remote-head` and `remote-tree` are optional as a pair. When supplied they classify synchronization state; they are not allowed to invalidate a valid HOT source merely because the remote moved.

## HOT behavior

A successful HOT result returns:

```text
status = HOT_REUSE
source_reacquisition_required = false
workspace_restore_required = false
```

Remote state is classified separately:

- `IN_SYNC`: continue normally.
- `LOCAL_AHEAD`: continue to incremental publish.
- `REMOTE_HEAD_UNSEEN`: fetch only the missing remote Git objects, then classify ancestry.
- `REMOTE_AHEAD`: fast-forward/rebase in the existing workspace.
- `DIVERGED`: merge/rebase in the existing workspace.
- `REMOTE_OBSERVATION_MISMATCH`: re-observe the remote identity.

None of these states means “clone/download the whole repository again.” In particular:

```text
REMOTE_HEAD_MOVED != SOURCE_IDENTITY_STALE
```

## WARM behavior

If HOT is unavailable, `repository-enter` may choose a verified WARM artifact.

### Workspace Cache

`WARM_RESTORE_WORKSPACE_CACHE` has priority when a valid unconsumed/unexpired Workspace Capsule is explicitly available because it may preserve staged, unstaged, and untracked work. Download the exact capsule, run `workspace-cache-validate`, restore it into a fresh path, set/verify canonical origin, and rerun `repository-enter`.

### Published source

`WARM_RESTORE_PUBLISHED_SOURCE` uses the self-contained `published-source-<run_id>` bundle emitted by a successful Web publish. The receipt must bind exact artifact ID/name, raw bundle SHA-256/size, published commit/tree, and `fresh_restore=PASS`. When fresh remote commit/tree are supplied, the published source must match them exactly. Restore the bundle into a fresh Git repository, set canonical origin/branch, verify exact commit/tree, then rerun `repository-enter`.

The published-source artifact is therefore not merely audit residue: it is the default clean WARM recovery object after a successful push.

## COLD behavior

Only when neither HOT nor a verified WARM artifact is available may the runtime return:

```text
status = COLD_ACQUIRE_REQUIRED
source_reacquisition_required = true
```

Only this state enters `references/source-acquisition.md` / `source-acquisition-plan`.

Source-only archives, copied directories, installed Skill trees, release staging, and a filesystem tree followed by `git init` never qualify as HOT. They are ignored as candidate workspaces; if WARM evidence exists, use WARM instead of turning the snapshot into repository authority.

## Performance objective

The steady-state lifecycle is:

```text
HOT -> edit -> commit -> FAST_PUBLISH(thin bundle) -> HOT
```

Recovery is:

```text
HOT lost -> WARM restore -> HOT
```

Only disaster recovery is:

```text
HOT lost + WARM unavailable -> COLD acquisition
```

Identity checks exist to protect this fast path, not to force the path to restart.
