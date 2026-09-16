# Google Drive storage policy

Use one fixed top-level Drive boundary for all ChatGPT-created temporary material:

```text
ChatGPT-Temporary/
```

Every task-owned temporary file or folder belongs under this root, including permission-smoke sentinels, upload/download staging, GitHub publication bundles, Workspace Cache capsules, transient persistence material, and other caches. Do not place temporary objects directly in My Drive root or in a top-level folder named after a Skill.

Use purpose-scoped children when separation matters. Codex Loop uses:

```text
ChatGPT-Temporary/codex-loop/github-staging
ChatGPT-Temporary/codex-loop/workspace-cache
ChatGPT-Temporary/codex-loop/handoff
ChatGPT-Temporary/codex-loop/smoke
```

A top-level Skill-named folder such as `codex-loop/` is reserved for content intentionally retained as an archive beyond the active task. Caches, smoke-test objects, staging bundles, transfer intermediates, and other disposable material are never archive content merely because they may survive for a TTL.

## Cleanup semantics

Prefer moving temporary objects to Drive trash when the active host/connector exposes a real trash operation. Google Drive API v3 implements this as `files.update` with `trashed=true`; do not emulate it by moving the object into an ordinary folder.

The current ChatGPT Google Drive connector exposes `delete_file` as permanent deletion and its `update_file` surface does not expose the `trashed` field. Do not claim trash occurred when only permanent delete is available. Permanent deletion is allowed only for an exact task-owned temporary object that the calling workflow already classified as disposable and cleanup-authorized. Archive/retained content never enters this temporary cleanup path.

A terminal provider success is sufficient cleanup evidence. Re-read external state only when dispatch failed ambiguously, timed out after dispatch, or otherwise produced `outcome_unknown`.
