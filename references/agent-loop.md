# Agent Loop Reference

Treat a coding turn as a state machine:

`ORIENT -> OBSERVE -> ACT -> OBSERVE -> VERIFY -> REVIEW -> GATE -> DONE`

Allow transitions back whenever evidence changes. A tool call is never a completion state; its output becomes evidence for the next iteration.

## Orient

Establish the requested outcome, repository root, local instructions, protected existing changes, acceptance criteria, and likely validation path. Bootstrap runtime state once; the task is bound to that canonical working tree and shared Git repository identity. Use `next` as the bounded working-set projection and `snapshot` only when full debug/audit state is needed. For concurrent work on one repository, use separate Git worktrees/branches instead of copied source directories.

## Observe

Prefer high-information evidence: exact failures, implementation around the failure, call sites, configuration, repository-native test commands, current diff, and evidence references surfaced by `next`. Drill down from the bounded summary instead of repeatedly loading the complete runtime state. Avoid exhaustive architecture discovery before taking a useful action.

## Act

Choose the smallest coherent mutation or command. Preserve unrelated work. Use guarded writes when a known preimage matters. Use host-specialized tools when they materially outperform local execution, then record/reconcile their effects.

## Delegate when requested

When the workflow asks for a second-opinion worker, enter a bounded read-only isolated task. Prefer native host delegation only when it is actually available; otherwise continue with logical isolation and record the degradation warning. Do not project Main hypotheses by default. The worker independently re-observes evidence and returns structured findings. Finish/abort the isolation before resuming Main; current workspace reality overrides the entry checkpoint. Nested local isolation is flattened/serialized by orchestration rather than treated as a parent-task blocker.

## Observe again

Inspect workload evidence, process/cleanup state, exit status when present, stderr/output, changed files, and external results. Workload completion and process termination are independent facts. Do not infer success from a syntactically valid command or from progress-only output such as `100%`; read `execution-supervision.md` when terminal workload evidence appears before process exit.

## Verify

Run the smallest validation that demonstrates the requested behavior from the intended cwd. The agent-facing validation flow records exact command identity and an `ExecutionObservation` when the host can distinguish workload, process, and cleanup outcomes; ordinary exit-code-only results remain compatibility observations. Generic teardown/lifecycle pathology is handled by execution supervision rather than an agent-invented forced-exit wrapper. Validation identity still includes exact argv plus cwd and is attached to a mutation generation; any later mutation invalidates its freshness. Acceptance-criterion and steer evidence is also generation-bound and must be re-evaluated after mutation.

## Resume after persistence

When recovering across conversations, do not manually reconstruct an old task as current truth. Run `persistence-resume-plan`, observe the required current facts, then `persistence-resume`. Treat old criterion PASS/validation/review/audit as historical; current source and external-action reality always wins. Never retry a persisted dispatched/outcome-unknown non-idempotent action before reconciliation.

## Review

Inspect the final change set for accidental edits, stale comments, debug code, incomplete TODOs, generated churn, and mismatch with repository conventions. Mark review freshness only after this inspection.

## Release and publish when requested

Commit the intended source in the same canonical working tree before packaging. Build release artifacts from the planned Git HEAD into disposable staging, record the commit/tree-bound artifact receipt, and never continue development from the staging directory or artifact. Before any repository publication transport, observe the exact remote head/tree and call the current workspace's stable `publish-enter --controller-abi 1` entrypoint. Read the returned `workspace_protocol_reference` from that same current workspace before transport; the route-aware router and current-workspace reference are authoritative over generic loop text or transport guidance bundled in an older installed Skill. Execute only the returned `next_action` / modeled planner actions and never infer another transport from Git terminology, connector availability, GitHub object presence, or remembered older behavior. Web publication and Local native Git remain distinct workspace-owned protocols behind that router. A compatibility failure such as a missing router or `PUBLICATION_ROUTER_ABI_UNSUPPORTED` is a real blocker, not an invitation to search for another primitive. Read `publication-router.md`.

## Gate

Supply acceptance evidence, then run `completion`. Continue on `CONTINUE`; report a real blocker on `BLOCKED`; finish only on `PASS`.
