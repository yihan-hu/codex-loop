# Verified Web-to-Local / Mac synchronization

Use this reference whenever repository bytes that are authoritative in Web mode need to be saved/synchronized to a Mac or another RDC host. This is a downstream binary transfer. It is **not** permission to make the local repository the development baseline and it does not require `workspace_mode=local`.

## Fixed data plane

There is exactly one supported automatic Web -> Local transfer path:

```text
current audited Web Git workspace
  -> exact self-contained verified Git bundle
  -> Google Drive binary staging via real file_uri
  -> exact Drive object id + size + SHA-256 readback
  -> minimum temporary download access needed by the authorized host
  -> RDC downloads the exact binary to the explicitly authorized local path
  -> local size + SHA-256 + git bundle verify
  -> optional Git import only under the separate local-source-mutation gate
  -> permanently delete the exact Drive staging object after verified consumption
```

Do not choose among transports. Do not substitute GitHub Actions artifacts, repository archive URLs, GitHub contents/blob/tree source relay, Dropbox/IDrive, an unmodeled direct binary bridge, model-carried Base64/chunks/heredocs, or source regeneration/retyping. A failure in the fixed path is a transfer blocker, not permission to invent a fallback.

## Deterministic planner

Before transfer, run:

```bash
python3 scripts/codex_loop.py web-local-sync-plan --cwd REPO \
  --session-id ROUTING_SESSION \
  --destination-path /AUTHORIZED/LOCAL/PATH \
  --workspace-granted \
  --local-computer-authorized
```

The planner requires a clean audited Web commit, fresh validation/review when required, current Web routing, and the dedicated `rdc_transfer` gate. `rdc_transfer` means **downstream binary destination only**. It is intentionally distinct from `rdc_repository`, which remains unavailable in Web mode because repository authority has not moved.

If the planner returns `WEB_LOCAL_SYNC_REQUIREMENTS_UNMET`, satisfy only the named requirements and rerun it. Do not change transport.

## Sequence

1. Keep `workspace_mode=web`. Record audited Web commit/tree.
2. Call `web-local-sync-plan` for the exact authorized destination path.
3. Build or reuse the exact self-contained Git bundle requested by the plan. A reusable bundle receipt must match current generation, source commit/tree, exact size/SHA-256, and `prerequisite_commit=None`.
4. Upload the real binary with Google Drive `upload_file(file_uri=...)` to the dedicated staging boundary. Do not model-transcribe the bytes.
5. Read the exact Drive object back and require expected parent, size, and object identity. Expose only the minimum temporary download access needed by the authorized RDC host.
6. Through Remote Desktop Commander, download that exact Drive object into the explicitly authorized destination path. Do not search the host for a convenient alternative path.
7. On the local host require exact byte size, SHA-256, and `git bundle verify` success before considering the transfer complete.
8. If the user only asked to save/synchronize the bytes, stop with Web still authoritative. If the user separately asks to import/update a local canonical repository, require the ordinary local workspace grant + current-task local-source-mutation authorization before changing repository refs/worktrees.
9. If the user separately chooses to continue development locally, only then record `route-transition --workspace-mode local --selection-evidence "..."` and bind the durable task to that canonical local worktree.
10. After verified local consumption, permanently delete the exact Drive staging object. Never broaden cleanup to sibling files/folders.

## Publication fallback

If a Web publication planner offers `local_handoff` and the user explicitly selects it, use this same fixed Drive -> RDC transfer to move the exact audited Git bundle. After local import identity is proven and Local mode is explicitly selected, publication proceeds only through the native-Git contract in `references/verified-native-git.md`.

## Windows

Windows uses the same fixed data plane and identity checks. RDC may use PowerShell/native Git to download and verify the bundle. Platform-specific command differences do not create an alternate transfer policy.
