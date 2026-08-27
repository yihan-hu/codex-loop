# Remote Desktop Commander workspace boundary

Use this reference only after Local mode has resolved the conversation's `LOCAL_ROOT` according to `local-mode-setup.md`. Remote Desktop Commander (RDC) operations must stay inside that authorized root plus any task-specific temporary roots explicitly granted by the user.

## Required allowlist

1. Treat the resolved `LOCAL_ROOT` as the persistent RDC development boundary for the current conversation only when the host actually authorizes it.
2. Bind each repository task to exactly one canonical Git working tree located under `LOCAL_ROOT`. Sibling repositories, worktrees, scratch folders, and artifacts may be accessed when relevant, but they do not become alternate source baselines.
3. Allow scratch, artifact, release-staging, receipt, and temporary directories anywhere under `LOCAL_ROOT` without separate authorization when they are used for the current task.
4. Treat every location outside `LOCAL_ROOT` as out of scope by default, including unrelated home-directory content, cloud-synced folders, Downloads, Desktop, Documents, credential stores, SSH configuration, package-manager caches, and system directories.
5. Do not broaden the allowlist merely because a command, tool, dependency, or repository discovery step would be easier outside `LOCAL_ROOT`. Ask for an explicit temporary root when the task genuinely requires another location.
6. Keep any outside-root temporary authorization narrow: record the exact root and purpose, use it only for that purpose, and stop using it when the step is complete. Do not treat it as a new persistent workspace.

## Tool behavior

- Run RDC terminal commands with a working directory inside an allowed root. Reject commands whose explicit path arguments, redirections, archive targets, Git worktrees, package outputs, or subprocess paths escape the allowlist.
- Restrict file search roots to allowed roots. Never start whole-disk, home-directory, or unrelated-parent searches to discover a repository.
- Restrict reads, writes, moves, edits, archive extraction, packaging, and generated artifacts to allowed roots.
- Treat symlink and path traversal as boundary-sensitive. Resolve the effective target before relying on a lexical path prefix; do not follow a symlink into an out-of-scope location.
- Keep Git discovery, clone, fetch, commit, worktree, archive, and push operations rooted in the canonical workspace or an explicitly authorized temporary root. Do not use another checkout as an implicit source baseline.
- Do not read credential material directly. Let Git, SSH, the OS credential helper, or the host-owned connector consume credentials through their normal interfaces.
- Do not weaken RDC host configuration such as `allowedDirectories` during an ordinary coding task. Treat host enforcement and this Skill's allowlist as cumulative; the narrower boundary wins.
- Do not use RDC text/file-write primitives to reconstruct a session-only archive or source tree from model-carried chunks, Base64, heredocs, or repeated writes merely because a direct binary transfer bridge is missing.
- When the user explicitly authorizes `GUARDED_SINGLE_SHOT_RELAY`, keep its envelope, partial file, and verified destination under an authorized root; decode only the uniquely framed payload, require exact size/SHA-256, and atomically rename only after verification. Guard damage may be diagnostic, but payload integrity failure remains a failure.

## Establishing a workspace

If the repository path is not yet known, search only within the resolved `LOCAL_ROOT` or create/clone the repository there. Do not search the user's entire machine. Once a repository is selected, bind the task to that repository's Git working tree as the canonical workspace.

An illustrative layout is:

```text
<LOCAL_ROOT>/
  repo/
  scratch/
  artifacts/
```

`<LOCAL_ROOT>` is a placeholder in documentation. Before tool execution, replace it with the exact absolute root resolved for the current conversation. `LOCAL_ROOT` is the access boundary; task relevance still controls which contents should be touched.

## Fail-closed rule

If `LOCAL_ROOT` is unresolved, RDC rejects it, or a required operation would touch an unauthorized path, stop that operation and request the exact missing root authorization. Do not infer consent from device connectivity, filesystem visibility, a prior conversation, successful tool access, or the ability to execute the command.
