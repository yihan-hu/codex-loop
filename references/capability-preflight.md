# Capability and permission preflight

Use one bounded permission-smoke stage when the reviewed workflow depends on external integrations, host permissions, or local interaction capabilities.

The purpose is to make predictable permission prompts happen **before** substantive execution, instead of discovering them at push/deploy/cleanup time. Preflight does not weaken host security, grant itself permissions, or replace a later host-required per-action approval.

## Mandatory sequencing

Distinguish **task review** from the final code/change review. Task review means the objective, route, intended downstream external actions, and reasonably required capabilities have been understood well enough to execute. It happens near the beginning of the objective. Final change review still happens near completion.

For a multi-step task with predictable external capabilities, use this order:

```text
understand/review task and intended workflow
  -> resolve deterministic routing
  -> plan required permission probes
  -> execute live host permission smoke tests
  -> satisfy any permission/setup prompts
  -> substantive observe/act/validate work
  -> final change review
  -> completion audit
```

After task review and route resolution, call:

```bash
python3 scripts/codex_loop.py permission-preflight-plan \
  --session-id ROUTING_SESSION \
  --capability github_push \
  --capability github_actions \
  --capability google_drive_write
```

Use only capabilities actually implied by the reviewed workflow. A Drive-only task may omit `--session-id` when no routing-sensitive repository/browser/deployment action exists.

The plan is advisory host-execution structure, not permission state. It intentionally writes no runtime permission record. Its returned phase is `post_task_review_pre_execution`.

## Real-probe contract

A preflight is **not complete** merely because a connector appears connected, a tool schema exists, a capability boolean is true, or a previous turn succeeded. For every required capability, perform at least one current live host operation that reaches the relevant permission boundary.

A valid probe must be:

- **live**: dispatched through the actual host/connector/native tool that the workflow will depend on;
- **bounded**: no unrelated user data, source mutation, branch movement, issue/comment creation, or broad filesystem traversal just to test access;
- **representative**: exercise the same access class needed later (read versus write, repository versus Actions, Drive read versus Drive write);
- **observable**: retain concise evidence of success/failure in current task context;
- **cleaned up** when it intentionally creates a temporary owned sentinel.

Tool discovery, connector listing, or reading these instructions never counts as the probe itself.

## Standard probes

### GitHub push

For **Local mode**, prefer native Git from the canonical authorized worktree:

```text
git push --dry-run <intended-remote> <intended-refspec>
```

Run it through the normal host-visible Git path. Success must show that the remote was reached and the dry run was push-capable without moving a ref. Do not create a throwaway branch merely to test permission.

For **Web mode**, do not stop at a repository permission readback: it can prove the account/app has push-capable repository access, but it may never cross the host's write-approval boundary. Use two bounded observations on the exact target repository:

```text
live repository permission readback -> require push-capable access
  -> host GitHub Git-database create-blob/write-object with fixed empty content
  -> do not attach that blob to any tree, commit, tag, branch, or ref
```

The empty blob is a write-scoped sentinel object, not repository source. It must remain unreferenced, so the probe cannot move a ref or change a checked-out tree. Use only fixed empty/non-sensitive probe content; never put task or repository bytes into the object. Never create a commit, branch, issue, PR, or comment just to smoke-test push permission. If the host exposes no isolated unreferenced Git-object write primitive, classify the early write approval as `GITHUB_PUSH_SAFE_PROBE_UNAVAILABLE` rather than substituting a source/ref mutation.

Repository push capability does not prove GitHub Actions write capability; probe Actions separately when the workflow depends on it.

### GitHub Actions

Exercise an **Actions write-scoped** host operation only against a workflow/job already audited to be source-read-only and ref-nonmutating. Dispatching or rerunning such a job is an acceptable bounded side effect because it creates only a workflow run.

For the Codex Loop repository, `Workspace Download` is an acceptable permission probe because it has `contents: read` and only packages the current source. `Workspace Import` is **not** a permission probe because it has `contents: write` and can publish source changes.
Record the resulting `github_actions` observation at repository scope (`actions:OWNER/REPO`), not at workflow-name scope. The safe `Workspace Download` job is the probe mechanism; the observed Actions write capability is repository-scoped, so later publication must not miss the observation merely because the production workflow is `Workspace Import`.

If the host exposes no safe Actions write-scope operation and no audited no-source-write workflow exists, classify the capability as `GITHUB_ACTIONS_PERMISSION_NOT_PROVEN` before substantive work. Do not invent a source mutation to force an approval prompt.

### Google Drive read

Run a live list/search/metadata operation in the exact Drive scope needed by the workflow. Avoid opening unrelated user files. Successful connector discovery alone is insufficient; the intended scope must actually be readable.

### Google Drive write

When later workflow steps require Drive creation/upload/delete capability, use one uniquely named non-sensitive sentinel owned by this preflight:

```text
create sentinel
  -> read back exact ID/metadata
  -> delete that exact sentinel immediately
```

Never overwrite, rename, move, or delete a pre-existing user file as a permission probe. The sentinel may contain only fixed non-sensitive text such as `codex-loop permission smoke`; do not put repository source, credentials, or task content in it. If cleanup fails, surface the exact sentinel identity and resolve cleanup before creating another probe object.

## Procedure

A successful live probe may be recorded with `permission-observation-record` as an exact-scope, expiring, route-generation-bound hint. On later same-session continuations, `permission-preflight-plan --reuse-fresh-observations --observation-scope CAPABILITY=SCOPE` may skip only fresh exact-scope probes. This never grants permission or bypasses host approval.
For a terminal `codex-loop` self-update in ChatGPT Web, pass the active routing session into `skill-deploy-handoff`. If the next user turn is in the same conversation, `skill-deploy-resume --same-conversation-observed` returns that exact session so these observations remain eligible for reuse. Do not create a new routing session solely because the install handoff crossed a turn; a new routing session is appropriate only for a genuinely new conversation or an intentionally reset route.

1. Complete task review: understand the objective, route, intended external actions, and reasonably required capabilities. Do not confuse this with the final diff/change review.
2. Initialize/read the conversation routing session when routing-sensitive work is involved. Resolve `workspace_mode`, `interaction_target`, and, for install/deploy work, `deployment_target`; run the applicable `route-check`. Capability probing must never create or mutate routing state.
3. Run `permission-preflight-plan` for the capability set implied by the reviewed workflow.
4. Execute every returned probe through the real host path. Prefer independent read-only probes in parallel when safe; serialize probe actions that create temporary objects or workflow runs.
5. If a probe triggers connection/permission UI, satisfy that host flow before substantive work. Batch missing connection/setup requests when the host supports it, and re-run only the failed probe after the host reports that access changed.
6. Keep concise successful observations in current task/session context so the same live capability is not needlessly re-probed.
7. Re-run a probe only if the workflow expands to a new capability, the selected route changes, the connector/native session becomes unavailable, or current evidence is otherwise stale.

For `local_chrome` or `local_mac_gui`, checking that a transport is connected is not permission to interact with the user's computer; do not inspect tabs/windows or take GUI/browser actions before explicit current-task computer-use authorization. RDC connectivity, a local checkout, or a local Skill directory is capability/host evidence only and must never select `workspace_mode=local` or `deployment_target=local_codex_skill`. For native GUI flows, independently verify GUI results after the permitted interaction rather than treating a click/keystroke dispatch as success.

For `local_chrome`, keep `browser_host_health` separate from `browser_session_health`. If the extension/native host is healthy but the current conversation has no Browser executor, classify `SESSION_BROWSER_CAPABILITY_MISSING` and stop Browser execution at that boundary rather than repairing Chrome again or switching to RDC/AppleScript.

## Common capability sets

- Web repository edit only: routing session resolves `workspace_mode=web`; current writable Web workspace; no GitHub/Drive probe unless the reviewed workflow includes publication or another external action.
- Web-mode GitHub publication: `github_push` + `github_actions` + `google_drive_write`, because the verified Web publication path depends on GitHub repository access, an Actions write-scoped operation, and Drive staging create/delete access.
- ChatGPT Web Skill install/update without source publication: native Skill surface capability only; do not probe Drive/GitHub merely because they are connected.
- Local native-Git publication: `github_push`; use native `git push --dry-run` from the canonical authorized worktree before substantial work when publication is already part of the reviewed objective.
- Optional cross-conversation persistence: `google_drive_read` and/or `google_drive_write` only when persistence is enabled or recoverability is an acceptance requirement. Persistence is off by default.
- Local repository read/inspection: RDC access plus resolved/authorized `LOCAL_ROOT`; this does not authorize source mutation.
- Local repository edit: the Local read capabilities plus explicit current-task local-source-mutation authorization.
- `local_chrome`: explicit current-task computer-use authorization plus local Chrome host health and a supported Browser/Chrome executor attached to the conversation.
- `local_mac_gui`: explicit current-task computer-use authorization, RDC, Accessibility, and any Screen Recording permission genuinely needed by the chosen observation transport.

Request the capabilities needed by the reviewed task, not every integration the host happens to offer.

## What may persist

Persist only non-sensitive host preferences/defaults that the user explicitly wants to reuse, such as the preferred local workspace or progress-visibility settings in the private Host Profile.

Do not persist OAuth tokens, Git credentials, browser cookies, passwords, connector secrets, approval tokens, or a claim that a permission is permanently granted. Connector/RDC/browser permission state remains host-owned.

Within the current task/session, a successful live probe may be reused while the corresponding host capability remains demonstrably live. This is an execution optimization, not a grant and not cross-conversation state.

## Host approval boundary

A preflight can deliberately surface setup/permission prompts earlier and can use persistent permissions that the host itself supports. It cannot bypass host-enforced per-action confirmation, sandbox policy, branch protection, repository rules, or high-impact-action review.

A later sensitive action may still require a fresh approval even after its smoke probe passed. Describe the preflight as **early permission discovery**, never as full automation or permanent authorization.

## Failure behavior

If a required probe fails, report the concrete capability before unrelated source mutation when practical and let the user satisfy the host permission/setup flow. Preserve the authoritative routing state and workspace; do not silently change `workspace_mode`, `interaction_target`, `deployment_target`, publication transport, or trust boundary just to avoid the blocker.

If no safe representative probe exists, report `*_PERMISSION_NOT_PROVEN` or `*_SAFE_PROBE_UNAVAILABLE` rather than fabricating success. Missing probe capability is not evidence for a route transition and never authorizes a riskier test mutation.
