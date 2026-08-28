# Capability and permission preflight

Use one bounded preflight stage before substantive execution when the planned workflow depends on external integrations, host permissions, or local interaction capabilities.

The purpose is to avoid discovering predictable permission blockers halfway through a task. Preflight does not weaken host security or grant itself permissions.

## Procedure

1. Resolve `workspace_mode` and the intended `interaction_target` first.
2. Infer the capabilities required by the reasonably planned workflow, including downstream steps the user already requested such as publish, sync, browser validation, or local GUI work.
3. Inspect only the relevant live connection/capability state.
4. Batch missing connection, authorization, or setup requests into one user-facing preflight whenever the host supports doing so.
5. After required capabilities are available, continue the task without re-asking for capabilities that remain valid.
6. Re-run preflight only if the workflow expands to a new capability or an already-checked capability becomes unavailable.

Request the capabilities needed by the task, not every integration the host happens to offer.

## Common capability sets

- Web repository edit only: current writable Web workspace; no RDC requirement.
- Web-mode GitHub publication: Google Drive staging access, GitHub connector access, and the repository's audited Actions prerequisites.
- Local repository edit: RDC access plus resolved/authorized `LOCAL_ROOT`.
- Local native-Git publication: the Local edit capabilities plus host-owned native Git authentication/network access.
- `local_chrome`: local Chrome availability plus a supported host Chrome bridge or RDC-backed Chrome automation.
- `local_mac_gui`: RDC plus any macOS Accessibility/Screen Recording permissions genuinely needed by the chosen action/observation transport.

## What may persist

Persist only non-sensitive routing defaults that the user explicitly wants to reuse, such as `default_local_root` in the host-local configuration described by `local-mode-setup.md`.

Do not persist OAuth tokens, Git credentials, browser cookies, passwords, connector secrets, approval tokens, or a claim that a permission is permanently granted. Connector/RDC/browser permission state remains host-owned and must be checked live when needed.

Within a task, remember successful preflight observations so the agent does not repeatedly interrupt the user for the same already-satisfied capability.

## Host approval boundary

A preflight can consolidate setup and use persistent permissions that the host already supports. It cannot bypass host-enforced per-action confirmation, sandbox policy, or high-impact-action review.

If the host requires a fresh approval for a particular sensitive write/action, request that approval at the required boundary. Do not describe the preflight as "full auto" or imply that user security controls have been disabled.

## Failure behavior

If a required capability cannot be established during preflight, report the missing capability before making unrelated source mutations when practical. Preserve the authoritative workspace and do not silently change `workspace_mode`, interaction transport, publication transport, or trust boundary just to avoid the blocker.
