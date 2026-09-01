# Execution Outcome Separation and Supervision

Codex Loop treats workload completion and process termination as independent execution facts.

## Invariants

- `Workload Outcome != Process Outcome`; absence of an exit code does not erase an authoritative workload result.
- Progress-only text such as `100%` is weak evidence and must never establish success.
- `TEARDOWN_STALLED` is valid only after the workload is already terminal and the owned process/process-group remains alive beyond a bounded teardown grace interval.
- Generic lifecycle pathology belongs in execution supervision. Do not invent task-specific forced-exit wrappers such as `os._exit`, Jest `--forceExit`, or equivalent merely to make validation return.
- Cleanup is a separate fact: `not_required`, `succeeded`, `failed`, `orphaned`, `unsupported`, or `unknown`.

## Outcomes

Workload: `unknown`, `running`, `passed`, `failed`, `cancelled`.

Process: `running`, `exited_clean`, `exited_nonzero`, `teardown_stalled`, `timed_out`, `terminated`, `orphaned`, `unknown`.

Evidence kinds: `machine_authoritative`, `framework_authoritative`, `explicit_protocol`, `weak_textual`, `none`. `passed`/`failed` requires an authoritative kind and explicit workload evidence. Framework summaries count only when a registered parser/adapter owns that interpretation; agents must not promote arbitrary stdout strings themselves.

## Validation recording

`validation-record` retains legacy `--exit-code` behavior, but richer host adapters may independently provide `--workload-status`, `--process-status`, `--cleanup-status`, `--evidence-kind`, and their evidence fields. A valid state such as `passed + teardown_stalled + succeeded` can satisfy a source-correctness criterion while retaining a process degradation warning. If the objective itself requires clean shutdown, teardown degradation remains contradictory evidence and completion must continue.

The runtime's existing task-owned POSIX process-group termination remains the cleanup primitive. Higher-level lifecycle code consumes `ExecutionObservation`; it does not duplicate signal/process ownership logic.
