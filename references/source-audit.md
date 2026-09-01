# Codex upstream source audit

Pinned maintenance baseline: `openai/codex@c9b19deb09c1841ce7acc33ddb96276030936a29` (2026-08-23).

Advance audit on 2026-08-23: the original 2026-08-22 maintenance pin is 14 commits behind this baseline. The intervening changes touch MCP runtime status, context-fragment annotations, session/context metadata, TUI, SDK, and one final Guardian review thread-source metadata change. None of the seven exact vendored/extracted resources or the direct command-canonicalization, shell-snapshot, exec-environment, or unified-exec source inputs changed; host/session/context evolution remains host-owned.

`references/source-map.yaml` is the machine-readable coverage contract. It classifies every direct module declared by the pinned `codex-core` root plus the `tools`, `session`, `tasks`, and `unified_exec` indexes. Run:

```bash
python scripts/audit_source_coverage.py --upstream /path/to/openai-codex
```

against a checkout at the pinned commit. Newly added, removed, or unclassified direct modules fail the audit rather than silently falling through.

The current audit added `session/turn_suspension` as a direct Session submodule and classifies it `HOST_DELEGATE`: unfinished-turn suspension/recovery depends on Codex-owned thread history, task cancellation, and session persistence rather than a deterministic Skill helper. Unified Exec also gained host cancellation-token plumbing; the local process/output mechanics remain valid, while tool-call/session cancellation authority stays host-owned. Recent upstream changes to managed filesystem deny-read rules, Guardian, MCP, hooks, and browser/computer-use policy reinforce the same boundary: the local runtime may be stricter, but never acts as sandbox/permission authority. Shell startup/profile execution likewise stays host-visible; the Skill retains exact snapshot resources plus a capture-plan adapter.

## Fidelity rule

Use the order `EXACT_VENDOR -> EXACT_EXTRACT -> THIN_WRAPPER -> MINIMAL_DERIVATIVE -> LOCAL_RUNTIME_PORT/BEHAVIORAL_PORT -> HOST_DELEGATE`. Never introduce Rust/Codex/App Server merely to increase copy percentage. A cross-language Python implementation is always a port, never a minimal patch. Keep intentional divergence explicit in `source-map.yaml` and back local ports with compatibility/regression tests.

## Local delegation extension

Delegation / Logical Isolation is a Codex Loop / Chatbox local extension, not an upstream Codex multi-agent port. It manages only local delegation lifecycle, bounded context projection metadata, warnings, checkpoint linkage, structured result persistence, and reconciliation. Actual model invocation and native multi-agent authority remain host-owned. The pinned source-map classifications for `spawn` and `multi_agents` remain `HOST_DELEGATE`; this extension does not reclassify them.
## Local canonical workspace / release extension

Canonical workspace binding, commit/tree-bound release receipts, and native-Git publish orchestration are Codex Loop local extensions. They do not claim to port Codex network, credential, or GitHub authority. Publishing is intentionally restricted to native Git executed by the host through Remote Desktop Commander on the persistent PiWork workspace; GitHub connector/object-API source upload is not a supported transport.

## Local guarded model-relay extension

`GUARDED_SINGLE_SHOT_RELAY` is a Codex Loop local extension for a user-explicit alternate data plane. It supplies deterministic framing, narrow ASCII-whitespace normalization, strict Base64 decode, size/SHA-256 verification, and atomic destination publication. The ChatGPT host still owns model/tool dispatch and cross-surface carriage; the extension does not claim an upstream Codex file-transfer primitive or host network authority.

## Architecture/control-plane watch

The core-module source map is intentionally complemented by `references/architecture-fidelity.yaml`. This closes the blind spot where important Codex behavior moves into `ext/*`, app-server protocol, feature registries, thread stores, agent graph, budgets, or lifecycle contributors without adding a new `codex-core` direct module.

Run `python scripts/audit_source_coverage.py` for the repository-side governance checks. When a checkout of the architecture observation pin is available, pass it separately with `--architecture-upstream /path/to/openai-codex` to assert watched paths and anchor patterns. Do not substitute the architecture observation pin for the exact-resource maintenance pin used by `source-verify`.
