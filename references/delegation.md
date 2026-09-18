# Delegation / Logical Isolation

Use this reference when a coding workflow requests a subagent, independent reviewer, delegated researcher/tester/debugger, parallel reviewers, or a second-opinion pass.

## Contract

- Keep model sampling, hidden context, actual tool dispatch, approvals, connectors, sandboxing, parallelism, background execution, and any native subagent capability host-owned.
- Keep delegation lifecycle, persistence, checkpoint linkage, generation reconciliation, result validation, warnings, and read-only local gates in the Codex Loop runtime.
- Treat logical isolation as behavioral separation only. It does not create a fresh model instance, physical context reset, independent inference context, or security boundary.
- Treat prior parent reasoning as untrusted unless explicitly projected. Re-observe repository/tool evidence.
- Treat delegated results as evidence, not truth. Main must integrate and re-evaluate them.
- Keep warnings separate from completion: capability degradation alone never turns PASS into BLOCKED.
- Keep authoritative semantic work distinct from ordinary delegated evidence. A coupled domain workflow may use `logical_isolation` as its semantic authority boundary, but only through the dedicated semantic-work lifecycle below.

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

`isolate-finish` validates and scrubs the structured result, reconciles current workspace generation, records workspace-change/limitation warnings, closes the isolation atomically, and returns a fresh Main working projection. Any generation change naturally stales old validation/criterion evidence under existing rules.

`isolate-abort` closes only the isolation; it does not cancel the parent. Parent cancellation atomically aborts any active isolation before continuing the normal cancellation flow.

### Authoritative semantic work

When a domain Skill requires proof that a semantic stage actually passed through Codex Loop's logical-isolation execution path, use:

```text
semantic-work-enter
  -> logical_isolation semantic judgment
  -> semantic-work-finish
  -> semantic_result_id
  -> semantic-result exact-binding check
```

This is a specialization of the existing logical-isolation lifecycle, not a renamed executor or a second isolation system. `semantic-work-enter` fixes `role=semantic-worker`, `requested_executor=actual_executor=logical_isolation`, and binds the owning consumer, stage, exact semantic input SHA-256, governing instruction SHA-256, current effective user-request hash, and current generation. Generic `isolate-finish` is forbidden for these isolations. Only `semantic-work-finish` can mint the opaque `semantic_result_id`.

`semantic-result` is the consumption boundary. The consumer must present the same consumer/stage/input/instruction identity. The runtime rejects a mismatched binding, a workspace change during isolation, or a result from an older generation or superseded user request. A domain runtime therefore cannot complete an authoritative semantic stage by writing a PASS JSON and submitting it through an ordinary artifact path; it must consume a current Codex Loop semantic result.

The `semantic-worker` logical-isolation worker itself must perform the semantic judgment. Scripts, deterministic loops, templates, copied verdicts, and prefilled PASS payloads may not manufacture the value passed to `semantic-work-finish`. Deterministic helpers may prepare source material or persist the already-produced result. As with all logical isolation, this is behavioral isolation rather than physical model-context proof; the authority guarantee is that the domain workflow has no parallel completion path outside the isolation.

## Context policy

Project only the isolated objective plus explicitly selected files, observed facts, user constraints, and necessary criterion references. Do not project Main hypotheses, preferred solution, root-cause guess, recommended patch, next action, unrequested prior conclusions, checkpoint key findings, or private reasoning. The runtime can test what it actively projects; it cannot claim the underlying model is physically unable to see prior conversation.

The worker contract is: read-only; prior parent reasoning is untrusted unless projected; independently re-observe repository/tool evidence; do not continue the parent task; return structured findings only; never claim physical independence that the host did not provide.

## Result contract

`isolate-finish` reads JSON from stdin. Persist only the bounded fields `summary`, `findings`, `recommended_action`, `files_inspected`, and `limitations`. Findings contain `claim`, evidence strings, and `confidence` (`low|medium|high|unknown`). Reject unsupported transcript/reasoning fields. Persisted text uses existing secret scrubbing. The complete scrubbed result must remain at or below 64 KiB. Authoritative semantic work uses a domain-defined JSON object up to 256 KiB and is accepted only through `semantic-work-finish`.

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

python scripts/codex_loop.py semantic-work-enter --cwd REPO --task-id TASK \
  --objective "perform B2 language review" \
  --consumer epi-prose --stage language-review-b2 \
  --input-sha256 INPUT_SHA256 --instruction-sha256 INSTRUCTION_SHA256

python scripts/codex_loop.py semantic-work-finish --cwd REPO --task-id TASK \
  --isolation-id ISO_ID < domain-result.json

python scripts/codex_loop.py semantic-result --cwd REPO --task-id TASK \
  --semantic-result-id SEM_ID --consumer epi-prose --stage language-review-b2 \
  --input-sha256 INPUT_SHA256 --instruction-sha256 INSTRUCTION_SHA256
```

Use `--request-capability parallel_execution` or `background_execution` when a workflow explicitly prefers those capabilities. A native actual executor must receive explicit host-reported `--actual-capability` values; logical execution uses the fixed truthful capability set.

## Completion and source fidelity

An active isolation adds a normal `CONTINUE` reason. A finished logical isolation may still permit PASS when all ordinary criteria, freshness, validation, review, external-action, process, protected-work, and Git gates pass. Delegation completion never auto-passes a parent criterion.

This is a Codex Loop / Chatbox local delegation extension. Keep upstream `spawn` and `multi_agents` classified `HOST_DELEGATE`; do not describe this implementation as a port of Codex native multi-agent support.
