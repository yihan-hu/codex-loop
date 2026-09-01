# Capability and permission preflight

Use one bounded preflight stage before substantive execution when the planned workflow depends on external integrations, host permissions, or local interaction capabilities.

The purpose is to avoid discovering predictable permission blockers halfway through a task. Preflight does not weaken host security or grant itself permissions.

## Procedure

1. Resolve `workspace_mode` and the intended `interaction_target` first.
2. Infer the capabilities required by the reasonably planned workflow, including downstream steps the user already requested such as publish, sync, browser validation, or local GUI work.
3. Inspect only the relevant live connection/capability state. For `local_chrome` or `local_mac_gui`, checking that a transport is connected is not permission to interact with the user's computer; do not inspect tabs/windows or take GUI/browser actions before explicit current-task authorization.
4. Batch missing connection, explicit computer-use authorization, or setup requests into one user-facing preflight whenever the host supports doing so.
5. After required capabilities are available, continue the task without re-asking for capabilities that remain valid.
6. Re-run preflight only if the workflow expands to a new capability or an already-checked capability becomes unavailable.

For `local_chrome`, keep `browser_host_health` separate from `browser_session_health`. If the extension/native host is healthy but the current conversation has no Browser executor, classify `SESSION_BROWSER_CAPABILITY_MISSING` and stop Browser execution at that boundary rather than repairing Chrome again or switching to RDC/AppleScript.

Request the capabilities needed by the task, not every integration the host happens to offer.

## Common capability sets

- Web repository edit only: current writable Web workspace; no RDC requirement.
- Web-mode GitHub publication: Google Drive staging access, GitHub connector access, and the repository's audited Actions prerequisites.
- Optional cross-conversation persistence: check Google Drive only when the user enabled persistence or made recoverability a requirement. Persistence is off by default; a disconnected Drive must not block ordinary tasks. Credentials remain host-owned.
- Local repository read/inspection: RDC access plus resolved/authorized `LOCAL_ROOT`; this does not authorize source mutation.
- Local repository edit: the Local read capabilities plus explicit current-task local-source-mutation authorization.
- Local native-Git publication of already-existing audited content: the Local read capabilities plus host-owned native Git authentication/network access; source integration/conflict resolution additionally requires explicit current-task local-source-mutation authorization.
- `local_chrome`: explicit user authorization for computer use in the current task, plus local Chrome host health and a supported Browser/Chrome executor attached to the current conversation. Read `browser-control-recovery.md`; do not treat RDC/AppleScript automation as Browser Control fallback.
- `local_mac_gui`: explicit user authorization for computer use in the current task, RDC, plus macOS Accessibility and any Screen Recording permission genuinely needed by the chosen observation transport. Read `local-mac-gui.md`; prefer Accessibility element targeting and independently verify GUI results.

## What may persist

Persist only non-sensitive host preferences/defaults that the user explicitly wants to reuse, such as the preferred local workspace or progress-visibility settings in the host-local configuration described by `local-mode-setup.md` and `progress-visibility.md`.

Do not persist OAuth tokens, Git credentials, browser cookies, passwords, connector secrets, approval tokens, or a claim that a permission is permanently granted. Connector/RDC/browser permission state remains host-owned and must be checked live when needed.

Within a task, remember successful preflight observations so the agent does not repeatedly interrupt the user for the same already-satisfied capability.

## Host approval boundary

A preflight can consolidate setup and use persistent permissions that the host already supports. It cannot bypass host-enforced per-action confirmation, sandbox policy, or high-impact-action review.

If the host requires a fresh approval for a particular sensitive write/action, request that approval at the required boundary. Do not describe the preflight as "full auto" or imply that user security controls have been disabled.

## Failure behavior

If a required capability cannot be established during preflight, report the missing capability before making unrelated source mutations when practical. Preserve the authoritative workspace and do not silently change `workspace_mode`, interaction transport, publication transport, or trust boundary just to avoid the blocker.
