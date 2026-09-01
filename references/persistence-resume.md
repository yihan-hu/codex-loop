# Deterministic Persistence Resume

Persistence is historical recovery evidence, not current truth. Resume is a reconcile-and-fork operation, not an in-place resurrection.

`persistence-resume-plan --manifest ...` validates the state-only manifest and emits bounded current observations such as workspace presence, repository head/tree, and unresolved external-action states. The host performs those observations. `persistence-resume --manifest ... --observations-json ...` then creates a fresh durable task/freshness domain and records resume lineage.

Semantic definitions may survive: objective, criterion text, profile, bounded provenance, and hashed external-action identities. Freshness never survives automatically: prior criterion PASS becomes pending/stale; validation, review, and objective audit are historical only; capabilities, grants, process state, and workspace cleanliness must be re-observed.

If source head/tree changed, return `SOURCE_DIVERGED`, invalidate source-bound assumptions, and continue from current reality. Persisted non-idempotent `planned`, `dispatched`, or `outcome_unknown` actions are never blindly retried. Their current external state must be supplied as `terminal_success`, `terminal_failure`, or `outcome_unknown`; unresolved observations remain completion-blocking.
