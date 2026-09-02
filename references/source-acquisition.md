# Source acquisition and bootstrap policy

Use this reference whenever Codex Loop must establish a new mutable workspace from GitHub, Google Drive, or a user-provided source. Source acquisition happens **before** ordinary development; persistence, publication, packaging, and deployment are separate stages.

## Invariants

- Resolve `workspace_mode` first. A source-transfer problem never silently selects Local mode.
- A successfully materialized fresh workspace becomes the only mutable source authority.
- Normal source acquisition is limited to **user upload, Google Drive, or GitHub**.
- Transport objects (Actions artifacts, Workspace Capsules, tarballs, release packages, Drive cache files) are evidence/data plane, never later mutable source authorities.
- Never edit a host-installed Skill directory in place.
- Never auto-select an installed Skill as a development source merely because it is available, current, convenient, or the GitHub path is blocked.
- Never infer success or failure from a tool's inability to observe an event it does not support.

## GitHub -> Web workspace: required path

When the user asks to pull, open, refresh, or synchronize repository source **from GitHub** into the current Web workspace, preserve Git identity through this path:

```text
observe exact repository + target branch/commit
  -> audited .github/workflows/workspace-download.yml
  -> workflow run whose head_sha == exact target commit
  -> commit-bound Git bundle artifact
  -> GitHub Connector download_workflow_artifact
  -> verify GitHub artifact ZIP digest when available
  -> read the same job log and obtain bundle SHA-256 + exact commit/tree
  -> extract the downloaded artifact ZIP
  -> verify the Git bundle SHA-256
  -> git bundle verify
  -> materialize a fresh real Git repository from the bundle
  -> require restored HEAD == exact target commit
  -> require restored HEAD^{tree} == exact target tree
  -> bind subsequent development to that workspace
```

The standard workflow packages a Git bundle, not `git archive`. It uses full checkout history, creates a temporary export ref pointing at the exact workflow `HEAD`, logs the bundle's SHA-256/size plus exact commit/tree, uploads a `<repo-name>-source` artifact, and supports both branch pushes and `workflow_dispatch`. The temporary export ref is transport metadata only; after restore, set the intended branch/HEAD and verify exact commit/tree before binding the workspace.

Do not substitute any of the following as the ordinary Web acquisition path:

- container or shell `git clone`/`git pull` from GitHub;
- GitHub Connector per-file contents/blob/tree reconstruction;
- generic GitHub archive/download URLs chosen outside the commit-bound workflow;
- source-only `git archive` when the bundle workflow is available;
- model-carried text/Base64 source relay;
- an installed Skill copy unless the user explicitly invokes the exception below.

If the exact commit has no usable download run, dispatch the audited workflow when the host exposes a workflow-dispatch capability and verify the resulting `head_sha`. If that is unavailable, a **verified incremental replay** is allowed only when all of the following are proven: (1) a usable commit-bound Git bundle exists for a known ancestor; (2) every intervening mutation is represented by an auditable deterministic patch or workflow-owned transformation with fixed size/hash or equivalent integrity evidence; (3) the transformation is replayed only inside a fresh Web workspace; and (4) the resulting complete Git commit/tree identity exactly equals the intended GitHub revision. A spot-check or per-file reconstruction is never sufficient. Record the ancestor commit, artifact digest/bundle hash, replay transformation hashes, target commit, and final commit/tree.

The Web import workflow may publish a **receipt-bound Git bundle** after verified publication. Such an artifact is acceptable even when `GITHUB_TOKEN` publication does not recursively trigger the download workflow only when the same run's receipt explicitly binds the bundle hash, published commit, and published tree, and GitHub readback confirms that published commit/tree.

If neither an exact-commit bundle, a receipt-bound published bundle, nor a fully verified incremental replay is available, stop with a precise acquisition blocker. Do not mutate repository source merely to manufacture an easier artifact.

Useful fail-precise classifications are descriptive, not additional runtime state:

- `WORKSPACE_DOWNLOAD_WORKFLOW_MISSING`
- `WORKSPACE_DOWNLOAD_TRIGGER_UNAVAILABLE`
- `WORKSPACE_DOWNLOAD_OBSERVABILITY_UNAVAILABLE`
- `WORKSPACE_DOWNLOAD_ARTIFACT_UNAVAILABLE`
- `WORKSPACE_DOWNLOAD_INTEGRITY_FAILED`
- `WORKSPACE_GIT_IDENTITY_MISMATCH`

An empty result from a connector action that only supports a different trigger class is `...OBSERVABILITY_UNAVAILABLE`, not proof that the workflow never ran.

## Google Drive / user upload -> Web workspace

A Drive object or user upload may be used when the user selects it as source. Prefer a Codex Loop Workspace Capsule when one is available because it preserves Git identity and resumable dirty state. For a generic uploaded/source package, validate its format and provenance as far as the available manifest permits; never call it the current GitHub revision without exact evidence.

For Drive Workspace Capsules, read `persistence.md`. Restore only into a fresh workspace, verify outer SHA-256 plus capsule internals, require exact HEAD commit/tree and staged/unstaged/non-ignored-untracked state fingerprint, then bind the restored workspace. A successfully consumed capsule is immediately cleanup-eligible; cleanup failure does not invalidate the restored workspace.

## Installed Skill bootstrap: default off, explicit exception only

An installed Skill is deployment state and is **not part of normal source resolution**. Do not inspect or copy it as fallback when GitHub/Drive/upload acquisition is inconvenient or blocked.

Use an installed Skill as a one-time bootstrap source only when the user explicitly authorizes that source in the **current conversation/turn context**, for example: “use the installed Codex Loop as the source for this workspace.” Generic requests such as “update Codex Loop,” “modify the installed Skill,” or “use the latest version” are not authorization to copy the installed directory.

When the explicit exception is invoked:

1. Keep the installed directory read-only and copy it into a fresh development workspace before mutation.
2. Run deployment-provenance verification when `references/deployment-manifest.json` exists.
3. If the user expects the current/latest target-branch revision, require a fresh GitHub remote observation and exact installed commit/tree equality before calling it current.
4. If the installed manifest binds a different exact revision and the user explicitly accepts that installed revision as the development starting point, record `freshness=historical_explicitly_accepted`; never call it latest.
5. If exact provenance is unavailable but the user still explicitly selects the installed copy, label it `provenance=unverified_user_selected`; require later source/remote reconciliation before publishing to an existing canonical repository.
6. Record source kind `installed_skill_exception`, exact repository/revision when known, provenance/freshness status, and hashed current-turn authorization evidence in private runtime state only.
7. After copying, bind only the fresh workspace and never return to the installed directory as competing source authority.

This exception does not bypass Local-mode or filesystem authorization. If the installed Skill is on an RDC-backed host, Local mode and current-task filesystem authorization must already permit the read-only copy operation.

## Completion evidence

Before treating source acquisition as complete, retain enough evidence to answer:

- Which repository/source and exact revision were intended?
- Which acquisition method was used (`github_git_bundle`, `receipt_bound_git_bundle`, `drive_workspace_cache`, `user_upload`, `verified_incremental_replay`, or `installed_skill_exception`)?
- What proved the source bytes/Git objects belonged to that revision?
- What integrity checks passed?
- Which fresh workspace became the sole mutable baseline?
- If the installed-Skill exception was used, what current-turn user authorization and provenance/freshness label justified it?

A later publication still follows the normal Web or Local publish contract; acquisition evidence does not replace publish/readback evidence.
