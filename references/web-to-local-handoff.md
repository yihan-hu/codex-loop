# Verified Web-to-Local / Mac transfer and synchronization

Use this reference whenever bytes in the current ChatGPT/Web workspace need to be copied, saved, moved, or synchronized to a Mac or another RDC host. It covers both ordinary files and Web-authoritative repository synchronization. This is a downstream binary transfer. It is **not** permission to make a local repository the development baseline and it does not require `workspace_mode=local`.

For an ordinary file-transfer request, the request itself is sufficient current-task intent to select this Drive -> RDC data plane and to satisfy the narrow `rdc_transfer` computer-use intent. Do not ask the user for a second transfer/data-plane/computer-use authorization. Destination-path access and host-enforced connector/RDC permissions remain separate gates.

## Fixed data plane

There is exactly one supported automatic Web -> Local transport family:

```text
ordinary file
  -> exact source bytes + size + SHA-256
  -> Google Drive binary staging via real file_uri
  -> exact Drive object id + size readback
  -> minimum temporary download access needed by the authorized host
  -> RDC downloads the exact binary to the authorized local path
  -> local size + SHA-256 verification
  -> permanently delete the exact Drive staging object after verified consumption

Web-authoritative repository
  -> exact self-contained verified Git bundle
  -> the same Google Drive staging -> RDC path
  -> local size + SHA-256 + git bundle verify
  -> optional Git import only under the separate local-source-mutation gate
  -> permanently delete the exact Drive staging object after verified consumption
```

Do not choose among transports. Do not substitute GitHub Actions artifacts, repository archive URLs, GitHub contents/blob/tree source relay, Dropbox/IDrive, an unmodeled direct binary bridge, model-carried Base64/chunks/heredocs, or source regeneration/retyping. A failure in the fixed path is a transfer blocker, not permission to invent a fallback. If the configured staging boundary is public-read, do not stage credentials, secrets, or content that cannot tolerate that temporary exposure.

## Ordinary file transfer

For a non-repository file, do not require Git cleanliness, validation, change review, a Git bundle, or `workspace_mode=local`.

1. Resolve the exact source file bytes in the current ChatGPT/Web workspace and compute exact byte size plus SHA-256.
2. Initialize/check routing as usual, then call `route-check --action rdc_transfer` for the authorized destination. When the user explicitly asked to move/save/copy/deliver the file to the local host, treat that request as the evidence for `--local-computer-authorized`; do not ask again. Pass the existing current-conversation destination/workspace grant when one is required by the host boundary.
3. Upload the real file with Google Drive `upload_file(file_uri=...)` into the configured binary staging boundary. Do not model-transcribe the bytes.
4. Read back the exact Drive object and require the expected object identity, parent, and size. Use only the minimum temporary download access needed by the authorized RDC host.
5. Through RDC, download that exact Drive object to the requested/authorized destination path. Write to a temporary sibling when practical, verify local byte size and SHA-256 against the source, then atomically publish/rename the destination.
6. After verified local consumption, delete only the exact staging object according to the staging transport cleanup contract.

This flow needs no separate user authorization to choose Drive. Host-native permission prompts, connector connection requirements, and destination-path authorization are not bypassed. If the Drive staging bridge is unavailable or the file cannot tolerate the staging trust boundary, stop with a precise transfer blocker. Do not silently switch to model relay; model-carried transfer remains explicit-only.

## Deterministic planner

Before transfer, run:

```bash
python3 scripts/codex_loop.py web-local-sync-plan --cwd REPO \
  --session-id ROUTING_SESSION \
  --destination-path /AUTHORIZED/LOCAL/PATH \
  --workspace-granted \
  --local-computer-authorized
```

The planner requires a clean audited Web commit, fresh validation when required, current Web routing, and the dedicated `rdc_transfer` gate. `rdc_transfer` means **downstream binary destination only**. It is intentionally distinct from `rdc_repository`, which remains unavailable in Web mode because repository authority has not moved.

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
