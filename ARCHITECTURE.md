# Codex Loop Architecture

```mermaid
flowchart TD
  U[User objective] --> S[Skill admission]
  S --> P{Predictable GitHub/Drive use?}
  P -->|yes| W[Early permission prewarm<br/>Git object + same-SHA ref / Drive sentinel]
  P -->|no| R
  W --> R[Semantic intent router]
  R --> WM[workspace_mode]
  R --> IT[interaction_target]
  R --> DT[deployment_target]
  WM --> O[Objective lifecycle]
  IT --> O
  DT --> O
  O --> A[Observe / Act]
  A --> V[Validation when useful]
  A -. local or RDC writer .-> G[Bound task-owned output growth]
  V --> C[Upstream-style completion audit]
  C -->|CONTINUE| A
  C -->|PASS / BLOCKED| E[Terminal result]
  O -. optional .-> D[Delegation / persistence / managed processes]
  R -. Web host gap .-> WA[Web source/publish adapters]
  WA --> GH[GitHub]
  WA --> GD[Google Drive temporary staging]
  O -. Skill delivery .-> K[Build + validate skill.zip]
  K --> X[Fresh current-conversation artifact exposure]
  X --> UI[Manual Plugins -> Plugin Directory -> Skills -> Create -> Upload]
  UI --> IS[Installed Skill]
```

## Boundaries

- ChatGPT host owns model sampling, tool dispatch, sandboxing, approvals, connector authentication, conversation context, and the actual current-conversation artifact reference.
- Codex Loop owns objective continuity plus deterministic state that is genuinely needed for execution.
- The Skill router is the lifecycle admission; Codex Loop does not run a second direct-vs-durable admission classifier.
- Routing keeps the three independent axes because identical semantic intents may require different transports in Web and Local environments.
- GitHub/Drive permission prewarm is intentionally early. Web publication prewarms both Git-object write and persistent-ref write with a no-movement same-SHA ref update; Drive write/delete is prewarmed with an exact create/read/delete sentinel.
- Local/RDC execution safety bounds task-owned output growth directly. It does not use remaining free disk as a task-admission threshold.
- Review is semantic model work over the actual final diff, not a stored review receipt. Git state is observed directly rather than pre-authorized through bookkeeping.
- Exact Codex Loop-created permission sentinels and staging objects are cleaned automatically. Pre-existing user files and durable deliverables remain outside that cleanup authority.
- Skill package bytes, fresh conversation artifact exposure, and product installation are separate boundaries. Generated Skill packages are never routed through a presumed Library object; ChatGPT Web installation is the manual upload path shown above.
