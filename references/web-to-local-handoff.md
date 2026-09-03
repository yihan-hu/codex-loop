# Verified Web-to-Local publication handoff

Use this reference only when repository source has already been created/audited in Web mode, FAST_PUBLISH cannot proceed, and the user explicitly selects Local handoff instead of the standard verified Web fallback.

## Design rule

The handoff moves **bytes and Git identity, not prose**. Never ask the model to recreate files, copy source through chat text, emit Base64 chunks, or re-run the implementation from memory. The audited Web commit/tree remains the source identity that must arrive locally unchanged.

When the current source already lives in Web mode, prefer the standard `FULL_VERIFIED_PUBLISH` Web fallback because it avoids a route transition and an extra host transfer. Local handoff is useful when the user explicitly wants the persistent local checkout, needs a local-only tool, or the standard Web path is unavailable/unacceptable.

## Sequence

1. Stay in `workspace_mode=web` while preparing the transfer. Require a clean audited Web HEAD, fresh validation/review, and record its exact commit + tree.
2. Build one **self-contained** verified Git bundle with `web-publish-bundle` and no prerequisite commit. Record exact byte size, SHA-256, bundle ref, source commit, and source tree.
3. Transfer the binary through a real binary bridge. Preferred bridge: upload the exact bundle with `file_uri` to the dedicated Drive staging boundary already used for Web publication, then expose only the minimum temporary download access needed by the RDC host. If the host exposes a direct binary bridge with equivalent integrity, it may be used instead.
4. Only after the user has explicitly selected Local mode, record `route-transition --workspace-mode local --selection-evidence "..."`, resolve/authorize `LOCAL_ROOT`, and run the ordinary `rdc_repository` gate. The transfer decision is not source-mutation permission.
5. Download the bundle into an authorized local temporary/staging path. Require exact size + SHA-256 before use, then run native `git bundle verify` host-visible.
6. Import/fetch only the declared bundle ref into the selected canonical local Git repository (or a fresh canonical worktree under `LOCAL_ROOT` when needed). Preserve unrelated user work. Do not overwrite a dirty/diverged local branch to make the handoff fit.
7. Require local imported commit == audited Web commit and local imported tree == audited Web tree. An identity mismatch stops the handoff.
8. After identity equality is proven, Local mode owns subsequent repository work. If publication is the goal, use `references/verified-native-git.md`: native Git push from the canonical worktree, then remote commit/tree readback.
9. Delete the exact temporary Drive/staging object after verified local consumption when the transport policy allows it. Do not broaden cleanup to siblings.

## Windows

Windows uses the same bundle and native-Git identity contract. Prefer RDC + PowerShell/native Git. Managed background sessions and POSIX-only primitives stay host-visible or fail only that step; they do not justify reconstructing the repository through model text.

## Fallback boundary

If the user rejects temporary Drive/public-link staging and no direct binary bridge exists, Local handoff is unavailable. Return to the user-choice boundary and offer standard verified Web publication or an explicitly authorized verified model relay. The model relay is byte-preserving and hash-verified but intentionally slow; it is never the default and must never become source regeneration.
