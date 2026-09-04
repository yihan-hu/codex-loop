# Stable publication router ABI

Repository publication is a self-hosting boundary: the installed/controller Skill can be older than the repository workspace it is currently modifying. The controller therefore must not encode the current publication transport. It knows only one stable entrypoint ABI and lets the **current workspace runtime** own protocol selection.

## ABI v1

For every `push` / `publish` request in Web or Local mode, call the current workspace's:

```bash
python3 scripts/codex_loop.py publish-enter --cwd REPO \
  --session-id ROUTING_SESSION \
  --repository OWNER/REPO --branch BRANCH \
  --remote-head FULL_REMOTE_HEAD --remote-tree FULL_REMOTE_TREE \
  --controller-abi 1 \
  [--capability-scope github_push=repo:OWNER/REPO] \
  [--capability-scope google_drive_write=drive:ChatGPT-GitHub-Staging]
```

`publish-enter` is the only model-facing publication entrypoint. Low-level `web-publish-*` and Local `publish-plan` commands are workspace implementation details used by the router or for router debugging.

The CLI requires `--controller-abi` explicitly; omission is invalid rather than silently assuming the workspace's current ABI. This keeps version negotiation observable and prevents a stale controller from being mistaken for a current one.

The v1 envelope is intentionally small and stable:

- `entrypoint=publish-enter`;
- `router_abi` and `accepted_controller_abis`;
- deterministic `workspace_mode`;
- workspace-owned `publication_protocol` metadata;
- `workspace_protocol_reference`, pointing to the authoritative protocol instructions in the current workspace;
- `controller_contract`;
- `status` / `code`;
- `planner_result` as opaque workspace-owned data;
- `next_action` as the next model/host action.

The installed/controller Skill does **not** need to understand the current `publication_protocol.version`. That version describes the workspace-owned publication implementation. Forward compatibility comes from the router ABI, not from teaching an older controller every future transport.

## Controller rule

The controller must:

1. call `publish-enter` before any publication transport reasoning;
2. treat its result as authoritative for Web-vs-Local route and protocol;
3. read the returned `workspace_protocol_reference` from the **current workspace** before transport; the current-workspace reference outranks transport instructions bundled in the installed controller Skill;
4. execute only `next_action` and the modeled actions inside `planner_result`;
5. never infer another transport from Git terminology, connector availability, GitHub object presence, remembered older behavior, or a prior Skill version.

If the workspace lacks `publish-enter`, surface `WORKSPACE_PUBLICATION_ROUTER_MISSING`. If it returns `PUBLICATION_ROUTER_ABI_UNSUPPORTED`, surface that exact compatibility blocker. In either case stop before transport. Do **not** search for a replacement Web primitive, silently switch Local mode, reconstruct source through GitHub APIs/model text, or lower Git identity requirements.

## Current protocols

ABI v1 currently routes:

- Web -> `web_exact_git_identity` protocol v2. The verified Git bundle carries the exact audited source commit object. GitHub does not need to contain that object before publication. Success requires exact remote commit + tree equality.
- Local -> `local_native_git` protocol v1. Native Git runs from the authorized canonical local worktree and exact remote commit + tree readback proves success.

Protocol fields are descriptive workspace data. They are not controller feature flags.

## Future protocol / ABI upgrades

Use **expand -> deploy -> switch**, never a one-commit flag day.

1. **Expand:** a release adds the new protocol or new router ABI while preserving the currently installed controller ABI. For an ABI transition, support both old and new ABIs and keep the old controller path fully functional.
2. **Deploy:** install/update that compatibility release and obtain host-visible evidence that it is active where publication control will run.
3. **Switch:** only a later release may start preferring the new ABI/protocol behavior. Keep the previous ABI accepted for at least the migration window needed by the supported upgrade path.
4. **Retire deliberately:** removing an old ABI requires an explicit compatibility change plus regression updates. It must never happen implicitly while introducing the successor.

A repository change that adds a new publication protocol does not authorize the installed controller to improvise support for it. Keep the stable ABI compatible or fail deterministically.

## Self-update rule

This contract intentionally does not attempt to rescue a pre-router installed Codex Loop during the same upgrade that introduces ABI v1. Once an ABI-v1-aware Codex Loop is installed, future newer workspaces remain publishable through their own `publish-enter` implementation without requiring the older installed controller to understand newer transport details.

## Web -> local synchronization is separate

Saving/synchronizing a Web workspace to a Mac/local host is not publication and does not choose Local development. Use `web-local-sync-plan`, whose only supported data plane is exact self-contained Git bundle -> Google Drive binary staging -> RDC download to the authorized local path -> local size/SHA-256 + `git bundle verify` -> exact staging cleanup. `workspace_mode` remains Web unless the user separately selects the local repository as the development baseline.
