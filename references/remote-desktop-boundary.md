# Remote Desktop Commander boundaries

RDC is a host execution/interaction transport and does not select repository development mode. Apply the repository boundary below when `workspace_mode=local`; apply the interaction-only boundary when RDC is used for `local_chrome` or `local_mac_gui` while the repository may remain in Web mode. See `interaction-routing.md`.

Registered workspace identity, current-conversation semantic grants, and RDC filesystem authorization are separate layers. See `workspace-registry.md`.

## Local repository-development boundary

Local mode may have more than one **Effective Local Root**:

```text
Primary Local Root + Session Granted Roots = Effective Local Roots
```

The primary root comes from explicit Local-mode selection. A registered additional root enters the effective set only when the user explicitly grants that exact registry entry for the current conversation and RDC actually authorizes its resolved real path.

1. Treat every Effective Local Root as an RDC development boundary for the current conversation only when the host actually authorizes it.
2. Bind each repository task to exactly one canonical Git working tree inside one Effective Local Root. Other roots, sibling repositories, worktrees, scratch folders, and artifacts never become alternate source baselines.
3. A session grant for one registered workspace does not grant its parent, siblings, or another alias. A broader RDC host root may contain multiple repositories, but semantic grant checks remain exact per registry entry.
4. Scratch, artifact, release-staging, receipt, and temporary directories may be used inside the task's already-authorized Effective Local Roots when relevant; do not infer new roots from convenience.
5. Treat every location outside the Effective Local Roots as out of scope by default, including unrelated home-directory content, cloud-synced folders, Downloads, Desktop, Documents, credential stores, SSH configuration, package-manager caches, and system directories.
6. Do not broaden the allowlist merely because a command, tool, dependency, or repository discovery step would be easier elsewhere. Ask for an explicit narrow temporary root when genuinely required.
7. Keep any outside-root temporary authorization narrow: record the exact root and purpose, use it only for that purpose, and stop using it when the step is complete. Do not persist it as a registered trusted workspace unless the user separately asks to register that location.

## Registered workspace access gate

For a registered workspace, actual repository-affecting access requires:

```text
REGISTERED + GRANTED THIS CONVERSATION + HOST/RDC AUTHORIZED = ACCESSIBLE
```

A KNOWN alias is not permission. Before the first RDC filesystem action for a registered workspace:

- confirm the current conversation has an explicit semantic grant;
- resolve the configured path to its real path and reject missing/non-directory/changed-symlink targets;
- pass only host-observed authorized roots to `workspace-resolve` and require access;
- never modify RDC `allowedDirectories` to make the check pass.

If the alias is known but not granted, ask for current-conversation path permission without asking the user to repeat the stored absolute path. If the path no longer exists or its realpath changed, ask for explicit re-registration; never search the whole home directory or disk for a replacement.

## Local repository tool behavior

- Treat Local mode and root authorization as routing/access state, not source-write consent. Before the first edit/create/delete/overwrite/reformat of local source in each task, require explicit current-task local-source-mutation authorization. Do not infer it from earlier tasks, RDC availability, prior successful writes, a read-only inspection request, synchronization intent, or generic `push` wording.
- A publish-only request may use native Git to publish already-existing audited local content when otherwise authorized, but it must not silently change source files to make the push succeed. If source integration or conflict resolution would be required, stop and request explicit local mutation authorization for that task.
- Run repository-affecting RDC terminal commands with a working directory inside an Effective Local Root and the task's bound canonical working tree when source state matters. Reject commands whose explicit repository/file path arguments, redirections, archive targets, Git worktrees, package outputs, or subprocess paths escape the allowlist.
- Restrict file search roots to Effective Local Roots. Never start whole-disk, home-directory, or unrelated-parent searches to discover a repository.
- Restrict reads, writes, moves, edits, archive extraction, packaging, and generated artifacts to allowed roots.
- Treat symlink and path traversal as boundary-sensitive. Resolve the effective target before relying on a lexical path prefix; do not follow a symlink into an out-of-scope location.
- Keep Git discovery, clone, fetch, commit, worktree, archive, and push operations rooted in the canonical workspace or an explicitly authorized temporary root. Do not use another checkout as an implicit source baseline.
- Do not read credential material directly. Let Git, SSH, the OS credential helper, or the host-owned connector consume credentials through their normal interfaces.
- Do not weaken RDC host configuration such as `allowedDirectories` during an ordinary coding task. Treat host enforcement and this Skill's allowlist as cumulative; the narrower boundary wins.
- Do not use RDC text/file-write primitives to reconstruct a session-only archive or source tree from model-carried chunks, Base64, heredocs, or repeated writes merely because a direct binary transfer bridge is missing.
- When the user explicitly authorizes `GUARDED_SINGLE_SHOT_RELAY`, keep its envelope, partial file, and verified destination under an authorized root; decode only the uniquely framed payload, require exact size/SHA-256, and atomically rename only after verification. Guard damage may be diagnostic, but payload integrity failure remains a failure.

## Interaction-only RDC boundary

When `interaction_target` is `local_chrome` or `local_mac_gui`, RDC may be used even while `workspace_mode=web`. In that case:

- Do not inspect, edit, test, package, commit, or publish a local repository unless the user separately selected Local repository development; interaction-only RDC use must not touch the local checkout while `workspace_mode=web`.
- Limit commands and observations to the requested application/computer interaction and narrowly necessary host capability checks.
- For Chrome, prefer structured application scripting or a supported native browser bridge over generic coordinates.
- For native GUI fallback, use the minimum screenshot/mouse/keyboard scope needed and verify the resulting state.
- Do not enumerate unrelated files, tabs, windows, processes, or user data merely because RDC can access them.
- Keep temporary interaction artifacts ephemeral and delete them after verification when practical.
- macOS Accessibility, Screen Recording, browser-profile, and similar permissions remain host-owned; never change them silently.

The host-local files `~/.codex-loop/host.json` and `~/.codex-loop/workspace-registry.json` are narrow bootstrap/configuration exceptions used only for non-sensitive routing identity/defaults. They are not repository workspaces and must never contain credentials or persistent permission state. Reading them does not select Local mode.

## Establishing a workspace

If a repository alias is already registered, resolve it through the registry; do not rediscover it by scanning the machine. If the path is not registered, search only within an already resolved/authorized primary root or use an exact path supplied by the user. Once a repository is selected, bind the task to that repository's Git working tree as the canonical workspace.

An illustrative layout is:

```text
<PRIMARY_ROOT>/
  repo-a/
  scratch/

<SESSION_GRANTED_ROOT>/
  repo-b/
```

The placeholders are documentation only. Before tool execution, use the exact real paths that were registered/selected, granted when required, and confirmed by the host.

## Fail-closed rule

If the primary root is unresolved, a registered workspace is not granted, RDC rejects the resolved path, a symlink changes the real boundary, or an operation would touch an unauthorized path, stop that operation. Do not infer consent from device connectivity, filesystem visibility, a prior conversation, successful tool access, registry knowledge, or the ability to execute a command.
