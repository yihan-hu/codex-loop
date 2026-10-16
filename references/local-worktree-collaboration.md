# Local Worktree Collaboration

Use only after Codex Loop admission on the **selected, pinned Local computer**. This protocol is not supported in independent ChatGPT Web workspaces. The host must verify the existing current-chat Git read/write grant for both the repository and the exact worktree parent; merely naming a run or reading its SQLite record is not authorization. A fresh chat has no inherited grants.

## What is shared, what is isolated

- A **Run** owns one immutable verified Git source baseline and an initially validated directed acyclic graph (DAG) that may be revised for unclaimed tasks. Each task declares `key` (stable ID), `pool` (fairness grouping), `depends_on` (predecessor task keys), `title` and `instructions`. `key`, `pool` and `depends_on` are optional only when there is genuinely no need for explicit labels or dependencies; omitted values become `task-N`, `default` and `[]`.
- **Pools remain fairness groups, not hard concurrency quotas.** A Run may optionally configure a *shared resource cap* spanning multiple pools (e.g., GPU-backed Qwen and Adapter A tasks). SQLite atomically excludes tasks from all grouped pools when the combined number of claimed Slots reaches the cap. Other Ready work, such as GPT-6 or science QA, remains claimable; existing claims are not interrupted. Capacity returns automatically when a Slot finishes or its expired lease is reclaimed. Runs with no resource cap keep the original uncapped behavior. Each atomic claim prioritizes pools with fewer active workers and least-recently served pools, and keeps all available Chats useful. A waiting task does not block another Pool's downstream work. Predecessors must actually be finished and committed; declared cycles, duplicate keys or missing prerequisites are rejected on Run creation.
- Each Chat keeps its existing Codex Loop `task_id` and one private Git worktree, and may execute many successive tasks. Each **new** Slot claims and materializes its SQLite-owned inputs, then reuses the existing `isolate-enter` / Logical Isolation machinery in the same durable lifecycle (the two databases are not a shared transaction; an entry failure holds the claimed Slot for idempotent retry, not automatic reassignment): the reply contains `logical_isolation.isolation_id`, its bounded context and binding to Run/Slot/lease. For an idempotent claim, return that same isolation; waiting does not create one. `collaboration.instructions_chunks` includes the full normalized task instructions; `review_of` defaults to `reviewer/read_only` unless an explicit task isolation policy overrides it. Read-only Slot completion checks its own actual worktree before and after producing the review. `finish.continue_now` finishes the old scope and immediately creates the new Slot's scope; a retried finish reconstructs the whole next-task context or reports `next_task_blocked` for same-worker recovery; this does not spawn a new Chat or physically clear its conversation. At `collab finish`, the runtime marks one task done, preserves its own commit delta and may return `continue_now=true` with the already-claimed `next_task`. **Execute that task immediately in the same Chat and worktree**, with no fresh lifecycle/bootstrap/authorization. A completed task cannot be stolen or restarted by another Chat; expired uncompleted claims may be reclaimed with a new ownership generation.
- Dependencies crossing worktrees are materialized through verified Git `cherry-pick -x` of each prerequisite's **own new commits**, ordered by the DAG. The target branch remains untouched until final integration. On an interrupted Git operation, inspect native Git state, resolve safely and retry claim; no blind replay of a partial cherry-pick. Each task records its initial `start_commit` *after* dependency materialization, so final integration takes only `start_commit..commit_sha`, topologically, without reapplying the imported prerequisites.
- Messages/delegation offers and all worker/task ownership live in a SQLite file under the selected local computer's `CODEX_LOOP_HOME`. Do not sync this SQLite file across Mac/WSL or OneDrive. Each worktree and local file path is still independently subject to the current Chat's scoped authorization. A file/SQLite update **cannot awaken** an idle or ended Chat.
- When every task is `done` and every delegation is resolved, the last active worker atomically becomes Integrator. An unavailable/dirty worktree, missing commit, unfinished task or unresolved delegation never counts as completion. The Integrator performs target-branch Git merge/cherry-pick and validation, then owns any prewritten continuous post-integration serial tail on the same `task_id`.

## Runtime-learned resource concurrency

Use `collab resource-blocked --run-id RUN --task-id TASK --slot SLOT --lease-generation GEN --resource GPU_KEY --reason "GPU occupied"` **only** when an attempted external resource acquisition was rejected *before* any task side effect, process launch or working-tree change. This verifies a clean Git worktree at the task input HEAD, checks ownership and outstanding delegations, aborts the matching Slot Logical Isolation and atomically requeues the task. The worker immediately calls `collab claim --wait` with its original task_id; the scheduler skips resource-full pools and may assign a different pool.

On an observed failure, the current claimed peers in the resource's pool group become a **temporary learned upper bound**. For resources not yet configured, the first failed pool is registered automatically; for pools sharing one GPU, configure the group once with `resource-cap` (or report the same known resource key). If no peer is running, apply a 60-second retry cooldown to prevent an external GPU owner from causing a hot claim/return loop. When successful tasks finish and release their Slot leases, capacity becomes available again for subsequent claims. Once the resource has no active owners (and any external-owner cooldown has expired), the learned ceiling is discarded and the original configured cap is restored, so later claims can probe increased available capacity. These are local-Run scheduling observations, not durable hardware specifications; do not falsely report generic task errors as capacity failures or abort a running GPU process.

## Planned same-host DAG Run

1. Verify the exact authorized repository, clean target checkout, source commit/tree and one outside-repository worktree parent on the **same pinned host**. Choose `detached` for short-lived contributions and `branches` for separately reviewable long-lived contributions; both strategies use isolated worktrees.
2. Define and hash the **initial** `PLAN.md` and JSON task file before launch. These establish original scope and launch provenance, while subsequent Local dispatch reads the live SQLite task graph. The task file is an array with records such as:

   ```json
   [
     {"key":"article-01","pool":"articles","depends_on":[],"title":"Review article 1","instructions":"Produce a verified training receipt and commit it"},
     {"key":"method-01","pool":"methods","depends_on":[],"title":"Method training","instructions":"Train independently and commit outputs"},
     {"key":"method-02","pool":"methods","depends_on":["method-01"],"title":"Method validation","instructions":"Use method-01's committed outputs and verify"}
   ]
   ```

   Optional `isolation` is an object with `role` (existing isolation roles), `mutation_policy` (`read_only` or `workspace_write`), and for strict semantic authority `semantic_work` ({consumer,stage,input_sha256,instruction_sha256}). With no setting the same Logical Isolation is used as `researcher/workspace_write`; a strictly semantic Slot is `semantic-worker/read_only`. If a domain needs several independent `semantic-work-enter` stages, express them as separate dependent Slots because existing Logical Isolation does not support nesting. `semantic-work-finish` must accept the real domain result before the Slot can finish. Other `read_only` Slots require explicit `isolate-finish`; only writable Slots auto-close after verified Git completion. A Git receipt never fabricates a review or semantic PASS. These fields are execution data, not prose for the agent to reinterpret; retain precise ownership, gate and output instructions. Unlike old Wave-only pools, dependent tasks **belong in this same Run** if their verified predecessors can be materialized safely. A genuinely exclusive global resource or a prerequisite requiring an independently accepted release baseline can still justify a separate subsequent Run.
3. Create once via `python3 scripts/codex_loop.py collab create --repo REPO --branch TARGET --goal-key GOAL --worktree-parent PARENT --tasks-file TASKS.json [--serial-tail-file PREWRITTEN_TAIL.md] --strategy detached`. The SQLite registry owns all task definitions and pool/edge state afterward. There is no hard task-to-Chat ratio; launch as many active Chats as actually useful and authorized.
4. **Optional resource cap before starting GPU-heavy work:** For an existing authorized Run, configure one shared resource across all GPU-consuming pools:
   `python3 scripts/codex_loop.py collab resource-cap --run-id RUN --resource local_mlx_gpu --max-claimed 2 --pool shadow-generation --pool approved-chain-generation --pool approved-chain-full-generation`.
   Use actual pool IDs returned by `collab status`. `resource_caps` in status shows the configured groups and current claimed count. This is a **claim reservation** rather than GPU process monitoring; keep an independent OS flock/semaphore for processes outside the Run. Updating the cap never cancels previously claimed tasks, even if their current count exceeds the new limit.

5. Each Chat performs its own normal Codex Loop bootstrap and current-chat scoped repository/worktree permission admission; then `collab claim --run-id RUN --task-id TASK --worktree-parent PARENT --wait --poll-interval 30 --max-wait-seconds 60`. A claim atomically reclaims expired leases after 600 seconds of unobserved activity, selects only eligible Ready tasks fairly, reuses the Chat's own worktree, materializes verified predecessor code, and returns the task key/pool/dependencies, worktree, exact source baseline and lease generation. An idempotent retry of an already-claimed task returns its current assignment and the **same** Logical Isolation, without resetting its evidence or starting another stage. The projection is a behavioral boundary with explicit context and role; it cannot erase previous conversation turns.
6. After bounded task work and local verification, commit changes (including small tracked evidence for test-only tasks) and call `collab finish --run-id RUN --task-id TASK --slot SLOT_NUMBER --lease-generation GENERATION --commit-sha FULL_HEAD`. `--slot` disambiguates retries or successive tasks whose HEAD did not change. The finish response reports an integration election **or** `continue_now=true` plus `next_task`; follow that `next_task` immediately with the **same** task ID/worktree and the returned **new** `logical_isolation` projection. Do not re-invoke `isolate-enter` manually: the claim already created it. Do not stop at a label called Wave or ask for another launch prompt. If no next task is ready, the same Chat calls the bounded `collab claim --wait` again: `status=waiting` with `retry_wait=true` means repeat, a claimed result starts work, and `status=done` means exit. An idle poll does not reserve a task or refresh its 600-second lease.
7. If elected Integrator, execute `collab integrate --run-id RUN --task-id TASK --integration-worktree TARGET`; it cherry-picks only each task's own commits in dependency order. Resolve Git conflicts without touching unrelated user work. Verify the merged result, then call `collab integration-complete --test-evidence ACTUAL_TESTS`. If `continue_now=true` assigns a registered post-integration tail, execute its entire chain in this Chat and call `collab serial-complete` only after its real gates pass. Neither SQLite nor the registry runs an unattended model or automatically pushes.
8. `collab status --run-id RUN` displays Ready/Waiting/Claimed/Done per Pool, idle waiting-worker heartbeat timestamps, remaining tasks, and the integration/serial owner. `next` and `resume` expose inbox/serial work for current active workers. If a Chat stops, its claimed task becomes reclaimable after 600 seconds without an observed heartbeat. The next eligible claim uses a separate worker-owned worktree and restores the old task's latest verified commits, staged/unstaged tracked edits and nonignored untracked files without modifying the old directory. A checkpoint is optional: `claim.restored_worktree` reports what was transferred. Before restoring, a stable source snapshot and conflict check must pass; otherwise the claim is held for manual reconciliation. Ignored paths are not automatically copied, and the result reports their count and examples for inspection. Internal untracked symlinks are rebuilt relative to the replacement tree, never copied as absolute aliases to the old worker. Waiting uses short foreground process calls; if My Mac returns a PID, observe it with `read_process_output`, or poll the existing My WSL job via `wsl_poll`. No background daemon or automatic Chat wakeup is created. A stale idle heartbeat only means the local waiting command stopped reporting. A resumed old Chat must check its lease generation and must not replay rejected writes.

## Native generators and independent health review

An authorized local Run may reserve generation pools for named code-worker task IDs using `collab pool-operators`. Code workers still enter the ordinary Codex Loop claim, Logical Isolation, Git metadata-handoff and finish path. An operator may retire a prior worker with `collab stop-worker`; its active Slot and external model process remain intact until safe reconciliation, but new claims are blocked.

`collab recurring-review` registers a read-only health-review Slot which enters the Ready Queue only when a ChatGPT worker next claims after its 20-minute due time. At most one review remains outstanding. It does not awaken a stopped Chat. A local launchd supervisor is independent and checks both model process PIDs every 10 minutes, restarting missing code workers without overwriting completed results; scientific QA remains a separate human-model judgment.

## Local mutable DAG, review tags and activity leases

For Local planned Runs only, workers may atomically publish one task or a JSON array of an entire new Pool (including internal dependencies), and modify *available* tasks during execution. Only the initial PLAN/task file is hashed for launch; the mutable task state is the host-local SQLite registry. Read `collab status` for its current `graph_revision` and avoid applying old PLAN content over newer task instructions. Claimed/Done tasks remain immutable; create follow-up tasks instead of editing them.

```bash
# Inside the already admitted, authorized Local worker. Files contain JSON.
python3 scripts/codex_loop.py collab publish --run-id RUN --task-id TASK   --lease-generation GENERATION --task-file new-task-or-task-array.json
python3 scripts/codex_loop.py collab revise --run-id RUN --task-id TASK   --lease-generation GENERATION --task-key later-task   --expected-revision CURRENT_REVISION --updates-file changes.json
```

The new task JSON uses `key`, `pool`, `depends_on`, `title`, `instructions`, plus optional `exclude_workers`, `review_of` and `isolation`. Dynamic publication and revision preserve the same isolation configuration until a task is claimed. For an independent review, `review_of` names the producing task key(s): this adds the required task dependencies and excludes the actual producers automatically, even if the author is not known when the review task was planned. `exclude_workers` accepts stable registered names such as `Repo-worker3`, ordinal aliases such as `worker3`, or exact task IDs. All filtering happens before atomic assignment.

A claimed Local task has an observed activity lease of **600 seconds**, renewed by `claim`, `publish`, `revise`, `checkpoint` and explicit `heartbeat`. Updated My Mac/WSL connector bridges call `collab activity --task-id TASK --interval-seconds 60` before each scoped project tool invocation: unread messages/control are checked every time, but the active lease is written only after at least 60 seconds. Older connectors, model thinking, and uninstrumented subprocesses still need explicit heartbeats. Each worker must call:

```bash
python3 scripts/codex_loop.py collab heartbeat --run-id RUN --task-id TASK   --lease-generation GENERATION
```

after meaningful tool activity and at safe intervals during a long-running operation. Heartbeat is evidence of activity, not proof that all work is complete. If no activity was recorded for 600 seconds, the *next* `collab claim` atomically reclaims the old owner; no daemon or paused-Chat wakeup runs. A coordinator with the exact same-host authorization may reclaim a named stuck task sooner:

```bash
python3 scripts/codex_loop.py collab reclaim --run-id RUN   --task-key task-A --force --reason 'Original Chat unavailable'
```

An automatically reclaimed task gets a **new lease generation**. Old `heartbeat`, `publish`, and `checkpoint` calls are rejected. A late `finish` carrying its original Slot and generation may register a verified clean result: before the successor has finished, the original commit can be accepted atomically and the successor receives an addressed `stop_task` notice; after a result was accepted, preserve the late commit under a separate Git ref without overwriting it. Worker worktrees are keyed by worker identity, not slot identity; the old worktree is never erased or reused. `claim.recovery` reports the previous owner, worktree, and any saved checkpoint. Committed intermediate results may be recorded with `collab checkpoint --run-id RUN --task-id TASK --lease-generation GENERATION --commit-sha SHA --note DESCRIPTION`. A new worker must inspect and verify source and any uncertain external effects before reusing them; staged and unstaged tracked edits plus nonignored untracked files are automatically transferred using a stable snapshot. Ambiguous external effects and conflict states are not automatically replayed.

If an *Integrator* or post-integration serial owner becomes stale, transfer only after verifying the target branch and clean working tree; an interrupted integration is **never** restarted blindly:

```bash
python3 scripts/codex_loop.py collab reclaim-integrator --run-id RUN   --task-id NEW_INTEGRATOR --integration-worktree TARGET_BRANCH_CHECKOUT
```

For a deliberate early transfer, append `--force --reason DESCRIPTION`. The new owner receives a new integrator generation. For pre-existing merge attempts, review Git state and use `integration-resolved` or `integration-complete` only after required commit proof and tests. Web coordination remains unchanged.

## Unplanned collaboration

For an independently started local task, after verifying the actual repository/worktree and goals, run `collab discover --repo REPO --branch TARGET`; decide whether an existing run is semantically compatible rather than merging unrelated projects. To join or create an **unplanned** cohort:

```bash
python3 scripts/codex_loop.py collab join --repo REPO --branch TARGET \
  --goal-key SPECIFIC_SHARED_GOAL --worktree-parent AUTHORIZED_PARENT \
  --task-id CURRENT_TASK_ID --title 'specific task' --instructions 'full task requirements' \
  --existing-worktree EXACT_OWN_WORKTREE
```

Omit `--existing-worktree` only when the caller has verified authority to create a new worktree under the authorized parent. An existing task always resumes its recorded slot, including if the run closed while it was paused. When registering a new task after integration starts, a fresh unplanned cohort is created under the same goal key.

## Subtask delegation between Worktrees

No coordinator process is required. **A Chat that already owns a claimed, worktree-bound Slot** may offer a bounded, separately tracked task to another active participant or to the unassigned pool. Both Chats must remain in the same run and their own previously authorized paths. An SQLite entry is **not** permission to edit another worker's checkout and it never wakes a stopped Chat.

```bash
# Worker A offers to B (or omit --to-task for a future worker to claim).
python3 scripts/codex_loop.py collab delegate --run-id RUN --task-id A \
  --request-key stable-task-key --title 'Update training API' \
  --instructions 'Change only the authorized training worktree and verify contract' --to-task B
# B reads the next/resume context or the explicit inbox, then accepts/rejects.
python3 scripts/codex_loop.py collab inbox --run-id RUN --task-id B
python3 scripts/codex_loop.py collab delegation-accept --run-id RUN --task-id B --delegation-id ID
python3 scripts/codex_loop.py collab delegation-complete --run-id RUN --task-id B \
  --delegation-id ID --result 'Implemented and tested' --commit-sha FULL_COMMIT
# Alternative: reject (with reason); A must reoffer or explicitly cancel.
python3 scripts/codex_loop.py collab delegation-reject --run-id RUN --task-id B \
  --delegation-id ID --reason 'Cannot own this interface'
python3 scripts/codex_loop.py collab delegation-reoffer --run-id RUN --task-id A \
  --delegation-id ID --to-task OTHER_ACTIVE_WORKER
python3 scripts/codex_loop.py collab delegation-cancel --run-id RUN --task-id A \
  --delegation-id ID --reason 'No longer required'
```

`--request-key` is a stable idempotency key: retrying the same offer after an ambiguous tool outcome returns the same delegation instead of creating duplicate work. Once accepted, the recipient owns the subtask. Completing it returns a result and optional **verified reachable commit SHA**. For code changes, commit the result and supply the SHA; the worker's own final `collab finish` must still include all work. The recipient cannot finish their Slot while an assigned delegation is incomplete. A sender's own lifecycle cannot complete while its delegated work is still open, accepted or rejected, but the sender can continue other useful work and its Slot can be finished. Rejected work does not silently disappear: the sender reoffers it or explicitly cancels it with a reason. This prevents an apparent last-finisher from integrating an incomplete run.

For a pool offer, an already-running worker can explicitly accept it. On a planned run **after all original slots are claimed**, a fresh Chat using the same authorized run launcher can `collab claim` an unassigned pool offer: the registry atomically creates one additional worker Slot and marks the offer accepted. No process or new Chat is spawned by SQLite; the user still starts any required Chat. No auto-claim occurs solely because someone reads their inbox. A rejected accepted subtask must not leave undocumented, unreviewed partial code in its worker's final commit; preserve and review any partial changes instead of discarding them.

Delegation offers, assignments, results and rejection reasons appear in `collab status` and the relevant `next`/`resume` inbox context. They are separate from ordinary messages: reading/acknowledging a message does not accept a delegation. An elected Integrator does not begin until every delegation is completed or explicitly cancelled and every registered Slot is `done`. A sender cancelling the final rejected offer after all workers finished can become the elected Integrator in the same transaction. No automatic Git push is authorized.

## Safety and recovery

- The local runtime stores durable coordination **outside** project Git, and it is not the Host Profile, authorization store, or a second orchestration server.
- SQLite transactions handle competing claims and election; Git remains the source of truth for file contents, branch HEAD and commits. Check the exact real Git state before retrying writes.
- Target checkout may advance during worker development. The Integrator requires a clean target checkout whose current HEAD descends from the run base; it must test the merged result, not assume each worker test proves integration.
- `collab integrate` persists an attempt marker **before** Git mutation. After any ambiguous interruption, reconcile native Git state and recover the original integrator; do not reissue the same cherry-pick blindly.
- Never force-checkout the same branch in multiple Git worktrees, use `--force` to override checkout, erase uncommitted work, auto-skip a blocked slot, auto-clean unmerged refs, or sync SQLite across Mac/WSL via OneDrive.
