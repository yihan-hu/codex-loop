# Lightweight durable resume

Resume restores durable intent, then lets the model re-observe current reality. Do not reconstruct a lifecycle state machine.

## Flow

```text
VALIDATE MANIFEST -> OBSERVE CURRENT REALITY -> RECONCILE -> RESTORE REQUEST/PLAN -> CONTINUE
```

`persistence-resume-plan` requests only facts that can become stale outside the manifest, such as workspace presence, expected Git HEAD/tree, and unresolved consequential external actions. The host supplies those observations.

A v4 resume restores:

- request anchor and ordered steers;
- objective and acceptance text;
- optional three-state plan;
- profile and validation requirement;
- workspace lineage;
- unresolved external-action lineage after real provider reconciliation.

It does **not** restore semantic PASS state. Historical validation remains historical. The resumed model should inspect the repository/tool state, update the plan if needed, then continue from the smallest useful next action.

If current source commit/tree differs from the manifest, report `SOURCE_DIVERGED` and keep the same lifecycle id and reconcile it to current reality. Do not pretend old validation still applies.

For a persisted non-idempotent action in `dispatched` or `outcome_unknown`, observe the provider before any retry. Missing terminal evidence remains unresolved.

## Workspace Cache restore ordering

When a Workspace Cache is also used:

```text
validate capsule
-> restore fresh Git workspace
-> verify exact HEAD/tree/worktree fingerprint
-> bind workspace
-> observe current external reality
-> persistence-resume-plan
-> persistence-resume
```

A successful cache restore establishes current source reality; it does not make historical validation current. Cleanup failure after a verified restore is cleanup residue, not a reason to invalidate the restored workspace.
