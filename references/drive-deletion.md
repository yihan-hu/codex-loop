# Google Drive cleanup adapter

Use this reference after the calling workflow has already decided that the exact object is cleanup-eligible. This adapter controls dispatch/reconciliation only; it never expands cleanup authority, retention policy, ownership, age, parent scope, integration/completion gates, or user intent. Storage placement is governed by `drive-storage.md`.

## Identity gate stays authoritative

Before destructive cleanup, require a fresh readback that proves the exact target identity needed by the calling workflow: Drive ID, expected title, expected parent, and object kind. Apply any stronger workflow-specific gate first, such as verified staging consumption, TTL expiry, completed integration, or an empty-folder requirement.

A folder is not recursively cleanup-authorized merely because its folder object is eligible. Its children must already be absent or independently eligible under the calling workflow.

## Dispatch rule

1. Prefer a real provider trash operation when the active host/connector exposes one. Google Drive API v3 trash is `files.update` with `trashed=true`; do not emulate trash by moving the object to an ordinary folder.
2. The current ChatGPT Google Drive connector exposes `delete_file` as **permanent deletion** and does not expose `trashed` through `update_file`. Never describe this operation as trash.
3. Permanent deletion may be used only for an exact task-owned temporary object that the calling workflow already marked disposable and cleanup-authorized. Archive/retained objects are outside this adapter's automatic temporary cleanup path.
4. When permanent deletion is authorized, call the connected Drive `delete_file` operation for the exact proven ID using the connector-returned object URL when accepted.
5. If the connector rejects a **folder** URL before dispatch with a URL/parser validation error such as `Invalid Google Drive URL`, keep the same Drive ID and retry once with `https://drive.google.com/file/d/<EXACT_DRIVE_ID>/view`. This is URL normalization for the same object, not a fallback cleanup path.
6. A terminal provider success completes cleanup; do not immediately issue another read solely to prove absence. If dispatch may have occurred but the outcome is unknown, re-observe the exact Drive ID before any retry and reconcile the external action normally.

Permission, ownership, authentication, safety/confirmation, policy, rate-limit, and other connector failures do not qualify for the URL-normalization retry. The resource-form retry never bypasses provider permissions.

When the caller already has explicit per-object cleanup intent, including verified publication/transfer staging cleanup or a cleanup plan that marked the exact object disposable, do not ask for a second confirmation solely because URL normalization was needed.
