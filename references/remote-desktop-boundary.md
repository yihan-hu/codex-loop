# Remote Desktop Commander boundaries

RDC is a host execution/interaction transport, never an authority bypass. **Every RDC filesystem, search, process, browser/GUI, or configuration intent must be classified and routed through Codex Loop before the first RDC call.** RDC availability does not select repository development mode. Apply the repository boundary below when `workspace_mode=local`; apply the interaction-only boundary for `local_chrome`/`local_mac_gui`; use `route-check --action rdc_host_config` before the two narrow Codex Loop host config reads; they are routed read-only bootstrap actions, not exceptions. See `interaction-routing.md`.

The host's `allowedDirectories` is a hard capability ceiling, not semantic permission. Codex Loop's current task scope is normally narrower; effective access is the intersection. `allowedDirectories=[]` or another broad host setting must never be interpreted as permission to scan home, sibling repositories, cloud folders, or other unrelated locations. Do not broaden RDC configuration during ordinary task execution; configuration mutation belongs in a separate explicit host-administration task/session.

Before **any repository-affecting RDC action**, require an initialized conversation routing session and run `route-check --action rdc_repository` with the current conversation's workspace-grant state. While `workspace_mode=web`, that check must fail closed regardless of RDC connectivity, a known local checkout, an installed local Skill, or prior local use. Do not probe the local repository first and resolve routing afterward.

Before interaction-only RDC/browser use, require the routing session to select the intended `interaction_target` and run `route-check --action browser_interaction` with current-task computer-use authorization. Capability availability may confirm that the selected route can execute; it must never select or mutate the route.

Registered workspace identity, current-conversation semantic grants, RDC filesystem authorization, and routing state are separate layers. See `workspace-registry.md`.

## Local repository-development boundary

Local mode may have more than one **Effective Local Root**:

```text
Primary Local Root + Session Granted Roots = Effective Local Roots
```

The primary root comes from explicit Local-mode selection. A registered additional root enters the effective set only when the user explicitly grants that exact registry entry for the current conversation and RDC actually authorizes its resolved real path.

1. Effective Local Roots bound **where a repository may be selected or created**; they are not a standing license to inspect every descendant.
2. After a repository task is bound, its canonical Git worktree becomes the default RDC filesystem/search/process scope. Other roots, sibling repositories, sibling worktrees, and unrelated descendants are out of scope unless the user separately names or grants them for this task.
3. A session grant for one registered workspace does not grant its parent, siblings, or another alias. A broader RDC host root may contain multiple repositories, but semantic grant checks remain exact per registry entry and current task binding.
4. Task-owned scratch, artifact, release-staging, receipt, and temporary paths may be used only when they are explicitly derived inside the bound worktree or another already-authorized task path; do not infer sibling scratch roots from convenience.
5. Treat every location outside the Effective Local Roots as out of scope by default, including unrelated home-directory content, cloud-synced folders, Downloads, Desktop, Documents, credential stores, SSH configuration, package-manager caches, and system directories.
6. Do not broaden the allowlist merely because a command, tool, dependency, or repository discovery step would be easier elsewhere. Ask for an explicit narrow temporary root when genuinely required.
7. Keep any outside-root temporary authorization narrow: record the exact root and purpose, use it only for that purpose, and stop using it when the step is complete. Do not persist it as a registered trusted workspace unless the user separately asks to register that location.

## Registered workspace access gate

For a registered workspace, actual repository-affecting access requires:

```text
REGISTERED + GRANTED THIS CONVERSATION + HOST/RDC AUTHORIZED = ACCESSIBLE
```

A KNOWN alias is not permission. Before the first RDC filesystem action for a registered workspace:

- require `route-check --action rdc_repository` to allow the repository route;
- confirm the current conversation has an explicit semantic grant;
- resolve the configured path to its real path and reject missing/non-directory/changed-symlink targets;
- pass only host-observed authorized roots to `workspace-resolve` and require access;
- never modify RDC `allowedDirectories` to make the check pass.

If the alias is known but not granted, ask for current-conversation path permission without asking the user to repeat the stored absolute path. If the path no longer exists or its realpath changed, ask for explicit re-registration; never search the whole home directory or disk for a replacement.

## Local repository tool behavior

- Treat Local mode and root authorization as routing/access state, not source-write consent. Before the first edit/create/delete/overwrite/reformat of local source in each task, require explicit current-task local-source-mutation authorization. Do not infer it from earlier tasks, RDC availability, prior successful writes, a read-only inspection request, synchronization intent, or generic `push` wording.
- RDC-backed repository work may target macOS or Windows. Do not reject `rdc_repository` solely because the host is Windows. Keep Windows-only gaps (managed sessions, POSIX shell semantics, atomic guarded replacement) host-visible or fail-precise for the affected operation as described in `local-mode-setup.md`.
- A publish-only request may use native Git to publish already-existing audited local content when otherwise authorized, but it must not silently change source files to make the push succeed. If source integration or conflict resolution would be required, stop and request explicit local mutation authorization for that task.
- Run repository-affecting RDC terminal commands from the task's bound canonical worktree (or an explicitly named task-owned path). Reject commands whose file arguments, redirections, archive targets, Git worktrees, package outputs, or subprocess paths escape the current task scope even when they remain inside a broader Effective Local Root.
- After binding, restrict file searches to the canonical worktree or an explicitly named task-owned path. Never search sibling repositories, the whole Effective Local Root, home directory, or disk merely to discover a replacement or convenience input.
- Restrict reads, writes, moves, edits, archive extraction, packaging, and generated artifacts to allowed roots.
- Treat symlink and path traversal as boundary-sensitive. Resolve the effective target before relying on a lexical path prefix; do not follow a symlink into an out-of-scope location.
- Keep Git discovery, clone, fetch, commit, worktree, archive, and push operations rooted in the canonical workspace or an explicitly authorized temporary root. Do not use another checkout as an implicit source baseline.
- Do not read credential material directly. Let Git, SSH, the OS credential helper, or the host-owned connector consume credentials through their normal interfaces.
- Do not weaken RDC host configuration such as `allowedDirectories` during an ordinary coding task. Treat host enforcement and this Skill's allowlist as cumulative; the narrower boundary wins.
- Do not use RDC text/file-write primitives to reconstruct a session-only archive or source tree from model-carried chunks, Base64, heredocs, or repeated writes merely because a direct binary transfer bridge is missing.
- When the user explicitly authorizes `GUARDED_SINGLE_SHOT_RELAY`, keep its envelope, partial file, and verified destination under an authorized root; decode only the uniquely framed payload, require exact size/SHA-256, and atomically rename only after verification. Guard damage may be diagnostic, but payload integrity failure remains a failure.

## Interaction-only RDC boundary

When `interaction_target` is `local_chrome` or `local_mac_gui`, RDC may be used even while `workspace_mode=web`. Before the first interaction action, require `route-check --action browser_interaction` to allow the selected target using current-task computer-use authorization. In that case:

- Do not inspect, edit, test, package, commit, or publish a local repository unless the user separately selected Local repository development; interaction-only RDC use must not touch the local checkout while `workspace_mode=web`. A successful browser-interaction route check does not authorize `rdc_repository`.
- Limit commands and observations to the requested application/computer interaction and narrowly necessary host capability checks.
- For Chrome Browser Control, RDC is diagnostic/setup transport only; do not use AppleScript, Chrome `execute javascript`, generic coordinates, or internal Browser sockets as a Browser Control fallback.
- If the user explicitly requests a separate nonstandard RDC/GUI automation path after the limitation is disclosed, use the minimum scope needed, follow `local-mac-gui.md`, verify the resulting state, and label it as computer automation rather than Browser Control evidence.
- For `local_mac_gui`, prefer Accessibility identifiers/roles and derive mouse coordinates from current element geometry. Restore transient mouse/focus state when practical; do not rely on unverified global keystroke focus.
- Do not enumerate unrelated files, tabs, windows, processes, or user data merely because RDC can access them.
- Keep temporary interaction artifacts ephemeral and delete them after verification when practical.
- macOS Accessibility, Screen Recording, browser-profile, and similar permissions remain host-owned; never change them silently.

The host-local files `~/.codex-loop/host.json` and `~/.codex-loop/workspace-registry.json` are the only paths allowed by the routed `rdc_host_config` read-only action. They are not repository workspaces and must never contain credentials or persistent permission state. Reading them does not select Local mode, grant repository access, or authorize configuration mutation.

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

If the conversation routing session is missing/invalid, the relevant `route-check` denies the action, `workspace_mode` is still `web` for a repository-affecting RDC request, the primary root is unresolved, a registered workspace is not granted, RDC rejects the resolved path, a symlink changes the real boundary, or an operation would touch an unauthorized path, stop that operation. Do not infer consent or routing state from device connectivity, filesystem visibility, a prior conversation, successful tool access, registry knowledge, an installed local Skill, or the ability to execute a command.

## Downstream Web -> local transfer exception

`rdc_transfer` is not `rdc_repository`. When an ordinary Web file or Web-authoritative repository is being saved/synchronized to a local host through the fixed Drive -> RDC binary path, `route-check --action rdc_transfer` may allow only the authorized destination path while `workspace_mode=web`. A direct user request to move/save/copy/deliver the file to that local host is sufficient current-task local-computer-use intent for this narrow transfer and should not trigger a second authorization prompt. This permits downloading/verifying the exact bytes as a downstream artifact; it does not permit inspecting the local checkout, importing refs, editing source, or treating a local repository as authoritative. Any repository import/mutation still requires explicit Local-mode selection or the separately authorized local-source-mutation step defined by `web-to-local-handoff.md`.
