# Deterministic durable resume

Persistence is recovery evidence, never a second current-truth store. Resume therefore **forks historical state under current reality** rather than restoring an old task database in place.

## Flow

```text
EXPORT -> VALIDATE -> RESUME PLAN -> OBSERVE CURRENT REALITY -> RECONCILE -> REHYDRATE -> RESUMED
```

Commands:

```bash
python3 scripts/codex_loop.py persistence-resume-plan --manifest state-only.json
python3 scripts/codex_loop.py persistence-resume --cwd REPO \
  --manifest state-only.json \
  --observations-json observations.json
```

`resume-plan` returns the facts that the host must re-observe, including workspace presence, expected repository HEAD/tree when known, and unresolved external-action states. The host supplies observations; the runtime does not invent connector/Git facts.

## Freshness reset

Resume creates a **new task/freshness domain**. It preserves the objective, criterion definitions, profile, validation requirement, clean-process requirement, and privacy-safe external-action lineage. It does not restore current proof:

- previous criterion PASS -> new criterion `pending`;
- previous validation -> `HISTORICAL`;
- previous final review -> `HISTORICAL`;
- previous objective audit -> `HISTORICAL`;
- previous capability/permission state -> re-observe.

`resume_lineage` records the source manifest hash, prior task/generation, a new resume epoch, and new task identity. Current workspace facts always win.

## Source divergence

If persisted source commit/tree differs from the current observation, return `SOURCE_DIVERGED`, bind the new task to the current workspace, and keep old source-bound evidence historical. Do not continue old assumptions as if the source were unchanged.

## External actions

A persisted `dispatched` or `outcome_unknown` non-idempotent action is never retried merely because its terminal outcome is missing. `resume-plan` requires a real provider observation. On resume, the runtime reconstructs a hashed lineage identity (`resume-sha256:...`) only for bookkeeping; it never reconstructs the secret/raw external identity.

Current `terminal_success`/`terminal_failure` observations reconcile the old dispatch. Missing or `outcome_unknown` observations remain unresolved and block normal completion. An unresolved historical terminal failure remains a failure unless current evidence resolves it.

Possible resume status values are `RESUMED`, `NEEDS_RECONCILIATION`, `SOURCE_DIVERGED`, `EXTERNAL_ACTION_UNRESOLVED`, or rejection by manifest/observation validation.

## Workspace Cache restore ordering

When a new conversation also restores a Drive Workspace Cache, restore the capsule **before** `persistence-resume` source reconciliation:

```text
validate capsule -> restore fresh Git workspace -> verify exact HEAD/tree + state fingerprint -> bind workspace
  -> create/upload consumed receipt -> attempt exact capsule cleanup
  -> observe current workspace/external reality -> persistence-resume-plan -> persistence-resume
```

A successful workspace restore creates current source reality; it does not make prior state-only PASS/validation/review/audit evidence fresh. If Drive deletion of the consumed capsule fails, keep `WORKSPACE_RESTORED` and record `CACHE_CLEANUP_PENDING`; later bounded cache operations retry cleanup opportunistically. Never re-select a cache ID that has a matching consumption receipt as an automatic restore candidate.
