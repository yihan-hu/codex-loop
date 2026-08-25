# Upstream Adaptation Policy

Use one classification for every upstream-derived component:

- `EXACT_VENDOR`: copy an upstream file byte-for-byte. Preserve its hash and license attribution.
- `EXACT_EXTRACT`: extract an independently executable literal/resource from an upstream source file without semantic edits. Store source symbol and local fragment hash.
- `THIN_WRAPPER`: wrap an exact resource only to adapt invocation or data plumbing.
- `MINIMAL_DERIVATIVE`: make the smallest source-level change needed for the host environment and mark the change prominently.
- `BEHAVIORAL_PORT`: reimplement observable semantics without copying source structure.
- `LOCAL_RUNTIME_PORT`: implement deterministic Codex runtime behavior as executable Skill code.
- `HOST_ADAPTER`: translate local state/protocol to a host capability.
- `HOST_DELEGATE`: keep authority in ChatGPT host because sandbox, approval, model, connector, or context ownership cannot be reproduced safely.
- `REFERENCE_ONLY`: use the source to inform tests/design only.
- `OMIT`: intentionally exclude nonessential functionality.

Do not upgrade a component to `EXACT_VENDOR` merely for fidelity if it drags in the Codex agent runtime, Rust toolchain, model client, sandbox stack, or unrelated dependency graph. Prefer the smallest deterministic unit that preserves the useful semantics.
