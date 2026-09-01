# Execution supervision and outcome separation

Codex Loop separates **workload completion** from **process termination**. A test/build can produce an authoritative terminal result while its interpreter, child process, or shutdown hook remains alive. The runtime records those as independent facts rather than rewriting the workload or inventing framework-specific forced-exit wrappers.

## ExecutionObservation

A validation observation contains three independent result axes:

- Workload: `UNKNOWN`, `RUNNING`, `PASSED`, `FAILED`, `CANCELLED`.
- Process: `RUNNING`, `EXITED_CLEAN`, `EXITED_NONZERO`, `TEARDOWN_STALLED`, `TIMED_OUT`, `TERMINATED`, `ORPHANED`, `UNKNOWN`.
- Cleanup: `NOT_REQUIRED`, `SUCCEEDED`, `FAILED`, `ORPHANED`, `UNSUPPORTED`, `UNKNOWN`.

`TEARDOWN_STALLED` is legal only after the workload is already terminal and the owned process remains alive beyond a bounded teardown grace. If workload status is unknown, use `TIMED_OUT`/`UNKNOWN`; do not relabel an ordinary timeout as teardown stall.

## Authoritative workload evidence

Evidence strength is explicit:

- `machine_authoritative`: structured report/manifest/host metadata.
- `framework_authoritative`: result parsed by a registered framework adapter.
- `explicit_protocol`: terminal marker authenticated by a per-execution capture token/nonce.
- `weak_textual`: progress-like text that cannot establish success.
- `none`.

A `PASSED` workload requires authoritative evidence. `100%`, `done`, or similar progress-only output never establishes PASS. Framework summaries such as a pytest/unittest terminal result are authoritative only through a named parser/adapter; the agent must not promote arbitrary text by pattern matching. Explicit protocol evidence must be token-verified at the capture layer so ordinary workload stdout cannot forge it.

## Validation flow

The existing host-visible flow remains:

```text
validate -> host-visible command -> validation-record
```

`validate` now also returns an `execution_policy` describing workload timeout, teardown grace, process-group cleanup intent, and authoritative-only terminal evidence. A rich observation can be recorded without an exit code:

```bash
python3 scripts/codex_loop.py validation-record --cwd REPO \
  --command-json '["pytest","-q"]' \
  --workload-status PASSED \
  --workload-evidence-kind framework_authoritative \
  --workload-evidence '237 passed in 18.41s' \
  --workload-adapter pytest-terminal-summary-v1 \
  --process-status TEARDOWN_STALLED \
  --process-evidence 'parent remained alive after terminal framework result' \
  --cleanup-status SUCCEEDED \
  --cleanup-evidence 'owned process group was terminated after grace period'
```

`--exit-code` remains a compatibility input. Legacy exit 0 infers workload `PASSED` + process `EXITED_CLEAN`; legacy non-zero infers workload `FAILED` + process `EXITED_NONZERO`. That inference is not a universal law for rich observations: an authoritative workload PASS may coexist with a non-clean process outcome.

## Completion semantics

For an ordinary functional objective, `PASSED + TEARDOWN_STALLED + cleanup SUCCEEDED` may satisfy validation while surfacing `PROCESS_TEARDOWN_DEGRADED`. If the task was bootstrapped with `--require-clean-process-exit`, the same process outcome keeps completion open. `cleanup FAILED`, orphaned task-owned execution, or uncertain workload success blocks or prevents PASS as appropriate.

Generic lifecycle pathology belongs in the execution-supervision layer. Do not default to `os._exit`, `--force-exit`, `System.exit`, self-`kill -9`, or equivalent workload rewrites. Such workarounds may hide leaks or skip coverage/artifact flush and are allowed only when the user objective or a faithful domain reproduction explicitly requires them.

Host capability remains authoritative. Where the host cannot expose process groups, descendants, signals, or teardown grace, record partial supervision (`PROCESS_SUPERVISION_PARTIAL`) instead of pretending full lifecycle control.
