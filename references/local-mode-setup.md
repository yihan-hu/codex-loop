# Local mode setup, workspace registry, and effective local roots

Use this reference after Local selection from the current request or saved execution default or when a registered local workspace must be resolved. The selected local connection is an execution/interaction transport, not a development-mode selector: using local connector for local Chrome or macOS computer use does not by itself enter Local mode.

Codex Loop separates three states:

```text
KNOWN    persistent registry identity/location
GRANTED  explicit authorization for the current conversation
BOUND    one lifecycle's canonical Git working tree
```

A registered path is KNOWN, not GRANTED. See `workspace-registry.md` for the registry/session capability contract.

## Host platform contract

Local repository routing is platform-neutral once Local mode is resolved. A local-connector-backed **macOS or Windows** repository host is valid; do not reject Local mode solely because local connector reports Windows. macOS remains the end-to-end verified reference host. Windows is a best-effort/beta host until equivalent smoke coverage is completed.

On Windows:

- prefer host-visible PowerShell (or `cmd.exe` only when necessary) for shell execution and native Git for repository transport;
- keep managed interactive/background sessions host-visible because the bundled process-group/interrupt service is intentionally not enabled on Windows;
- when the guarded writer reports that atomic compare-exchange is unavailable for an existing file, use the host-visible local connector edit/write path for that mutation, then re-observe the exact file hash and refresh Codex Loop change state; do not weaken or emulate the atomic CAS primitive inside the runtime;
- skip POSIX-only shell/permission semantics when they are not meaningful on Windows, and report a precise per-operation degradation instead of disabling the whole Local workspace;
- require native Git to be installed and usable on the local connector host before Git-dependent Local work. If a runtime-owned Git probe cannot resolve Git but host-visible native Git works, keep the Git command host-visible and record the observation rather than rewriting source or switching publication transports.

Windows support here is deliberately permissive at the routing layer and conservative at individual primitives: a small platform bug may block one operation, but it is not evidence that the user must abandon Local mode or move source through model text.

## Local lifecycle authority

A resolved Local objective must create and resume its Codex Loop lifecycle on the local host, not in the transient ChatGPT host filesystem. The authoritative state root is the local host's `CODEX_LOOP_HOME/runtime`, normally `~/.codex-loop/runtime`.

Use the pinned environment’s configured `runtime_directory` and `state_directory` from `host-profile.md`; null values use `~/.codex-loop/runtime-src` and `~/.codex-loop`. Expand and verify them on that environment. The example below illustrates the standard locations; substitute configured paths and pass the selected state directory as command-scoped `CODEX_LOOP_HOME` for every lifecycle command. Use a runtime-owned source cache at `~/.codex-loop/runtime-src` by default. It is infrastructure, not the user's project checkout. The consumer Skill intentionally carries no maintainer-repository identity, so the host must resolve the canonical public Codex Loop source URL from the current distribution/public repository metadata (or obtain it from the user) before first Local bootstrap. Pass that externally resolved URL as `CODEX_LOOP_SOURCE_URL`; do not persist it as lifecycle authority. If the cache already exists, require it to be clean and update it only by fast-forward. On the verified macOS path:

```bash
RUNTIME="$HOME/.codex-loop/runtime-src"
mkdir -p "$HOME/.codex-loop"
if [ -d "$RUNTIME/.git" ]; then
  test -z "$(git -C "$RUNTIME" status --porcelain)"
  git -C "$RUNTIME" pull --ff-only origin main
else
  : "${CODEX_LOOP_SOURCE_URL:?canonical Codex Loop source URL required}"
  git clone --depth 1 "$CODEX_LOOP_SOURCE_URL" "$RUNTIME"
fi
python3 "$RUNTIME/scripts/codex_loop.py" ...
```

The runtime cache is replaceable code; the sibling `~/.codex-loop/runtime` directory is durable lifecycle state and must never be deleted or reset as part of runtime-cache refresh.

Do not use an arbitrary project checkout of Codex Loop as the lifecycle runtime, even when one happens to be available. Do not create a second host-side lifecycle for the same Local objective if local connector or the local runtime is temporarily unavailable; fail closed and resume when the local authority is reachable again.

A bound repository may contain task-owned ephemeral scratch such as `<worktree>/.codex-loop-tmp/<task-id>/` when a local operation genuinely needs staging inside an already-authorized root. That directory is disposable and never contains lifecycle authority. Durable task state remains in `~/.codex-loop/runtime`.

## Primary Local Root and Effective Local Roots

`LOCAL_ROOT` remains the logical name for the **primary** local development root selected for Local mode. It is not a hard-coded author path and not necessarily a persistent operating-system environment variable.

V1 expands the access model to:

```text
Primary Local Root + Session Granted Roots = Effective Local Roots
```

The primary root is the workspace root chosen when Local mode is resolved. Additional registered workspaces may join the effective root set only after the user explicitly grants each one in the current conversation and local connector/host authorization is independently confirmed.

Multiple effective roots do not merge repositories. Each lifecycle still binds to exactly one canonical Git working tree. A grant for one repository never grants its parent or sibling repositories.

## Persistent workspace registry

Saved project locations and default roots belong to the per-environment Host Profile. The host-local registry materializes saved aliases for grant lookup and can hold additional conversation-only roots:

```text
~/.codex-loop/workspace-registry.json
```

Example logical entries:

```text
piwork   -> /absolute/path/to/PiWork     kind=development_root
epiagent -> /absolute/path/to/EpiAgent   kind=repository
```

The registry stores identity/location only. It never stores authorization, trust, or cross-conversation grants. Knowing a registry alias never selects Local mode by itself.

Register the selected saved location on its own environment before using registry grants. Do not edit a profile-defined alias independently in this registry; reconcile it from the profile and invalidate a stale grant. No PiWork-specific path logic is needed.

## Resolving the primary root

Resolve the root from the pinned environment profile as described in `host-profile.md`: current-task authorized absolute directory (including an existing lifecycle binding), explicitly named saved project, then the environment's `default_root`. Current task choice wins over saved defaults. Check the chosen directory and canonical realpath through the pinned connector and confirm task/path authority before access.

If none is available, block directory-dependent execution and ask for a task directory or a saved environment default. Never use shell cwd, home, a connector's allowed root, another environment's registry, or a disk search to invent a replacement. Missing, non-directory, or connector-denied locations also block; a profile entry never grants access.

## Host-local persistent configuration

Use schema v4 `workspace.environments`, keyed by execution environment ID. The default root is a direct locator shared by that environment's connections. Keep Mac and WSL separate even on one computer. See `host-profile.md` for fields, defaults, and Drive recovery/save. No global workspace alias, connection-specific root, or legacy schema fallback remains.

A new conversation uses the saved `execution.default_target`, otherwise Web. Explicit current selection overrides it; an existing lifecycle retains its bound workspace. Profile reads never persist authorization or observed capabilities, and personal paths stay outside Git and packages.

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

A new conversation resolves its explicit or saved execution location. Selecting Local mode activates the resolved primary root as the repository baseline for later repository tasks in that same conversation until the user explicitly switches back to Web mode. This routing choice does **not** persist permission to mutate local source: every task that would edit/create/delete/overwrite source files needs explicit current-task local-source-mutation authorization.

Development-location resolution must happen before any **repository-affecting** local connector/local-filesystem discovery or repository operation. Interaction-only local connector use is routed separately by `references/interaction-routing.md` and may occur while `workspace_mode=web`; it must not inspect a local checkout or influence the Web source baseline.

If the current ChatGPT/Web workspace lacks an obvious write or publication bridge, that absence does not authorize Local mode. Stay in Web mode and surface the missing capability instead of probing the local host.

The development-location choice is conversation-scoped, but each durable runtime task still binds independently to one canonical Git working tree within one Effective Local Root. Sibling repositories and worktrees do not become interchangeable source baselines.

## local connector authorization boundary

Semantic workspace grants and local connector authorization are cumulative. Access requires:

```text
REGISTERED + GRANTED THIS CONVERSATION + HOST/local connector AUTHORIZED = ACCESSIBLE
```

Before using a registered workspace, resolve its real path, pass only host-observed authorized roots to the runtime, and require access. The runtime cannot modify local connector `allowedDirectories` and cannot turn a semantic grant into host permission.

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
  --current-user-authorization-observed \
  --authorization-evidence "user explicitly granted EpiAgent path access in this conversation"
```

Before a repository-affecting local connector action:

```bash
python3 scripts/codex_loop.py workspace-resolve epiagent \
  --session-id SESSION_NONCE \
  --host-authorized-root "/host/observed/authorized/root" \
  --require-access
```

For documentation, `SESSION_NONCE` and absolute paths are placeholders. Never copy an author's machine path into another user's execution plan.

## Fail-closed rule

Never replace an unresolved or unauthorized workspace with an author path, `~`, `/tmp`, the current ChatGPT workspace, or another convenient directory. Never search the whole home directory or disk. Resolve the registered/explicit root, require the current conversation grant when applicable, confirm the real host boundary, and then bind one canonical Git working tree.
