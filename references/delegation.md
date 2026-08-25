# Delegation / Logical Isolation

Use this reference when a coding workflow requests a subagent, independent reviewer, delegated researcher/tester/debugger, parallel reviewers, or a second-opinion pass.

## Contract

- Keep model sampling, hidden context, actual tool dispatch, approvals, connectors, sandboxing, parallelism, background execution, and any native subagent capability host-owned.
- Keep delegation lifecycle, persistence, checkpoint linkage, generation reconciliation, result validation, warnings, and read-only local gates in the Codex Loop runtime.
- Treat logical isolation as behavioral separation only. It does not create a fresh model instance, physical context reset, independent inference context, or security boundary.
- Treat prior parent reasoning as untrusted unless explicitly projected. Re-observe repository/tool evidence.
- Treat delegated results as evidence, not truth. Main must integrate and re-evaluate them.
- Keep warnings separate from completion: capability degradation alone never turns PASS into BLOCKED.

## Executor capabilities

`LogicalIsolationExecutor` truthfully reports: behavioral context isolation and bounded context projection are available; fresh/independent/physical model context, parallel/background execution, and independent tool sandbox are unavailable. A future `NativeSubagentExecutor` must use capabilities reported by the host rather than assuming all capabilities are true.

When native execution is requested but logical isolation is used, record `DEGRADED_SUBAGENT_ISOLATION`. If parallel execution is requested but unavailable, serialize and record `SERIALIZED_DELEGATION`. If background execution is requested but unavailable, execute inline and record `INLINE_DELEGATION`. `WORKSPACE_CHANGED_DURING_ISOLATION`, `DELEGATION_RESULT_LIMITED`, and `DELEGATION_ABORTED` describe later lifecycle conditions.

## Lifecycle

Only one isolation may be active per parent task. Nested local isolation is rejected; the host should finish/abort the current pass and then serialize the follow-up. All MVP isolations are read-only.

```text
MAIN --isolate-enter--> ISOLATED_ACTIVE --isolate-finish--> MAIN
  ^                              |
  +--------- isolate-abort ------+
```

`isolate-enter` creates a normal checkpoint, records `parent_generation`, executor capability metadata, the explicit projected context, and warnings. The checkpoint is remembered working state, never restored workspace reality.

`isolate-finish` validates and scrubs the structured result, reconciles current workspace generation, records workspace-change/limitation warnings, closes the isolation atomically, and returns a fresh Main working projection. Any generation change naturally stales old validation/review/criterion evidence under existing rules.

`isolate-abort` closes only the isolation; it does not cancel the parent. Parent cancellation atomically aborts any active isolation before continuing the normal cancellation flow.

## Context policy

Project only the isolated objective plus explicitly selected files, observed facts, user constraints, and necessary criterion references. Do not project Main hypotheses, preferred solution, root-cause guess, recommended patch, next action, unrequested prior conclusions, checkpoint key findings, or private reasoning. The runtime can test what it actively projects; it cannot claim the underlying model is physically unable to see prior conversation.

The worker contract is: read-only; prior parent reasoning is untrusted unless projected; independently re-observe repository/tool evidence; do not continue the parent task; return structured findings only; never claim physical independence that the host did not provide.

## Result contract

`isolate-finish` reads JSON from stdin. Persist only the bounded fields `summary`, `findings`, `recommended_action`, `files_inspected`, and `limitations`. Findings contain `claim`, evidence strings, and `confidence` (`low|medium|high|unknown`). Reject unsupported transcript/reasoning fields. Persisted text uses existing secret scrubbing. The complete scrubbed result must remain at or below 64 KiB.

## CLI

```bash
python scripts/codex_loop.py isolate-enter --cwd REPO --task-id TASK \
  --role reviewer --objective "independently review the implementation" \
  --requested-executor native_subagent --actual-executor logical_isolation \
  --project-file src/example.py --fact "observed failure" --criterion-ref C1

python scripts/codex_loop.py isolate-status --cwd REPO --task-id TASK

python scripts/codex_loop.py isolate-finish --cwd REPO --task-id TASK \
  --isolation-id ISO_ID < result.json

python scripts/codex_loop.py isolate-abort --cwd REPO --task-id TASK \
  --isolation-id ISO_ID --reason "insufficient evidence"
```

Use `--request-capability parallel_execution` or `background_execution` when a workflow explicitly prefers those capabilities. A native actual executor must receive explicit host-reported `--actual-capability` values; logical execution uses the fixed truthful capability set.

## Completion and source fidelity

An active isolation adds a normal `CONTINUE` reason. A finished logical isolation may still permit PASS when all ordinary criteria, freshness, validation, review, external-action, process, protected-work, and Git gates pass. Delegation completion never auto-passes a parent criterion.

This is a Codex Loop / Chatbox local delegation extension. Keep upstream `spawn` and `multi_agents` classified `HOST_DELEGATE`; do not describe this implementation as a port of Codex native multi-agent support.
