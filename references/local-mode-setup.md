# Local mode setup, workspace registry, and effective local roots

Use this reference when the user explicitly selects local repository development or when a registered local workspace must be resolved. Remote Desktop Commander (RDC) is an execution/interaction transport, not a development-mode selector: using RDC for local Chrome or macOS computer use does not by itself enter Local mode.

Codex Loop separates three states:

```text
KNOWN    persistent registry identity/location
GRANTED  explicit authorization for the current conversation
BOUND    one durable task's canonical Git working tree
```

A registered path is KNOWN, not GRANTED. See `workspace-registry.md` for the registry/session capability contract.

## Primary Local Root and Effective Local Roots

`LOCAL_ROOT` remains the logical name for the **primary** local development root selected for Local mode. It is not a hard-coded author path and not necessarily a persistent operating-system environment variable.

V1 expands the access model to:

```text
Primary Local Root + Session Granted Roots = Effective Local Roots
```

The primary root is the workspace root chosen when the user explicitly enters Local mode. Additional registered workspaces may join the effective root set only after the user explicitly grants each one in the current conversation and RDC/host authorization is independently confirmed.

Multiple effective roots do not merge repositories. Each durable task still binds to exactly one canonical Git working tree. A grant for one repository never grants its parent or sibling repositories.

## Persistent workspace registry

Frequently used local roots and repositories belong in the host-local registry:

```text
~/.codex-loop/workspace-registry.json
```

Example logical entries:

```text
piwork   -> /absolute/path/to/PiWork     kind=development_root
epiagent -> /absolute/path/to/EpiAgent   kind=repository
```

The registry stores identity/location only. It never stores authorization, trust, or cross-conversation grants. Knowing a registry alias never selects Local mode by itself.

Registering PiWork through the same registry removes the need for PiWork-specific path logic. Prefer a stable alias such as `piwork` for the primary development root and repository aliases such as `epiagent` for fixed repositories.

## Resolving the primary root

Resolve the primary Local root in this order, but only after the user has explicitly selected Local repository development:

1. Reuse the exact primary root already established earlier in the current conversation.
2. If the user names a registered workspace alias and explicitly grants it for this conversation, resolve that alias through the workspace registry and confirm RDC access.
3. Otherwise, use an absolute root explicitly named by the user when they select Local mode, optionally registering it when they ask to remember it.
4. Otherwise, read the private Host Profile `~/.codex-loop/host.json`. Prefer `workspace.default_local_workspace`; schema-v1 `default_local_workspace` and `default_local_root` are migration inputs only. Reading the alias is allowed as a global preference, but resolving it to a local filesystem path still begins only after explicit Local-mode intent.
5. If the host exposes a single explicit RDC-authorized workspace root as tool metadata, that root may be used after confirming it is the intended development root.
6. Otherwise ask once for the exact absolute root and require the user to authorize that root in RDC.

Do not infer a root from a repository author's home directory, a stale prior conversation, a downloaded archive path, or arbitrary filesystem visibility outside the authorized boundary.

## Host-local persistent configuration

The optional config path is `~/.codex-loop/host.json`. It belongs to the user's computer, not to any repository and not to the packaged Skill.

The current schema is the unified v2 Private Host Profile described in `host-profile.md`; the workspace preference is nested:

```json
{
  "schema_version": 2,
  "workspace": {
    "default_local_workspace": "piwork"
  }
}
```

Schema-v1 root `default_local_workspace` and historical `default_local_root` remain compatibility/migration inputs only; neither selects Local mode or grants access. Migrate a stable direct path by registering it as `piwork` with `kind=development_root`, then use `workspace.default_local_workspace`.

Store only non-sensitive preferences/locators. `host.json` may also contain progress, browser, Web-publish, and persistence preferences; see `host-profile.md`. Never store observed capability claims, Git/OAuth tokens, passwords, cookies, connector credentials, approval tokens, session grant nonces, or other secrets in this file.

Because host-local files live outside the repository, normal Git commits, Web-mode source transport artifacts, Local-mode `git push`, and Skill packaging must not include them. Do not copy them into a repository merely to make them easier to discover.

A new conversation still starts in Web mode even when the registry or `host.json` exists. Persistent knowledge of a path never becomes implicit consent to use the local checkout.

## Conversation grants

When an alias is KNOWN but not GRANTED, do not ask the user to repeat the absolute path. Ask for explicit current-conversation permission, for example:

```text
Give EpiAgent path permission.
```

After observing explicit authorization, record it with `workspace-grant`. The first grant returns an opaque session nonce; keep that nonce only in the current conversation context and pass it to later `workspace-resolve` or `workspace-grants` operations. Do not write the nonce into repository files, `host.json`, the registry, or user memory.

A new conversation has no old nonce, so its effective grant set begins empty even though the registry persists.

Requests such as `modify EpiAgent`, `look at EpiAgent`, or `you know the EpiAgent path` do not themselves grant filesystem access. Registration and a task request are not authorization evidence.

Changing a registered path also does not preserve its old grant. Grants bind to the exact alias/path/kind fingerprint and become stale after registry mutation.

## Conversation and task scope

A new conversation starts in Web mode. Selecting Local mode activates the resolved primary root as the repository baseline for later repository tasks in that same conversation until the user explicitly switches back to Web mode. This routing choice does **not** persist permission to mutate local source: every task that would edit/create/delete/overwrite source files needs explicit current-task local-source-mutation authorization.

Development-location resolution must happen before any **repository-affecting** RDC/local-filesystem discovery or repository operation. Interaction-only RDC use is routed separately by `references/interaction-routing.md` and may occur while `workspace_mode=web`; it must not inspect a local checkout or influence the Web source baseline.

If the current ChatGPT/Web workspace lacks an obvious write or publication bridge, that absence does not authorize Local mode. Stay in Web mode and surface the missing capability instead of probing the Mac.

The development-location choice is conversation-scoped, but each durable runtime task still binds independently to one canonical Git working tree within one Effective Local Root. Sibling repositories and worktrees do not become interchangeable source baselines.

## RDC authorization boundary

Semantic workspace grants and RDC authorization are cumulative. Access requires:

```text
REGISTERED + GRANTED THIS CONVERSATION + HOST/RDC AUTHORIZED = ACCESSIBLE
```

Before using a registered workspace, resolve its real path, pass only host-observed authorized roots to the runtime, and require access. The runtime cannot modify RDC `allowedDirectories` and cannot turn a semantic grant into host permission.

Keep repository discovery, clones, worktrees, source edits, tests, builds, packaging, scratch data, release staging, receipts, and terminal/Git operations inside the Effective Local Roots. A task still uses only its bound canonical working tree as source baseline.

If a registered path no longer exists or its realpath changed through a symlink, fail closed. Do not search the user's home directory or whole disk to guess a replacement. Re-register the exact new path.

## Command examples

Register a primary development root:

```bash
python3 scripts/codex_loop.py workspace-register \
  --name piwork \
  --path "/absolute/path/to/PiWork" \
  --kind development_root
```

Register a fixed repository:

```bash
python3 scripts/codex_loop.py workspace-register \
  --name epiagent \
  --path "/absolute/path/to/EpiAgent" \
  --kind repository
```

After explicit user authorization:

```bash
python3 scripts/codex_loop.py workspace-grant epiagent \
  --authorization-evidence "user explicitly granted EpiAgent path access in this conversation"
```

Before a repository-affecting RDC action:

```bash
python3 scripts/codex_loop.py workspace-resolve epiagent \
  --session-id SESSION_NONCE \
  --host-authorized-root "/host/observed/authorized/root" \
  --require-access
```

For documentation, `SESSION_NONCE` and absolute paths are placeholders. Never copy an author's machine path into another user's execution plan.

## Fail-closed rule

Never replace an unresolved or unauthorized workspace with an author path, `~`, `/tmp`, the current ChatGPT workspace, or another convenient directory. Never search the whole home directory or disk. Resolve the registered/explicit root, require the current conversation grant when applicable, confirm the real host boundary, and then bind one canonical Git working tree.
