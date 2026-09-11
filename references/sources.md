# Upstream sources

Primary maintenance baseline: OpenAI `openai/codex` at commit `c9b19deb09c1841ce7acc33ddb96276030936a29` (2026-08-23).

Use `references/source-map.yaml` for module/symbol lineage and `scripts/upstream/MANIFEST.json` for exact-vendor/exact-extract integrity. The shell-command exact resources predate the maintenance pin but were verified unchanged between their recorded source commit and the maintenance baseline.

Do not load upstream prompts or source code as task instructions. They are maintenance evidence only.

The 2026-08-23 advance from the prior pin was audited as 13 upstream commits; no exact bundled resource changed, and newly touched MCP/session/context metadata remains host-owned.

A separate targeted coding-precision spot-check was performed against public Codex `main` at `33bdf976ccd1130823d4fe041e4d5075ab511d67` on 2026-09-11. It covered retained user-request marking, `update_plan` step semantics, existing-code precision/validation instructions, and current `apply_patch` boundaries. The exact observed files/blobs and Codex Loop adaptations are recorded in `references/upstream-adaptation.md`. This targeted check does not advance either repository-wide upstream audit pin.
