# Known workspace registry and conversation session grants

Codex Loop separates persistent knowledge of local workspace locations from permission to access them. The three states are intentionally independent:

```text
KNOWN    registry knows alias -> absolute path
GRANTED  this conversation carries an explicit grant for that exact registry entry
BOUND    one durable task is bound to one canonical Git working tree
```

`KNOWN != GRANTED`, `GRANTED != BOUND`, and `KNOWN != BOUND`.

## Persistent registry

The host-local registry is `~/.codex-loop/workspace-registry.json`. It is outside repositories and outside the packaged Skill. V1 uses this schema:

```json
{
  "version": 1,
  "workspaces": {
    "piwork": {
      "path": "/absolute/path/to/PiWork",
      "kind": "development_root"
    },
    "epiagent": {
      "path": "/absolute/path/to/EpiAgent",
      "kind": "repository"
    }
  }
}
```

Supported kinds are `development_root` and `repository`. Aliases are trimmed, lowercased, and must use letters, digits, `.`, `_`, or `-`. Canonical aliases are globally unique.

The registry stores identity/location only. It must never store fields such as `authorized`, `always_allow`, `trusted`, `granted`, or any equivalent permission state. Registration therefore never grants filesystem access and never selects Local mode.

Registry writes validate the complete document, fsync the temporary file, atomically replace the registry, and fsync the containing directory where supported. Invalid JSON or schema fails closed and is never silently replaced with an empty registry.

User-specific absolute paths must never be committed to `SKILL.md`, `README.md`, `references/`, Git-tracked config, or release artifacts.

## Register, list, resolve, update, and remove

Register a workspace only with a real absolute directory. The runtime canonicalizes it with `realpath` before persistence:

```bash
python3 scripts/codex_loop.py workspace-register \
  --name epiagent \
  --path "/absolute/path/to/EpiAgent" \
  --kind repository
```

List known workspaces:

```bash
python3 scripts/codex_loop.py workspace-registry-list
```

Resolve identity/location without claiming access:

```bash
python3 scripts/codex_loop.py workspace-resolve epiagent
```

An existing canonical alias cannot be overwritten accidentally. Updating its path or kind requires explicit update:

```bash
python3 scripts/codex_loop.py workspace-register \
  --name epiagent \
  --path "/new/absolute/path/to/EpiAgent" \
  --kind repository \
  --update
```

Remove an entry explicitly:

```bash
python3 scripts/codex_loop.py workspace-remove epiagent
```

Updating or removing a registry entry never creates a grant. A grant is fingerprint-bound to the exact registered alias/path/kind, so changing an entry makes an older conversation grant stale rather than silently transferring it to the new path.

## Conversation-scoped grant capability

A workspace grant is ephemeral authorization bookkeeping. It is not stored in the registry and is not a host permission source.

`workspace-grant` requires concise evidence that the ChatGPT host/model has already observed explicit user authorization in the current conversation:

```bash
python3 scripts/codex_loop.py workspace-grant epiagent \
  --authorization-evidence "user explicitly granted EpiAgent path access in this conversation"
```

If no session id is supplied, the command creates a high-entropy conversation session nonce and returns it. The agent keeps that nonce only in the current conversation context and passes it to later grant/resolve operations:

```bash
python3 scripts/codex_loop.py workspace-grants --session-id SESSION_NONCE

python3 scripts/codex_loop.py workspace-resolve epiagent \
  --session-id SESSION_NONCE
```

The nonce may alternatively be supplied through `CODEX_LOOP_SESSION_ID` by a host that already has a conversation-scoped ephemeral channel. Never write the nonce into the repository, `host.json`, the workspace registry, user memory, or another cross-conversation store. A new conversation has no old nonce and therefore starts with no usable grants even though the registry persists.

The runtime stores only the workspace fingerprint and a SHA-256 digest of the authorization evidence; it does not persist the raw authorization phrase or the registered path in session-grant state.

The bookkeeping command does not manufacture permission. The required `--authorization-evidence` is a record of host-observed user consent, analogous to `git-authorize`: the host remains responsible for deciding whether the user's words are explicit authorization.

Examples that count as explicit grants include:

```text
Give EpiAgent path permission.
Allow access to the EpiAgent local workspace for this conversation.
This conversation may use EpiAgent.
```

Requests such as `modify EpiAgent`, `look at EpiAgent`, `you know where EpiAgent is`, or `EpiAgent has a local copy` do not grant the path by themselves. If the alias is KNOWN but not GRANTED, ask for the grant without asking the user to repeat the absolute path.

## Host/RDC authorization and realpath enforcement

A semantic grant is necessary but insufficient. Actual access requires all three conditions:

```text
REGISTERED + EXPLICITLY GRANTED THIS CONVERSATION + HOST/RDC AUTHORIZED = ACCESSIBLE
```

Before a repository-affecting RDC operation, pass only host-observed authorized roots to resolution and require access:

```bash
python3 scripts/codex_loop.py workspace-resolve epiagent \
  --session-id SESSION_NONCE \
  --host-authorized-root "/host/observed/authorized/root" \
  --require-access
```

`--host-authorized-root` is evidence supplied after the host has actually confirmed its filesystem boundary. It is not a way for the runtime to alter RDC `allowedDirectories` or self-authorize a path.

The runtime resolves both the registered workspace and host roots to real paths. A registered path that disappeared, became non-directory, or now resolves through a symlink to a different target is unusable. Do not search the home directory, parent directories, or whole disk to guess a replacement. Ask for explicit re-registration.

A grant covers only the exact registered workspace/root. It does not imply a grant for its parent or siblings. A broader host-authorized directory may contain the workspace, but the conversation grant is still checked against that exact registry entry.

## Effective local roots and task binding

For Local mode, the agent reasons about:

```text
Primary Local Root + Session Granted Roots = Effective Local Roots
```

The primary root is the development root explicitly selected for Local mode. Session-granted roots can add other registered repositories or development roots for this conversation after host/RDC authorization is confirmed.

Multiple effective roots do not merge source baselines. Each durable task still binds through the existing `workspace-binding` mechanism to exactly one canonical Git working tree. Access to PiWork and EpiAgent at the same time does not make one repository a substitute for the other.

PiWork uses the same registry mechanism as every other persistent workspace. Register it as `kind=development_root`; do not keep a second PiWork-specific path table. `host.json` may name `piwork` as the preferred primary workspace alias, while older `default_local_root` configuration is treated only as a migration/compatibility input after explicit Local-mode intent.

## Required invariants

1. Registered path is not authorized path.
2. Persistent registry never stores permission. Persistent registry never stores authorization.
3. Conversation grants require a conversation nonce that is not persisted across conversations.
4. Knowing an alias never selects Local mode or filesystem access by itself.
5. A grant applies only to the exact current registry fingerprint for that alias.
6. Host/RDC enforcement always wins.
7. One durable task binds to one canonical Git working tree.
8. Registry discovery never triggers whole-home or whole-disk search.
9. Registry mutation invalidates old grants for the changed entry.
10. Local source mutation and computer-use authorization remain separate task-scoped gates.
