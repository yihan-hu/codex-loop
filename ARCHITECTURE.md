# Codex Loop Architecture

```mermaid
flowchart TD
  U[Codex Loop selected + exact user request] --> A[Mandatory lifecycle admission]
  A --> DRIVE[First invocation: current connected user My Drive]
  DRIVE --> PROFILE[Fixed codex-loop/settings/host-profile.json]
  PROFILE --> PREFER[Validate account and restore private preferences]
  SAVE[User asks to remember a project] --> EDIT[host-project edits one source locator on controller]
  PREFER --> EDIT
  EDIT -->|Drive-backed| UPDATE[Export and update original Drive file ID + readback]
  EDIT -->|local_only| PRIVATE[Private profile on its own host]
  UPDATE --> PROFILE
  PREFER --> LOOKUP[Current project locator for pinned environment]
  LOOKUP --> CACHE[Selected connector verifies and materializes conversation cache]
  CACHE --> GRANT[Exact path authority + connector boundary]
  GRANT --> ACCESS
  GRANT -. WSL extra project .-> WREG[Owner-only local project allowlist]
  WREG --> WGRANT[Explicit user scope: idle-expiring bearer grant]
  WGRANT --> ACCESS
  WGRANT -. expiry or explicit revoke .-> WKILL[Stop grant commands; retain project files]
  DRIVE -->|Absent or unconnected| DEFAULT[Fresh Web defaults / own native profile]
  DEFAULT --> PREFER
  PROFILE -->|Error or duplicate| PROFILEFAIL[Report recovery failure]
  PREFER --> S{Explicit target / saved default / Web}
  S -->|Web/default| HR[Installed ChatGPT runtime]
  S -->|Local computer| MCP[Explicit connector or ordered custom MCPs then RDC]
  MCP --> OBS[Host-observed file/shell capability + computer identity]
  OBS -. My Mac first admission .-> MG[Private Codex Loop runtime commands including bootstrap/resume; no task ID yet]
  MG --> LR
  L -. after real task ID .-> WG[Register explicitly authorized project and session grant]
  WG --> ACCESS
  MCP -. first-time setup only .-> GUIDE[Local MCP setup tutorial]
  ROUTE --> DISPATCH[route-check verifies intended connector + task permissions]
  DISPATCH --> LR[Same connector: selected computer runtime cache]
  OBS -->|unavailable| Z[Fail closed]
  OBS --> LOC[Snapshot selected environment default/runtime/state locations]
  LOC --> ROUTE[Private conversation route pins connection + locations]
  ROUTE -. directory-dependent work .-> ROOT[Task directory / named project / environment default]
  ROOT -->|missing or denied| Z
  ROOT --> ACCESS[Host verifies task authority + real directory + connector roots]
  ACCESS --> DISPATCH
  HR --> L[bootstrap -> task_id]
  LR --> L
  A -->|known lifecycle| L
  A -->|identity/context lost| RR[resume same lifecycle]
  A -->|runtime unavailable| Z[Fail closed]

  L --> RQ[Retained exact request + steers]
  L --> LS{Lifecycle status}
  LS -->|active| CC[Continuation contract]
  LS -->|paused| PA[Wait for explicit continuation]
  LS -->|blocked| BL[Wait for user/external change]
  LS -->|complete / cancelled| TERM[Terminal: never silently revive]
  PA -->|resume / continue| RR
  BL -->|resume / continue| RR
  RR --> RE[Reactivate resumable lifecycle
retain prior blocker for recheck]
  RE --> CC

  CC -. repo/filesystem work .-> O[One cheap orient]
  O --> GP{Normal Git probe succeeds?}
  GP -->|yes| RI[Root-to-cwd repo instructions]
  GP -->|yes| PW[Pre-existing dirty/protected paths]
  GP -->|no + registered project mapping| GMR[Validate host-local git metadata from Host Profile]
  GMR --> FIX[Repair shared .git pointer once + retry original probe]
  FIX --> RI
  FIX --> PW
  GP -->|no usable mapping| RI
  CC --> DS{Domain Skill owns workflow?}
  DS -->|no| H[Host-native agent loop]
  DS -->|yes| DW[Domain Skill-owned workflow/state]
  DW --> H
  RI --> H
  PW --> H

  H <--> T[Inspect / act / observe / test / repair]
  H -. live task-owned work .-> VW[Verified wait: observe existing handle]
  VW --> H
  H -. multi-step work only .-> P[Optional 3-state plan]
  P -. read-only projection .-> TB[Task board: doing / pending / done]
  H -. large/risky change only .-> Q[One Codex-style review]
  Q -->|finding| H
  Q -->|clean| F[Requirement -> current evidence
semantic acceptance]
  H --> F
  F -->|material work remains| H
  F -->|genuine impasse| BK[block --reason]
  BK --> BL
  F -->|requirements proven| D[One deterministic completion check]
  D -->|machine blocker| H
  D -->|PASS| E[status = complete]

  L -. cheap state-only query .-> N[next]
  N -. no status mutation / no reconciliation .-> LS
  L -. explicit correction .-> ST[Record exact steer]
  ST --> RQ
  L -. long/noisy transition only .-> C[Checkpoint / persistence]
  C -. restores same status + plan .-> LS

  DW -. authoritative semantic stage .-> SE[semantic-work-enter]
  SE --> LI[logical_isolation]
  LI --> SF[semantic-work-finish]
  SF --> SR[semantic_result_id
bound to stage + input + instruction + request + generation]
  SR --> DW

  H -. consequential side effect .-> G[Routing / approvals / external-action reconciliation]
  G --> X[GitHub / Drive / Local / deployment]
  C -. durability/high-risk only .-> HD[Heavy baseline / fingerprints / durable validation / release lineage]
```


## Boundaries

- **Execution preferences are private locators.** `host.json` stores an ordered connection list, default Web/environment target, and per-environment workspace/project/runtime/state locations outside Git and packages. Explicit task choice wins; saved defaults initialize new conversation routes. Custom MCPs precede RDC, manual connection selection never silently falls back, and observed capabilities remain host-owned. Conversation routing pins the selected computer/connection; a running lifecycle cannot move because preferences changed. Profile reads and connection resolution are narrow pre-admission routing. See `references/local-connections.md`; first-time setup uses `references/local-mcp-tutorial.md`.
- **WSL temporary directories stay host-enforced.** The optional adapter has a private local project allowlist, separate from Host Profile locators. After explicit user authorization, the conversation receives a bearer grant reusable across tasks; only commands carrying that capability mount the extra project. Grant-backed execution/polling renews three days of idle validity; optional task labels do not bind authorization. The backend cannot identify the web chat, so the chat must retain its private capability. Protocol reconnection does not clear an unexpired grant, backend restart does. Expiry/revocation stops dependent commands and preserves durable files. Chat identity is not independently authenticated, and grants never enter saved preferences or shared task state. See `integrations/wsl-mcp/README.md`.
- **Lifecycle admission remains mandatory.** Once selected, Codex Loop must create or resume its lifecycle before any substantive task action. This invariant is not optimized away.
- **Exact user authority is canonical.** The initial request plus later steers define what the agent is authorized to do. A model-written task objective or acceptance restatement is not created for the same task.
- **Lifecycle status is explicit but thin.** `active | paused | blocked | complete | cancelled` controls whether work may proceed; it is separate from plan state. `paused` is user-driven, `blocked` requires a concrete impasse, and terminal states never silently resume.
- **The active loop is host-native.** After admission and any required one-time `orient`, ordinary inspection, editing, shell commands, tests, and repairs go directly through host tools. Codex Loop is not a workflow engine and does not sit between normal tool calls.
- **Domain workflows remain domain-owned.** If another selected Skill requires a workflow/state machine, Codex Loop keeps its lifecycle around that workflow but does not flatten or replace the Skill's states/transitions.
- **Authoritative domain semantic work has one execution path.** A coupled domain Skill may declare a stage as authoritative semantic work. That stage must enter `semantic-work-enter`, execute inside `logical_isolation`, and finish through `semantic-work-finish`. Only that path mints a `semantic_result_id`; generic delegation results, caller-authored PASS JSON, hashes, receipts, or domain helper scripts cannot substitute for it.
- **Semantic results are exact and fresh.** Each `semantic_result_id` is bound to consumer, stage, exact semantic input hash, governing instruction hash, effective user-request hash, and Codex Loop generation. `semantic-result` fails closed on a binding mismatch, on workspace mutation or a user steer during the isolation, or after a later mutation/steer makes the result stale.
- **Semantic-result persistence is structurally lossless.** Authoritative semantic JSON is sanitized without list/dict truncation, then checked against the total semantic-result byte limit. Oversized semantic results fail closed instead of silently dropping items; bounded structural scrubbing remains only for non-authoritative diagnostic/runtime state.
- **Logical isolation keeps its existing meaning.** It remains behavioral rather than physical context isolation. The new semantic authority contract does not claim cryptographic proof of cognition; it removes the domain-runtime bypass by making logical isolation the only Codex Loop path that can mint authoritative semantic work.
- **Normal model-facing context is authority-first and low-noise.** It contains the exact request/steers, a short continuation contract, lifecycle status, minimal workspace identity, real machine blockers/live work, and an optional short plan/task-board projection. Hashes, generations, validation history, changed-path inventories, receipts, and diagnostics remain runtime-side unless explicitly pulled or required by a capability.
- **`orient` is cheap.** Repository tasks establish repo identity, current branch/HEAD/status, applicable instructions, and pre-existing dirty paths without a full content fingerprint or repository-wide baseline.
- **Shared-worktree Git repair is bounded and failure-triggered.** A normal Git probe always runs first. Only when it fails, and only when the current path belongs to a Host Profile registered project whose environment defines `git_metadata_root`, Codex Loop validates `<git_metadata_root>/<project-alias>` as Git metadata for that exact worktree, updates its `core.worktree`, replaces the shared `.git` entry with the current-host pointer, preserves a conflicting synced `.git` directory outside the worktree, and retries the original probe once. My Mac/My WSL remain unchanged and repeated same-host Git access takes the normal fast path.
- **Scoped instructions are stable authority.** Load root-to-cwd instructions during orientation and load a deeper scope only before first touching it. Do not rediscover instructions as a heartbeat.
- **`next` is state-only.** It exposes status, plan/task-board state, and known live work without changing `paused`/`blocked`, reconciling the repository, hashing workspace content, rediscovering instructions, or suggesting that the model should finish. Use it only when a cheap lifecycle-state read is useful.
- **`resume` owns real re-entry and user continuation.** Active stays active; paused/blocked are reactivated as a new attempt to advance the same objective, with the prior blocker returned for mandatory re-observation; complete/cancelled cannot resume. After re-entry, re-observe the bound workspace, live work, and applicable instructions. Historical summaries or validation never outrank current reality.
- **Workspace recovery keeps the same lifecycle.** If a stale/legacy binding lacks enough Git identity to prove a move, `source-acquisition-verify --task-id` records stronger exact repository/commit/tree/origin evidence and `orient --rebind-verified` consumes it. Never bootstrap a replacement task or manually rewrite lifecycle state just to escape a workspace mismatch.
- **Plan is optional durable working memory.** Its only states are `pending | in_progress | completed`; the task board is a pure read-only projection of that same plan. Neither is authority or a deterministic completion blocker.
- **Validation is direct by default.** The host runs the smallest relevant test/build/lint check. Durable validation receipts exist only for explicit high-risk/durable workflows such as release/publication/persistence.
- **One semantic acceptance, one machine completion transition.** The model treats completion as unproven, derives material requirements from the request, and verifies them against current evidence. Only then does `completion` check machine-observable blockers; `PASS` transitions `active -> complete` without pretending the runtime certified semantic correctness.
- **Heavy reconciliation is lazy.** Full file baselines, ignored-file watches, workspace fingerprints, generation-based freshness, release lineage, and persistence are activated only when durable reconstruction or high-risk publication actually requires them.
- **Deterministic governance stays at real side-effect boundaries.** Non-idempotent external actions, routing, sandbox/approval, protected user work where durable tracking is active, workspace identity, and task-owned process cleanup remain explicit machine checks.
- **Drive temporary storage has one root.** All ChatGPT-created temporary Drive objects live under `ChatGPT-Temporary`; top-level Skill-named folders are reserved for intentionally retained archive content.
- **The host owns model sampling and normal tool execution.** Codex Loop does not recreate Codex's session runtime, token/budget manager, native multi-agent runtime, Plan Mode, Guardian/approval engine, tool dispatcher, or automatic idle-turn scheduler. No Composer DAG is introduced; the host-native agent loop remains the dynamic execution graph.

Host Profile recovery is independent of task resume. The host Drive connector owns authenticated transport; `host-profile` validates/imports/exports account-bound preference envelopes. Saved changes require provider read-back before claiming cross-chat durability. Fixed folder/file names are constants; private IDs never enter the Skill.

Local lifecycle dispatch has its own `local_lifecycle` route check, including bootstrap and resume. The host supplies the actual owning connector before dispatch; mismatches fail. This validates caller-provided identity, not interception of arbitrary host tool calls. Initialization recovery stays on the selected connector; only explicit user transition can change a pinned transport.

Environment identifiers represent distinct filesystems: Mac and WSL never share a default root merely because they share hardware. Empty current profiles use Web, no connections/locations, follow-user language, standard material progress, cloud browser preference without local fallback, and task persistence off. Missing files use defaults without writes; malformed/unsafe/unreadable/unsupported profiles fail. `route-check` resolves task/default roots from a route snapshot and named projects from the current controller profile and blocks missing directory or path authority; the host observes remote existence, realpath, and connector roots before supplying the grant flag. Runtime validation cannot intercept arbitrary host tools or verify a remote filesystem from Web. Saved project paths are authoritative in the profile; native registry entries are temporary conversation grant lookup under the platform temp directory, never a second editable source. Old persistent registry files are neither read nor deleted. `host-project` edits one project source entry, preserving unrelated preferences; saving a remote locator does not require a native runtime upgrade or replacing its profile. Drive discovery enumerates actual parent children before proving absence, and saves update the existing verified file ID in place.
