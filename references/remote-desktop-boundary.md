# Remote Desktop Commander workspace boundary

Use Remote Desktop Commander only inside the persistent authorized root `/Users/yihanhu/PiWork` plus any task-specific temporary roots explicitly granted by the user. Treat this as a hard capability boundary, not as a convenience convention. Within PiWork, each task still chooses one canonical Git working tree as its authoritative source baseline.

## Required allowlist

1. Treat `/Users/yihanhu/PiWork` as persistently pre-authorized for this user's Remote Desktop Commander coding workflows. No repeated per-task approval is required for paths contained under this root.
2. Bind each repository task to exactly one canonical Git working tree located under `/Users/yihanhu/PiWork`. Sibling repositories, worktrees, scratch folders, and artifacts may be accessed when relevant, but they do not become alternate source baselines.
3. Allow scratch, artifact, release-staging, receipt, and temporary directories anywhere under `/Users/yihanhu/PiWork` without separate authorization, provided they are used for the current task.
4. Treat every location outside `/Users/yihanhu/PiWork` as out of scope by default, including the rest of the home directory, cloud-synced folders, Downloads, Desktop, Documents, credential stores, SSH configuration, package-manager caches, and system directories.
5. Do not broaden the allowlist merely because a command, tool, dependency, or repository discovery step would be easier outside PiWork. Ask for an explicit temporary root when the task genuinely requires another location.
6. Keep any outside-PiWork temporary authorization narrow: record the exact root and purpose, use it only for that purpose, and stop using it when the step is complete. Do not treat it as a new persistent workspace.

## Tool behavior

- Run Remote Desktop Commander terminal commands with a working directory inside an allowed root. Reject commands whose explicit path arguments, redirections, archive targets, Git worktrees, package outputs, or subprocess paths escape the allowlist.
- Restrict file search roots to allowed roots. Never start whole-disk, home-directory, or unrelated-parent searches to discover a repository.
- Restrict reads, writes, moves, edits, archive extraction, packaging, and generated artifacts to allowed roots.
- Treat symlink and path traversal as boundary-sensitive. Resolve the effective target before relying on a lexical path prefix; do not follow a symlink into an out-of-scope location.
- Keep Git discovery, clone, fetch, commit, worktree, archive, and push operations rooted in the canonical workspace or an explicitly authorized temporary root. Do not use another checkout as an implicit source baseline.
- Do not read credential material directly. Let Git, SSH, the OS credential helper, or the host-owned connector consume credentials through their normal interfaces.
- Do not weaken Desktop Commander host configuration such as `allowedDirectories` during an ordinary coding task. If the host already enforces a narrower boundary, respect it. Treat host enforcement and this Skill's allowlist as cumulative; the narrower boundary wins.
- Do not use Remote Desktop Commander text/file-write primitives to reconstruct a session-only archive or source tree from model-carried chunks, base64, heredocs, or repeated writes merely because a direct binary transfer bridge is missing. Explain the boundary and ask the user to place the real file under PiWork or explicitly authorize a specific alternate transfer method.
- When the user explicitly authorizes `GUARDED_SINGLE_SHOT_RELAY`, keep its envelope, partial file, and verified destination under an authorized root; decode only the uniquely framed payload, require exact size/SHA-256, and atomically rename only after verification. Guard damage may be diagnostic, but payload integrity failure must remain a failure.

## Establishing a workspace

Use `/Users/yihanhu/PiWork` as the persistent development root. If the repository path is not yet known, search only within PiWork or create/clone the repository under PiWork; do not search the user's entire machine. Once a repository is selected, bind the task to that repository's Git working tree as the canonical workspace.

For a new persistent Git workspace, use a layout such as:

```text
/Users/yihanhu/PiWork/
  repo/
  scratch/
  artifacts/
```

PiWork is the persistent access boundary; task relevance still controls which contents should be touched. Keep unrelated repositories unchanged, and require explicit authorization for anything outside PiWork.

## Fail-closed rule

If a required operation would touch a path whose authorization is missing or ambiguous, stop that operation and request an explicit root authorization. Do not infer consent from device connectivity, filesystem visibility, successful tool access, prior unrelated tasks, or the ability to execute the command.
