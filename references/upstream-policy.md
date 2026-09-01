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

## Architecture fidelity governance

Source lineage is necessary but not sufficient. For every material upstream concept that affects user-visible behavior or lifecycle semantics, maintain `references/architecture-fidelity.yaml` with: `upstream_concept/watch surface`, `control-plane layer`, Codex Loop alignment status, known divergence/degradation, and an upgrade path.

Use **semantic parity before implementation parity**: preserve the upstream invariant and authority boundary first; only then choose exact reuse, a behavioral port, a host adapter, or an intentional local extension. `HOST_DELEGATE` is not a complete explanation by itself. Distinguish an equivalent host capability from a partial equivalent and a genuinely missing host primitive. When a primitive is missing, keep the local adapter thin enough to be replaced without rewriting objective semantics.

An upstream advance audit has three independent dimensions:

1. **Source Delta** — mapped source/resources/modules changed.
2. **Control-plane Delta** — lifecycle contributors, event protocols, state/thread/turn/item contracts, tool lifecycle, budgets, queueing, or extension registries changed.
3. **Concept Delta** — user-visible behavior or a unifying upstream abstraction changed even when the previously mapped core files did not.

`UPSTREAM_AUDIT_PASS` requires all three dimensions to be reviewed. Any architecture watch surface classified `NEEDS_REVIEW`, or any partial/divergent surface without both `divergence` and `upgrade_path`, fails `scripts/audit_source_coverage.py`. The architecture observation pin is independent from the frozen exact-resource maintenance baseline; advancing one does not silently advance the other.
