# Google Drive deletion adapter

Use this reference for every destructive Google Drive cleanup after the calling workflow has already decided that the exact object is eligible for deletion. This adapter controls dispatch and verification only; it never expands deletion authority, retention policy, ownership, age, parent scope, integration/completion gates, or user intent.

## Identity gate stays authoritative

Before dispatch, require a fresh readback that proves the exact target identity needed by the calling workflow: Drive ID, expected title, expected parent, and object kind. Apply any stronger workflow-specific gate first, such as verified staging consumption, TTL expiry, completed integration, or an empty-folder requirement.

A folder is not recursively cleanup-authorized merely because its folder object is eligible. Its children must already be absent or independently eligible under the calling workflow.

## Dispatch rule

1. Call the connected Drive permanent-delete operation for the exact proven Drive ID using the connector-returned object URL when that URL is accepted.
2. If the connector rejects a **folder** URL before dispatch with a URL/parser validation error such as `Invalid Google Drive URL`, keep the exact same Drive ID and retry the same delete operation once with this resource-form URL:

   `https://drive.google.com/file/d/<EXACT_DRIVE_ID>/view`

3. Treat this as URL normalization for the same object and the same external-action identity, not as a fallback delete path. Do not search for a substitute object, change the parent, rename/move the target, or broaden cleanup scope.
4. Use the normalized retry only for a clear pre-dispatch URL/parser rejection. Permission, ownership, authentication, safety/confirmation, policy, rate-limit, and other connector failures do not qualify.
5. If dispatch may have occurred but the outcome is unknown, do not blindly retry. Re-observe the exact Drive object first and reconcile the external action according to the normal consequential-action rule.

The resource-form retry does not bypass a Drive permission or product safety restriction. It only gives the same exact folder ID to the same connector delete primitive in a URL shape that its parser accepts.

## Verification

After terminal success, perform a fresh exact-ID lookup against the expected parent scope and require that the deleted object no longer resolves. Do not infer absence from a broad title search. If the object still exists, or absence cannot be proven, keep the cleanup action as residue/`cleanup_pending` and report it rather than guessing.

When the caller already has explicit per-object cleanup intent, including verified publication/transfer staging cleanup or a cleanup plan that marked the exact object delete-ready, do not ask for a second confirmation solely because URL normalization was needed.
