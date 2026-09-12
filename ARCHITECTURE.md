# Codex Loop Architecture

```mermaid
flowchart TD
  U[Codex Loop selected + user request] --> L[Create lifecycle instance ALWAYS]
  L --> B[Scope contract<br/>user owns WHAT / model owns HOW]
  L --> RQ[Retained request + later steers]
  L -. repository/filesystem task .-> W[Bind / observe workspace]
  W --> RI[Applicable repository instructions]
  W --> PW[Pre-existing user work]
  B --> H[Host model / native agent loop]
  RQ --> H
  RI --> H
  PW --> H
  B -. bounds every substantive change .-> H
  H <--> T[Observe / edit / tools]
  T --> V[Targeted validation]
  V --> H
  L -. when useful .-> P[Plan: pending / in_progress / completed]
  L -. long/noisy transition .-> C[Checkpoint / cross-chat persistence]
  H -. large or risky change .-> Q[One Codex-style semantic review]
  Q -->|finding| H
  Q -->|clean| F[Final semantic acceptance]
  H --> F
  F --> D[Deterministic finish check]
  D -->|clear| E[Done]
  D -->|real blocker| H
  H -. consequential side effect .-> G[Routing / sandbox / approval / external-action reconciliation]
  G --> X[GitHub / Drive / Local host / deployment]
  H -. only when needed .-> M[Delegation / managed processes]
  C -. restore .-> K[Continuation state inspection]
  K --> RQ
  K --> H
```

## Boundaries

- The effective user request plus later user corrections is the scope authority. Plans, objectives, reviews, architecture preferences, discovered cleanup, and model judgment may choose execution but never authorize additional work.
- Skill selection creates one real lifecycle instance immediately. Codex Loop does not run a second direct-vs-durable admission classifier after selection and does not wait for repository acquisition or persistence needs before creating lifecycle state.
- The standard lifecycle is always active and lightweight: retain request authority, observe the relevant environment, execute natively, validate where useful, perform final semantic acceptance, then run deterministic finish checks.
- Workspace binding is lifecycle-internal and optional. Repository/filesystem work loads scoped repository instructions and pre-existing user work before mutation; deeper instruction scopes are loaded before first touch.
- Continuation words such as `continue` / `resume` / `继续` first inspect the existing lifecycle state and current reality. They never create a replacement lifecycle or reset the request anchor.
- The host model owns reasoning, task decomposition, ordinary inspection/edit/test/repair decisions, semantic review, and final acceptance inside the user-authorized scope.
- Codex Loop lifecycle state is intentionally thin and mandatory. Plans, workspace baselines, checkpoints, cross-chat persistence, delegation, and process/external-action bookkeeping are added only when the objective uses them.
- `completion` checks deterministic blockers only. It is not an outer semantic review and does not require criterion PASS records, steer acknowledgements, repeated fresh checker passes, or a requirement-by-requirement objective audit.
- Validation is host-visible and direct. A host-observed result can be recorded without a validation-plan handshake. Repairs trigger only affected revalidation unless broader regression confidence is justified.
- A separate semantic review is optional and normally singular. Large/risky changes use one Codex-style review over the actual change; substantive findings are repaired and targeted checks rerun.
- Routing, sandbox/approval, non-idempotent external-action reconciliation, protected user work, and task-owned process cleanup remain deterministic because they guard real side effects rather than reasoning quality.
- Persistence, delegation, managed processes, publication adapters, workspace cache, and GUI/browser routing remain lazy branches; they add no steps to the default happy path when unused.
- ChatGPT host owns model sampling, tool dispatch, connector authentication, sandboxing/approvals, hidden context, and conversation persistence.
