# Local Worktree Collaboration

Use only after Codex Loop admission on the **selected, pinned Local computer**. This protocol is not supported in independent ChatGPT Web workspaces. The host must verify the existing current-chat Git read/write grant for both the repository and the exact worktree parent; merely naming a run or reading its SQLite record is not authorization. A fresh chat has no inherited grants.

## What is shared, what is isolated

- Every Chat has its own durable Codex Loop `task_id` and **one Git worktree**. No worker checks out the target branch in parallel. Each run stores one target branch and exact base commit, plus independent worker HEADs/commits.
- All tasks on the **same local computer and same `CODEX_LOOP_HOME`** share `local-collaboration.sqlite3` (SQLite transactions, private permissions). Do not put that SQLite database in OneDrive or another synchronized/network folder. Mac and WSL are different hosts even when they see the same source files.
- An orchestrated run has N predefined, immutable task slots; **one identical user-visible launcher** can be pasted into N new Chats. Registration order determines the slot, not copy/paste order. Unclaimed slots prevent integration.
- An unplanned Chat may discover compatible open runs with `collab discover`, and intentionally join/create an unplanned cohort with one exact semantic `goal_key`. **Same repository/target branch alone does not imply a shared objective.** An already closed cohort cannot accept new participants. Unplanned runs elect after the current registered cohort finishes; a genuinely later new task creates a new cohort.
- Messages reside in the same SQLite file. Codex Loop exposes unread messages in `next` and `resume` without marking them read; use `collab inbox --ack ID` after consumption. A file cannot wake an idle or closed ChatGPT conversation. A participant must resume for unread messages to be acted upon.
- Last finisher is elected atomically only when every registered slot is `done` and every delegation is completed or explicitly cancelled. A crash, dirty checkout, missing task, unlaunched planned slot, or Git conflict never counts as completion. If the integrator is interrupted, its **same Codex Loop lifecycle** resumes the existing integration; never replay an ambiguous cherry-pick.

## Planned same-host run

1. With exact repository and target-branch authority, inspect `git show -s --format=%H HEAD` / `git show -s --format=%T HEAD` and verify the base plus all needed common foundational work first. Choose `detached` for short-lived workers or `branches` for long-lived independently reviewable work. Worktrees and branches are different concepts; both strategies use separate worktrees.
2. Author a bounded local JSON file (array of `{"title":"...", "instructions":"..."}` entries) via the **selected local connector**, containing all worker-specific context and executable acceptance criteria. Keep the file temporary. Choose a worktree parent **outside** the existing target checkout, within the explicit authorized path scope.
3. Run `python3 scripts/codex_loop.py collab create --repo REPO --branch TARGET --goal-key GOAL --worktree-parent WORKTREE_PARENT --tasks-file TASKS.json [--serial-tail-file PREWRITTEN_SERIAL_TAIL.md] --strategy detached` (or `branches`) through the local Codex Loop runtime. Attach one serial-tail file only when the already frozen objective plan calls for consecutive serial work after this Run; it points to those complete stages/gates without creating separate Slots or a second authority. Verify returned `run_id`, slot count, base commit and parent. Then remove only the temporary input file. The SQLite row owns task definitions thereafter.
4. Return one **identical** launch instruction for every new Chat, including the exact same `run_id`, selected `My Mac`/`My WSL` connector, named project root, worktree parent, target integration checkout, and the scope of **this chat's** local mutations/process/test/Git commit rights. Do not authorize GitHub push unless the user requested publication.
5. Each new Chat uses its normal Codex Loop admission/bootstrap first, then `collab claim --run-id RUN --task-id ITS_TASK_ID --worktree-parent AUTHORIZED_PARENT`. The claim is atomic and idempotent for that task ID; it creates (or verifies and reuses) a dedicated worker worktree. It returns the exact slot instructions, worktree path and base SHA. Bind/orient that one worktree as usual before editing.
6. Before modifying shared interfaces, and at task re-entry/finish, read the local inbox and communicate meaningful changes via `collab message --run-id RUN --task-id TASK --body TEXT [--to-task OTHER_TASK]`. Do not assume messages trigger remote Chat turns.
7. Worker validates, commits its intended changes, and calls `collab finish --run-id RUN --task-id TASK --commit-sha FULL_HEAD`. It refuses dirty/untracked work, unverified ancestry or a changed SHA; a durable `refs/codex-loop/collab/RUN/slot-N` protects detached work from garbage collection.
8. If `integrate_now` is false, that worker finishes its own lifecycle and waits for no other Chat. If true, it is Integrator and **must keep working in that chat**: `collab integrate --run-id RUN --task-id TASK --integration-worktree AUTHORIZED_TARGET_CHECKOUT`. The target checkout must have the exact target branch checked out and be clean; worker commits are cherry-picked in slot order. A conflict returns an interrupted state, not success. The host agent must inspect and resolve the Git state without overwriting user work; after manual resolution use `collab integration-resolved --resolution-evidence TEXT`. Run actual tests/review, then `collab integration-complete --test-evidence TEXT`, which checks candidate HEAD and clean checkout. The elected Integrator cannot complete its own Codex Loop lifecycle until the run reaches `integrated` **and any owned serial tail is complete**. If `integration-complete` returns `continue_now=true`, it atomically owns the whole prewritten tail under its existing task ID; immediately execute it in the same Chat and integration checkout, with the separate plan-defined gates intact. No pause/relaunch, new Slot, new task_id, or background scheduler is involved. Upon passing those gates and committing to a clean target branch, call `collab serial-complete --run-id RUN --task-id TASK --integration-worktree AUTHORIZED_TARGET_CHECKOUT --evidence 'actual gates/tests and receipts'`. It verifies same repo/branch/clean state and merged-commit ancestry, records final HEAD, and unblocks lifecycle completion. Do not call it on a failed or held gate. `collab status` and `next`/`resume` expose the unfinished serial chain and exclusive owner after interruption.
9. Both the automatic merge and post-integration serial continuation operate only while the elected Chat is active. It cannot start a new chat, call tools in another chat, publish to GitHub without authorization, or clean up worktrees/refs speculatively. Retain local collaboration state for resume and review.

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
