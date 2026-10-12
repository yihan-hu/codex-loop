# Local Worktree Collaboration

Use only after Codex Loop admission on the **selected, pinned Local computer**. This protocol is not supported in independent ChatGPT Web workspaces. The host must verify the existing current-chat Git read/write grant for both the repository and the exact worktree parent; merely naming a run or reading its SQLite record is not authorization. A fresh chat has no inherited grants.

## What is shared, what is isolated

- A **Run** owns one immutable source baseline and one validated directed acyclic graph (DAG) of planned tasks. Each task declares `key` (stable ID), `pool` (fairness grouping), `depends_on` (predecessor task keys), `title` and `instructions`. `key`, `pool` and `depends_on` are optional only when there is genuinely no need for explicit labels or dependencies; omitted values become `task-N`, `default` and `[]`.
- **Pools do not impose hard concurrency limits.** Each atomic claim considers all currently ready tasks, prioritizes pools with fewer active workers and least-recently served pools, and keeps all available Chats useful. A waiting task does not block another Pool's downstream work. Predecessors must actually be finished and committed; declared cycles, duplicate keys or missing prerequisites are rejected on Run creation.
- Each Chat keeps its existing Codex Loop `task_id` and one private Git worktree, and may execute many successive tasks. At `collab finish`, the runtime marks one task done, preserves its own commit delta and may return `continue_now=true` with the already-claimed `next_task`. **Execute that task immediately in the same Chat and worktree**, with no fresh lifecycle/bootstrap/authorization. A completed task cannot be stolen or restarted by another Chat.
- Dependencies crossing worktrees are materialized through verified Git `cherry-pick -x` of each prerequisite's **own new commits**, ordered by the DAG. The target branch remains untouched until final integration. On an interrupted Git operation, inspect native Git state, resolve safely and retry claim; no blind replay of a partial cherry-pick. Each task records its initial `start_commit` *after* dependency materialization, so final integration takes only `start_commit..commit_sha`, topologically, without reapplying the imported prerequisites.
- Messages/delegation offers and all worker/task ownership live in a SQLite file under the selected local computer's `CODEX_LOOP_HOME`. Do not sync this SQLite file across Mac/WSL or OneDrive. Each worktree and local file path is still independently subject to the current Chat's scoped authorization. A file/SQLite update **cannot awaken** an idle or ended Chat.
- When every task is `done` and every delegation is resolved, the last active worker atomically becomes Integrator. An unavailable/dirty worktree, missing commit, unfinished task or unresolved delegation never counts as completion. The Integrator performs target-branch Git merge/cherry-pick and validation, then owns any prewritten continuous post-integration serial tail on the same `task_id`.

## Planned same-host DAG Run

1. Verify the exact authorized repository, clean target checkout, source commit/tree and one outside-repository worktree parent on the **same pinned host**. Choose `detached` for short-lived contributions and `branches` for separately reviewable long-lived contributions; both strategies use isolated worktrees.
2. Freeze one full-objective `PLAN.md` and one JSON task file before launch. The task file is an array with records such as:

   ```json
   [
     {"key":"article-01","pool":"articles","depends_on":[],"title":"Review article 1","instructions":"Produce a verified training receipt and commit it"},
     {"key":"method-01","pool":"methods","depends_on":[],"title":"Method training","instructions":"Train independently and commit outputs"},
     {"key":"method-02","pool":"methods","depends_on":["method-01"],"title":"Method validation","instructions":"Use method-01's committed outputs and verify"}
   ]
   ```

   These fields are execution data, not prose for the agent to reinterpret; retain precise ownership, gate and output instructions. Unlike old Wave-only pools, dependent tasks **belong in this same Run** if their verified predecessors can be materialized safely. A genuinely exclusive global resource or a prerequisite requiring an independently accepted release baseline can still justify a separate subsequent Run.
3. Create once via `python3 scripts/codex_loop.py collab create --repo REPO --branch TARGET --goal-key GOAL --worktree-parent PARENT --tasks-file TASKS.json [--serial-tail-file PREWRITTEN_TAIL.md] --strategy detached`. The SQLite registry owns all task definitions and pool/edge state afterward. There is no hard task-to-Chat ratio; launch as many active Chats as actually useful and authorized.
4. Each Chat performs its own normal Codex Loop bootstrap and current-chat scoped repository/worktree permission admission; then `collab claim --run-id RUN --task-id TASK --worktree-parent PARENT`. A claim atomically selects a Ready task fairly, reuses the Chat's previous worktree if it has one, materializes predecessor code, and returns the task key/pool/dependencies, worktree and exact source baseline. An idempotent retry of an already-claimed task returns its current assignment.
5. After bounded task work and local verification, commit changes (including small tracked evidence for test-only tasks) and call `collab finish --run-id RUN --task-id TASK --slot SLOT_NUMBER --commit-sha FULL_HEAD`. `--slot` disambiguates retries or successive tasks whose HEAD did not change. The finish response reports an integration election **or** `continue_now=true` plus `next_task`; follow that `next_task` immediately with the **same** task ID/worktree. Do not stop at a label called Wave or ask for another launch prompt. If no next task is ready, this Chat may exit normally; remaining active Chats keep claiming work when dependencies unlock.
6. If elected Integrator, execute `collab integrate --run-id RUN --task-id TASK --integration-worktree TARGET`; it cherry-picks only each task's own commits in dependency order. Resolve Git conflicts without touching unrelated user work. Verify the merged result, then call `collab integration-complete --test-evidence ACTUAL_TESTS`. If `continue_now=true` assigns a registered post-integration tail, execute its entire chain in this Chat and call `collab serial-complete` only after its real gates pass. Neither SQLite nor the registry runs an unattended model or automatically pushes.
7. `collab status --run-id RUN` displays Ready/Waiting/Claimed/Done per Pool, remaining tasks, and the integration/serial owner. `next` and `resume` expose inbox/serial work for current active workers. If a Chat stops during a task, resume **that** task ID and its same owned worktree; never steal claimed work or replay uncertain Git writes.

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
