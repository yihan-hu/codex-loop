# Controller-owned publication routing

Repository publication is mode-dependent, but routing authority stays in the installed/bundled Codex Loop controller. The target repository is workspace data, not a publication controller and does **not** need to contain Codex Loop runtime files.

## Entry rule

Treat `git push`, `push main`, `publish`, and equivalent wording as publication intent. Intercept that intent before literal transport execution, resolve `workspace_mode`, then use exactly one canonical path:

```text
publication intent
  -> Codex Loop routing
     -> Web   -> verified exact-identity Web publication
     -> Local -> native Git from the bound worktree + exact remote commit/tree readback
```

The bundled controller may call its own stable helper:

```bash
python3 CODEX_LOOP_ROOT/scripts/codex_loop.py publish-enter --cwd REPO \
  --session-id ROUTING_SESSION \
  --repository OWNER/REPO --branch BRANCH \
  --remote-head FULL_REMOTE_HEAD --remote-tree FULL_REMOTE_TREE \
  --controller-abi 1
```

`CODEX_LOOP_ROOT` is the installed/controller Skill root, not the target repository. Passing `--cwd REPO` binds publication to the target workspace. A missing `REPO/scripts/codex_loop.py` is therefore irrelevant and must never produce a publication blocker.
## Controller contract

The controller must:

1. intercept publication intent before literal transport execution;
2. treat the current routing state as the deterministic projection of the user's explicit Web/Local selection;
3. return `mode_protocol_reference` for the selected mode;
4. execute only the selected mode's modeled actions;
5. require exact remote identity verification after publication;
6. never require an ordinary target repository to ship `publish-enter` or another Codex Loop runtime file.

The controller ABI is an internal controller/runtime compatibility check. It is **not** a requirement imposed on target repositories. A future controller ABI may evolve without turning application repositories into Codex Loop extensions.

## Web mode

Web mode uses `references/web-mode-publish.md`. Native local Git is not substituted merely because it is available through RDC. The verified Web path preserves audited Git identity and its existing staging/import integrity rules.

A Web-path failure is reported as a Web publication blocker or a modeled recovery choice. It never silently selects Local mode.

## Local mode

Local mode uses `references/verified-native-git.md`. Once the user explicitly selects Local and repository access is granted, native Git is first-class canonical execution, not a fallback.

The minimal Local sequence is:

```text
validate/review current worktree
  -> fetch/observe remote
  -> prove fast-forward ancestry or integrate explicitly
  -> native git push
  -> fetch/read remote
  -> require remote commit == local audited commit
  -> require remote tree == local audited tree
```
If native Git fails because of authentication, network, branch protection, divergence, or permissions, report that exact blocker. Do not switch transport or force-push around it.

## Self-update special case

When the target repository is Codex Loop itself, maintainers may test/use the validated workspace copy of the controller during development. That is a self-hosting convenience for Codex Loop source, not a rule that propagates to other repositories.

## Why intent interception remains mandatory

Removing interception would reintroduce the original Web-routing failure class: the model could see `git clone` or `git push` and execute the literal command before knowing whether the authoritative workspace is Web or Local. The invariant is therefore:

> **Intent interception is mandatory; transport substitution is mode-dependent.**

In Web mode, Codex Loop substitutes the verified Web semantic equivalent. In Local mode, the canonical transport may be the literal native Git command itself after routing and authorization have been established.
