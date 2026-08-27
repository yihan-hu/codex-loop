# Local mode setup and `LOCAL_ROOT` contract

Use this reference whenever a conversation enters local development through Remote Desktop Commander (RDC), or when a local workspace root must be resolved.

## `LOCAL_ROOT`

`LOCAL_ROOT` is the conversation-resolved absolute filesystem root that the user has authorized RDC to access for persistent development. It is a logical contract name, not a hard-coded author path and not necessarily a persistent operating-system environment variable.

Examples such as `/Users/alice/PiWork` are illustrative only. Never copy an example path into a user's execution plan unless that exact path was established for the current user.

Resolve `LOCAL_ROOT` in this order:

1. Reuse the exact root already established for Local mode earlier in the current conversation.
2. Otherwise, use an absolute root explicitly named by the user when they select Local mode.
3. If the host exposes a single explicit RDC-authorized workspace root as tool metadata, that root may be used after confirming it is the intended development root.
4. Otherwise ask once for the exact absolute root and require the user to authorize that root in RDC.

Do not infer a root from the repository author's home directory, a stale prior conversation, a downloaded archive path, or filesystem visibility outside the authorized boundary.

## Conversation and task scope

A new conversation starts in Web mode. Selecting Local mode activates the resolved `LOCAL_ROOT` for later repository tasks in that same conversation until the user explicitly switches back to Web mode.

Development-location resolution must happen before any RDC/local-filesystem discovery or repository operation. Do not use RDC to look for a local checkout first and then infer that the conversation is in Local mode. An explicit request to synchronize a verified Web-mode push to the Mac permits a downstream local synchronization phase only after Web publication has completed; the local repository must be updated from the exact verified remote commit rather than consulted as a competing development baseline.

If the current ChatGPT/Web workspace lacks an obvious write or publication bridge, that absence does not resolve `LOCAL_ROOT` and does not authorize Local mode. Stay in Web mode and surface the missing capability instead of probing the Mac.

The development-location choice is conversation-scoped, but each durable runtime task still binds independently to one canonical Git working tree under `LOCAL_ROOT`. Sibling repositories and worktrees do not become interchangeable source baselines.

A new conversation does not inherit Local mode merely because RDC remains connected or the same local repository still exists. Local mode must be explicitly selected again; the local root can then be resolved from the new conversation and host authorization state.

## RDC authorization boundary

Treat the resolved `LOCAL_ROOT` as the persistent pre-authorized filesystem boundary for Local mode only when RDC actually permits access to it. Host enforcement and the Skill boundary are cumulative; the narrower boundary wins.

Keep repository discovery, clones, worktrees, source edits, tests, builds, packaging, scratch data, release staging, receipts, and terminal/Git operations under `LOCAL_ROOT` unless the user explicitly grants a narrower-purpose temporary root elsewhere.

If `LOCAL_ROOT` is unresolved, ambiguous, or rejected by RDC, stop local filesystem operations and surface that exact setup boundary. Do not search the user's home directory or whole disk to guess a usable path.

## Command examples

Before a host-visible shell command needs the root, substitute the actual resolved absolute path. Do not rely on an environment variable surviving across separate RDC process calls.

For documentation, this form is acceptable:

```bash
LOCAL_ROOT=/Users/alice/PiWork
cd "$LOCAL_ROOT/example-repo"
```

The example assignment is illustrative. The real command must use the user's resolved root.

If a root-local GitHub CLI/config layout is desired, derive it from `LOCAL_ROOT` rather than a username-specific path:

```bash
GH_CONFIG_DIR="$LOCAL_ROOT/.gh"
GH_BIN="$LOCAL_ROOT/tools/gh/.../bin/gh"
```

Credential material remains host-owned. Never read tokens, SSH keys, or credential-store contents directly.

## Fail-closed rule

Never replace an unresolved `LOCAL_ROOT` with an author path, `~`, `/tmp`, the current ChatGPT workspace, or another convenient directory. Resolve and authorize the real persistent root first.
