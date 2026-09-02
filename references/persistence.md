# Optional cross-conversation persistence and Workspace Cache

Codex Loop has two separate recovery layers for Web work:

1. **state-only persistence**: small lifecycle/reconciliation evidence;
2. **Workspace Cache**: an explicit, private, immutable Git/worktree handoff capsule for continuing development in a later conversation.

Neither Drive object is a second mutable truth source. The current bound workspace remains authoritative until a later restore is fully verified and bound.

## Default and authority

- Persistence is default-off. Workspace Cache is created only when the user explicitly asks to cache/preserve the workspace or when cross-conversation workspace recoverability is an explicit acceptance requirement.
- `google_drive` is the first host adapter. Google OAuth, connector sessions, refresh tokens, user identity, file authorization, and Drive object operations remain owned by the ChatGPT host.
- Repository source contains only adapter logic, schemas, tests, and policy. User-instance folder IDs, task IDs, cache file IDs, manifests, and connection state never belong in GitHub source.
- A restored workspace becomes authoritative only after integrity + Git identity + worktree-state verification succeeds.

## State-only persistence

`persistence-export --backend google_drive` creates a private temporary `state-only.json` manifest. The host may upload it to `Codex Loop/.runtime/tasks/<task-id>/`. It remains schema-whitelisted and may contain the objective, criteria, task/profile/generation metadata, repository commit/tree lineage, bounded resume metadata, and hashed external-action identity. It must not contain chain of thought, hidden instructions, credentials/tokens/cookies, raw tool transcripts, approval/session nonces, environment secrets, or raw external-action identities.

A later conversation downloads the manifest, runs `persistence-validate`, then `persistence-resume-plan` and `persistence-resume`. Resume creates a new freshness domain: old PASS, validation, review, and objective-audit evidence is historical until re-proven against current reality. See `persistence-resume.md`.

## Workspace Cache (`state_and_workspace` recovery)

Workspace Cache is a separate artifact class with a fixed **7-day TTL** and one-shot consumption semantics.

Create it from the current real Git workspace:

```bash
python3 scripts/codex_loop.py workspace-cache-create \
  --cwd REPO \
  --repository OWNER/REPO \
  --output /PRIVATE/TEMP/workspace-cache.tar.gz
```

The capsule contains only:

- a verified Git bundle carrying the exact current HEAD commit/history required for restore;
- the exact HEAD tree identity;
- a binary staged patch;
- a binary unstaged patch;
- non-ignored untracked regular files and safe in-workspace symlinks;
- an immutable manifest with component hashes and a state fingerprint.

It deliberately excludes ignored files, `.git/config`, hooks, credentials, environment caches, virtual environments, `node_modules`, and other ignored build/runtime material. Unsupported/special untracked filesystem entries fail closed instead of being silently omitted.

`workspace-cache-create` returns the capsule SHA-256/size, cache ID, exact HEAD commit/tree, state fingerprint, suggested Drive filename, private bounded folder path `Codex Loop/.runtime/workspace-cache`, and 7-day expiry. The host uploads the exact binary file privately and retains the Drive object identity only in host-private state.

### Restore

A later conversation must download the exact capsule and verify the externally retained SHA-256 before restore:

```bash
python3 scripts/codex_loop.py workspace-cache-validate \
  --capsule /PRIVATE/TEMP/cache.tar.gz \
  --expected-sha256 FULL_SHA256

python3 scripts/codex_loop.py workspace-cache-restore \
  --capsule /PRIVATE/TEMP/cache.tar.gz \
  --expected-sha256 FULL_SHA256 \
  --destination /FRESH/WEB/WORKSPACE \
  --consumption-receipt-output /PRIVATE/TEMP/cache-consumed.json
```

Restore must produce a **fresh real Git repository** and require:

- restored `HEAD` exactly equals cached HEAD commit;
- restored `HEAD^{tree}` exactly equals cached tree;
- staged patch is restored to index + worktree;
- unstaged patch is restored only to worktree;
- non-ignored untracked state matches the manifest;
- the recomputed workspace-state fingerprint exactly matches the cache manifest.

Only after all checks pass may the new workspace be bound as the sole mutable authority.

### One-shot consumption and deletion ordering

After successful restore:

1. mark the cache consumed by uploading the small `workspace-cache-consumed-v1-<cache-id>.json` receipt to the same bounded private folder;
2. attempt to delete the exact capsule after a fresh ID/title/parent readback;
3. if capsule deletion succeeds, delete the matching consumption receipt;
4. if deletion fails, refresh exact identity and retry **at most once in that cache operation**;
5. if it still fails, leave the receipt + capsule as `CACHE_CLEANUP_PENDING`.

A cleanup failure **never invalidates `WORKSPACE_RESTORED`**. The consumption receipt excludes that cache ID from later automatic restore selection even when the capsule remains because Drive deletion was unavailable/blocked.

## Opportunistic bounded cleanup

Run cleanup opportunistically on every Workspace Cache create/list/restore operation. For a restore, first select the intended capsule and preserve that exact cache ID from pre-restore garbage collection; clean other eligible objects, restore/verify the selected capsule, then mark it consumed and delete it. Scan only the exact bounded `Codex Loop/.runtime/workspace-cache` folder and pass current object metadata to:

```bash
python3 scripts/codex_loop.py workspace-cache-cleanup-plan --objects-json /PRIVATE/TEMP/cache-objects.json
# While restoring CACHE_ID:
python3 scripts/codex_loop.py workspace-cache-cleanup-plan --objects-json /PRIVATE/TEMP/cache-objects.json --preserve-cache-id CACHE_ID
```

Each object observation must include exact `id`, `name`, `created_at`, and host-proven `bounded_parent_proven` + `ownership_proven`. The runtime plans deletion only for:

- caches with a matching consumption receipt; or
- unconsumed caches whose age is at least 7 days.

Unconsumed, unexpired caches remain. A cache with unproven ownership/parent becomes `cleanup_pending`, never a guessed delete. Matching/orphan consumption receipts are removed only inside the same bounded proof scope. Neighboring Drive folders and non-cache objects are ignored.

This means effective Workspace Cache retention is:

```text
min(successful consumption time, created_at + 7 days)
```

with later opportunistic cleanup for permission-related deletion residue.

## State-only cleanup

State-only manifests retain their existing status-dependent TTL policy. `persistence-cleanup-plan` remains artifact-class-specific: unresolved external actions are retained; expired state manifests are delete-eligible only with exact ownership + bounded task-folder proof. Prefer recoverable deletion when available; exact permanent deletion is permitted only when that is the adapter's supported primitive.

Workspace Cache cleanup rules do not apply to public-read `ChatGPT-GitHub-Staging` publication transport objects; those remain one-time publication artifacts governed by `web-mode-publish.md`.

## Capability degradation

A disconnected Drive connector is not a correctness failure when persistence/cache is optional. If the user explicitly requires cross-conversation workspace recoverability, inability to create or retrieve the capsule is a completion blocker. Never substitute model-carried source text, hidden memory, or an installed Skill copy without explicit installed-source authorization.
