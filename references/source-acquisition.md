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

Treat `git clone`, `git pull`, `git fetch`, “open this repo”, “refresh from GitHub”, and “sync from GitHub” as **source-acquisition intent**, not as a requirement to execute those literal shell commands. In Web mode, automatically translate that intent into this verified Git-bundle path. Do not report “shell git clone/pull is forbidden” as the blocker when the canonical bundle path is available; block only when the canonical path itself cannot produce, retrieve, or verify the required revision.

For an already bound Web repository, interpret `git pull`/`git fetch` as “synchronize the canonical Web repository to the requested remote revision while preserving exact Git identity.” Satisfy that through the verified acquisition/replay mechanisms below rather than network Git from the container.

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
  -> set the canonical GitHub origin and intended target branch
  -> run source-acquisition-verify against exact repository/commit/tree/branch
  -> require restored HEAD == exact target commit
  -> require restored HEAD^{tree} == exact target tree
  -> require complete non-shallow Git history and matching canonical origin
  -> only then bootstrap/bind subsequent development to that workspace
```

The standard workflow packages a Git bundle, not `git archive`. It uses full checkout history, creates a temporary export ref pointing at the exact workflow `HEAD`, logs the bundle's SHA-256/size plus exact commit/tree, uploads a `<repo-name>-source` artifact, and supports both branch pushes and `workflow_dispatch`. The temporary export ref is transport metadata only; after restore, set the intended branch/HEAD and verify exact commit/tree before binding the workspace.

Before durable bootstrap or any source mutation, run the deterministic verifier from the fresh restored repository:

```bash
python3 scripts/codex_loop.py source-acquisition-verify \
  --cwd /FRESH/WEB/REPO \
  --repository OWNER/REPO \
  --expected-commit FULL_COMMIT \
  --expected-tree FULL_TREE \
  --branch TARGET_BRANCH \
  --method github_git_bundle
```

For a receipt-bound publication artifact use `--method receipt_bound_git_bundle`. `PASS` proves the restored working tree is a real non-shallow Git repository whose HEAD/tree, canonical GitHub origin, and intended branch match the acquisition contract. `BLOCKED` means the workspace must not be bootstrapped or rebound as canonical source. A source-only snapshot initialized as a new root commit is therefore rejected before development begins.

Do not substitute any of the following as the ordinary Web acquisition path:

- container or shell `git clone`/`git pull` from GitHub;
- GitHub Connector per-file contents/blob/tree reconstruction;
- generic GitHub archive/download URLs chosen outside the commit-bound workflow;
- source-only `git archive` when the bundle workflow is available;
- model-carried text/Base64 source relay;
- an installed Skill copy unless the user explicitly invokes the exception below.

If the exact commit has no usable download run, first look for a **receipt-bound Git bundle**: the self-contained published bundle produced by a verified Web publish of that exact current GitHub revision. The publish run must bind the artifact name/ID, raw bundle SHA-256/size, published commit/tree, and a successful fresh-empty-repository restore proof; GitHub branch readback must still equal that commit/tree. This is a direct acquisition path, not fallback.

If neither an exact-commit download bundle nor an exact receipt-bound published bundle exists, **stop by default** with `WORKSPACE_DOWNLOAD_ARTIFACT_UNAVAILABLE`. Do not automatically start incremental replay, per-file reconstruction, installed-Skill bootstrap, model relay, or Local mode merely because the direct artifact is missing. Call `source-acquisition-plan` before any alternate recovery. A fallback becomes eligible only after the host/model has observed an explicit **current-task user authorization** for that named fallback and passes `--current-user-fallback-authorization-observed` plus audit evidence. The authorization is current-task-only and must never be persisted as a preference.

When the explicitly authorized fallback is **verified incremental replay** (`verified_incremental_replay`), require all of the following: (1) a usable commit-bound Git bundle for a known ancestor; (2) every intervening mutation represented by auditable deterministic patch/object evidence with fixed hashes or equivalent integrity evidence; (3) replay only inside a fresh Web workspace; and (4) the resulting **complete Git commit/tree identity** exactly equals the intended GitHub revision. Record the ancestor artifact digest/bundle hash, replay object/patch hashes, target commit, and final commit/tree. A spot-check is never sufficient.

Any restored commit/tree mismatch is `WORKSPACE_GIT_IDENTITY_MISMATCH` and stops the direct path. **A tree mismatch is never a trigger for automatic slow inspection or recovery.** Surface the control-plane/acquisition defect and require a new explicit user authorization before any alternate fallback is attempted. Do not mutate repository source merely to manufacture an easier artifact.

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
2. Run deployment-manifest verification when `references/deployment-manifest.json` exists.
3. A schema-v2 `consumer` manifest proves runtime-byte integrity only and intentionally contains no repository identity. Never infer a maintainer repository or any other canonical repository from it. If repository identity is needed, obtain it from the current task/user or another authoritative current source.
4. If an explicit `maintainer` or legacy provenance manifest binds the installed package to a repository/commit/tree, treat that identity as provenance only. If the user expects the current/latest target-branch revision, require a fresh GitHub remote observation and exact installed commit/tree equality before calling it current. Provenance never authorizes or binds the user's connector/repository.
5. If the installed manifest binds a different exact revision and the user explicitly accepts that installed revision as the development starting point, record `freshness=historical_explicitly_accepted`; never call it latest.
6. If exact repository provenance is unavailable but the user still explicitly selects the installed copy, label it `provenance=unverified_user_selected`; require later source/remote reconciliation before publishing to an existing canonical repository.
7. Record source kind `installed_skill_exception`, exact repository/revision when known, provenance/freshness status, and hashed current-turn authorization evidence in private runtime state only.
8. After copying, bind only the fresh workspace and never return to the installed directory as competing source authority.

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
