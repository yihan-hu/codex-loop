# Codex Loop Architecture

```mermaid
flowchart TD
  U[Codex Loop selected + user request] --> A[Mandatory lifecycle admission gate]
  A --> S{Lifecycle execution surface}
  S -->|Web/default| HR[Installed ChatGPT Skill runtime]
  S -->|Explicit Local| LR[Mac runtime cache via RDC<br/>~/.codex-loop/runtime-src]
  HR -->|bootstrap / resume| L[Lifecycle instance + task_id]
  LR -->|bootstrap / resume| L
  HS[ChatGPT host CODEX_LOOP_HOME/runtime] --> HR
  LS[Mac ~/.codex-loop/runtime] --> LR
  A -->|same objective + known task_id| L
  A -->|continuation + identity lost| RR[Resume on the same lifecycle surface]
  RR --> L
  A -->|selected lifecycle surface unavailable| Z[Fail closed<br/>no fallback lifecycle]
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
- Skill selection requires lifecycle admission before any substantive task action. For a new objective, `bootstrap` is the first task action and returns the `task_id`; before running it, use only the user's explicit development-location choice to select the lifecycle execution surface. Web/default objectives use the installed ChatGPT runtime. Explicitly Local objectives bootstrap through RDC on the Mac-local runtime so lifecycle durability does not depend on the ChatGPT host filesystem. An already-admitted continuation always reuses the same lifecycle surface and task id.
- The admission boundary fails closed. If the host cannot execute the runtime entrypoint, Codex Loop does not degrade into ordinary chat/tool execution. The current ChatGPT Skill surface cannot make this a native host dispatch interceptor, so the contract is enforced by the Skill entrypoint until such a hook exists.
- The standard lifecycle is always active and lightweight after admission: retain request authority, observe the relevant environment, execute natively, validate where useful, perform final semantic acceptance, then run deterministic finish checks.
- Workspace binding is lifecycle-internal and optional. Repository/filesystem work loads scoped repository instructions and pre-existing user work before mutation; deeper instruction scopes are loaded before first touch.
- Continuation words such as `continue` / `resume` / `继续` enter resume resolution before bootstrap. They never create a replacement lifecycle or reset the request anchor. Lifecycle task databases and workspace active-task pointers live on the lifecycle's owning execution surface: Web/default uses the ChatGPT host `CODEX_LOOP_HOME/runtime`; explicit Local uses the Mac-local `~/.codex-loop/runtime`. The two stores are not mirrors or fallbacks for one another. A ChatGPT host restart must therefore resume a Local objective through RDC against the Mac store rather than searching or recreating host-local state. Conversation-scoped routing/grant sessions remain temporary and are not promoted into durable lifecycle authority.
- The host model owns reasoning, task decomposition, ordinary inspection/edit/test/repair decisions, semantic review, and final acceptance inside the user-authorized scope.
- Codex Loop lifecycle state is intentionally thin and mandatory. Plans, workspace baselines, checkpoints, cross-chat persistence, delegation, and process/external-action bookkeeping are added only when the objective uses them.
- `completion` checks deterministic blockers only. It is not an outer semantic review and does not require criterion PASS records, steer acknowledgements, repeated fresh checker passes, or a requirement-by-requirement objective audit.
- Validation is host-visible and direct. A host-observed result can be recorded without a validation-plan handshake. Repairs trigger only affected revalidation unless broader regression confidence is justified.
- A separate semantic review is optional and normally singular. Large/risky changes use one Codex-style review over the actual change; substantive findings are repaired and targeted checks rerun.
- Routing, sandbox/approval, non-idempotent external-action reconciliation, protected user work, and task-owned process cleanup remain deterministic because they guard real side effects rather than reasoning quality.
- Persistence, delegation, managed processes, publication adapters, workspace cache, and GUI/browser routing remain lazy branches; they add no steps to the default happy path when unused.
- ChatGPT host owns model sampling, tool dispatch, connector authentication, sandboxing/approvals, hidden context, and conversation persistence.
