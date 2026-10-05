# Saved projects and conversation workspace cache

The Private Host Profile is the single editable source for remembered locations:
`workspace.environments.<computer>.projects.<alias>`. A request to remember a
project edits that source and, when Drive-backed, updates the existing
`codex-loop/settings/host-profile.json` file ID in place. Follow
`host-profile-drive.md`; never replace it with a registry registration.

```text
KNOWN    the current Host Profile supplies alias -> location on one environment
GRANTED  this conversation has authority for that exact directory
BOUND    one lifecycle uses one canonical Git working tree
```

`KNOWN != GRANTED`, `GRANTED != BOUND`, and `KNOWN != BOUND`.

## Save or remove a remembered project

Run this on the controller with the same private preference home used to restore
Drive, even when the path belongs to a remote computer:

```bash
CODEX_LOOP_HOME=SESSION_PRIVATE_HOME python3 scripts/codex_loop.py host-project set \
  --computer laptop --name epiagent --path "/absolute/path/to/EpiAgent"

CODEX_LOOP_HOME=SESSION_PRIVATE_HOME python3 scripts/codex_loop.py host-project remove \
  --computer laptop --name epiagent
```

The helper changes only that project in the original private profile; it preserves
other environments, projects, defaults, and preferences. It validates a locator,
without inspecting a remote directory. Local `saved=true` is not a Drive save:
export, update the original verified file ID, and fetch it again before claiming
cross-chat persistence. No native profile copy or runtime upgrade is required to
save a remote locator. A native runtime mismatch must be resolved before actual
local execution; it is never a reason to save into registry instead.

Aliases are bounded lowercase identifiers using letters, digits, `.`, `_`, or
`-`; they are scoped to an execution environment. Personal paths never enter Git
or Skill packages. Saving a project never grants access or selects Local mode.

## Materialize a temporary lookup for actual local access

The registry is a derived conversation cache under the platform temporary
`codex-loop/workspace-sessions` directory, keyed by a conversation nonce. It never
reads or writes `~/.codex-loop/workspace-registry.json`. Old files are left untouched;
there is no automatic migration or deletion. A new chat starts without its old
cache or grants. The cache never stores authorization; grant state is separate.

On the pinned local environment, read the current source project locator through
the controller first, then inspect its directory/realpath through the selected
connector. Materialize only this verified location (or a current-task directory):

```bash
python3 scripts/codex_loop.py workspace-materialize \
  --name epiagent --path "/absolute/path/to/EpiAgent" --kind repository
```

The first materialization returns `session_id`; retain it only in current chat
memory. Pass the same nonce to subsequent commands, or supply it through a
conversation-scoped `CODEX_LOOP_SESSION_ID`. Do not persist it in Host Profile,
user memory, task/repository state, or any cross-chat store. It is bound to the
selected environment; never reuse it on another computer.

```bash
python3 scripts/codex_loop.py workspace-registry-list --session-id SESSION_NONCE

python3 scripts/codex_loop.py workspace-grant epiagent \
  --session-id SESSION_NONCE --current-user-authorization-observed \
  --authorization-evidence "current user authorized this exact directory"

python3 scripts/codex_loop.py workspace-resolve epiagent \
  --session-id SESSION_NONCE \
  --host-authorized-root "/host/observed/authorized/root" --require-access

python3 scripts/codex_loop.py workspace-grants --session-id SESSION_NONCE
python3 scripts/codex_loop.py workspace-forget epiagent --session-id SESSION_NONCE
```

Materialization and forgetting never edit Host Profile. Supported kinds are
`repository` and `development_root`. Updating an existing cached entry requires
`workspace-materialize --update` with the same nonce. Cache writes validate schema
and replace atomically; corrupt files fail instead of being silently reset.

Re-read the source locator before using a saved alias. A changed location requires
fresh inspection, cache update, and task path authority; an old cached entry must
never override the profile. Changing the cached alias/path/kind invalidates its
older grant. Session-grant state stores only fingerprints and evidence digests,
never raw consent text or project paths. `workspace-grant` records consent already
observed by the host; it does not manufacture user consent or connector permission.

## Access and binding

Actual access requires a real directory, current task path authority, and observed
host/connector permission. `--host-authorized-root` records a boundary already
verified by the host; it cannot change connector permissions. A missing directory,
changed realpath/symlink, denied root, unknown alias, or mismatched grant fails
closed. Never search home, parent directories, or the whole disk for a replacement.
Ask for the exact location when it cannot be obtained from the current source.

A grant covers that exact root, not its parents or siblings. Multiple roots may
be accessible, but each lifecycle binds to one canonical Git working tree:

```text
Primary Local Root + Session Granted Roots = Effective Local Roots
```

Saving locations, local source mutation, and computer-use authorization remain
separate. Existing lifecycle bindings do not move when preferences change.
