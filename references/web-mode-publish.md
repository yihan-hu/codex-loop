# Verified Web-mode GitHub publication with exact Git identity

Use this low-level workspace-owned contract after the stable route-aware `publish-enter` ABI selects Web publication. This path preserves the audited Git commit object itself: successful publication requires **remote commit == audited source commit** and **remote tree == audited source tree**. Normal model control must enter through `references/publication-router.md`; call `web-publish-*` directly only when debugging the router/protocol implementation.

This path is Web mode only. Do not switch to RDC + native Git merely to gain transport; Local mode has its own native-Git contract behind the same stable publication router.

## Publication intent translation

Treat `git push`, “push this branch”, “publish this commit”, “send these changes to GitHub”, and equivalent wording as **publication intent**, not as a requirement to execute native network `git push`. In Web mode, automatically satisfy that intent through this verified bundle/staging/import path. The absence of native `git push` in the Web container is not itself a blocker.

Report a publication blocker only when this canonical Web publication path itself cannot satisfy its preconditions, permissions, integrity checks, or exact remote identity requirements. Do not switch transports merely because the user used Git terminology. **GitHub not already containing the audited source commit object is not a blocker**: the verified Git bundle is specifically how that exact commit object is introduced to the importer. Do not query object presence as a transport-selection gate.

## Trust and data-plane boundary

Source Git objects move only through a binary Git bundle:

```text
canonical Web Git workspace
  -> audited clean HEAD commit/tree
  -> deterministic/verified Git bundle + SHA-256/size
  -> private local file_uri
  -> dedicated Google Drive ChatGPT-GitHub-Staging folder
  -> temporary anyone: reader visibility required by GitHub-hosted runner
  -> audited .github/workflows/workspace-import.yml
  -> exact audited commit installed on target branch
```

The GitHub Connector is control plane only. It may read repository state, preflight push/Actions permission, bootstrap/update the small trusted workflow, and create one tiny `.github/import-requests/*.json` trigger. It must not relay source bytes through contents/blob/tree payloads, comments, model text, or Base64.

The public-read staging boundary is temporary and explicit. If source cannot tolerate anyone-with-link readability even briefly, stop; do not silently choose another transport.

## Preconditions

Before staging:

1. `workspace_mode=web` and `route-check --action github_publish` passes.
2. The canonical Web workspace is a real Git repository and clean.
3. Current-generation executable validation is fresh when required.
4. Current-generation final change review is fresh.
5. Exact target branch remote HEAD/tree is observed.
6. Fresh scoped permission observations exist for `github_push` and `google_drive_write`. The publication transport does not call a host Actions write API; Actions readiness is verified after the request push by observing the matching import run and its receipt/log evidence.
7. `.github/workflows/workspace-import.yml` matches the audited exact-identity importer contract below.

Normal model/controller entry:

```bash
python3 scripts/codex_loop.py publish-enter --cwd REPO \
  --session-id SESSION \
  --repository OWNER/REPO \
  --branch TARGET \
  --remote-head FULL_REMOTE_HEAD \
  --remote-tree FULL_REMOTE_TREE \
  --controller-abi 1 \
  --capability-scope github_push=repo:OWNER/REPO \
  --capability-scope google_drive_write=drive:ChatGPT-GitHub-Staging
```

The router begins/reuses the publish-only continuation and calls this Web planner. Low-level debugging may still use `web-publish-plan` / `web-publish-bundle`. `web-publish-archive` remains only a compatibility alias for bundle creation; it no longer creates a tar source archive.

`github_actions` is intentionally absent from this host-permission gate. The importer is triggered by the GitHub request commit itself, not by an Actions dispatch/rerun API call. After that trigger, treat the matching workflow run as the live Actions/runtime proof; a missing or failed run is a publication failure to reconcile, not a reason to fabricate an earlier source-mutating permission probe.


## Git bundle identity

The bundle builder creates a temporary `refs/heads/codex-loop-publish-<nonce>` pointing to the exact audited HEAD, runs `git bundle create`, deletes the temporary local ref, verifies the bundle, and records:

- audited source commit;
- audited source tree;
- bundle ref;
- bundle byte size;
- bundle SHA-256;
- current lifecycle generation + validation/review generation.

A dirty workspace, stale validation, or stale final review blocks bundle creation. The Drive file is transport only and never becomes a development baseline.

## Workflow-changing publication control plane

GitHub-hosted import jobs run with `GITHUB_TOKEN` / GitHub App credentials. `contents: write` is sufficient for ordinary source refs, but GitHub separately rejects a push that creates or updates `.github/workflows/**` when that App token lacks workflow-file write permission. Therefore a Web publish whose audited source changes workflow files must **not** discover this only after staging and triggering an importer.

Before any bundle staging or import-request commit, `web-publish-plan` must compare audited HEAD with the exact observed remote base. If `.github/workflows/**` differs, return `FAST_PUBLISH_CONTROL_PLANE_REFRESH_REQUIRED` and list each workflow path plus `create` / `update` / `delete`. The host must then:

1. use the GitHub Connector only for those reviewed workflow control-plane files, starting from the exact observed branch head;
2. observe the resulting remote commit/tree;
3. reacquire that exact control-plane revision through `Workspace Download` or another approved exact GitHub -> Web acquisition path;
4. in that fresh Web workspace, reapply only the remaining non-workflow source delta and prove the complete resulting tree equals the previously audited source tree before any new semantic edit;
5. rerun the default FAST planner against the refreshed remote base.

Do not create a FAST/standard import request before this refresh is complete. Do not relay ordinary repository source bytes through GitHub contents/blob/tree APIs. This is a narrow control-plane exception for workflow files and preserves the binary Git-bundle data plane for the rest of the source. If the required exact reacquisition cannot be proven, stop rather than fabricate ancestry or force a different transport.

## Staging and trigger request

Upload the exact bundle binary to the dedicated `ChatGPT-GitHub-Staging` Drive folder through the real `file_uri` bridge. Record returned Drive file ID, exact size, and SHA-256. Apply temporary `anyone: reader` access only to that exact staging object/folder boundary required by the runner.

Create exactly one tiny request file on the **target branch**:

```json
{
  "version": 2,
  "transfer_id": "unique-nonce",
  "bundle_file_id": "DRIVE_FILE_ID",
  "bundle_size": 12345,
  "bundle_sha256": "64hex",
  "bundle_ref": "refs/heads/codex-loop-publish-<32hex>",
  "expected_base": "40hex-target-head-before-trigger",
  "target_branch": "branch-name",
  "source_commit": "40hex-audited-head",
  "source_tree": "40hex-audited-tree"
}
```

The trigger commit is **not release/source history**. It is a temporary control-plane commit whose parent must equal `expected_base` and whose only file delta must be the newly added request JSON.

## Audited importer semantics

The separate `.github/workflows/workspace-download.yml` workflow must ignore pure `.github/import-requests/**` push triggers. The temporary control-plane commit is not a source revision worth exporting, and allowing Download to run on that commit wastes an Actions job/artifact without contributing to publication.

The workflow must:

1. prove exactly one request file was added by the trigger commit;
2. require `expected_base == github.event.before` and trigger parent == `expected_base`;
3. download the Drive bundle and verify exact byte size + SHA-256;
4. run `git bundle verify`;
5. fetch only the declared bundle ref into a temporary local ref;
6. require fetched commit == request `source_commit`;
7. require `source_commit^{tree}` == request `source_tree`;
8. require `expected_base` is an ancestor of `source_commit`;
9. re-read target branch and require it still equals the trigger `GITHUB_SHA`;
10. publish with a **single bounded** `force-with-lease` that replaces only that exact trigger commit:

```bash
git push \
  --force-with-lease="refs/heads/$TARGET:$GITHUB_SHA" \
  origin "$SOURCE_COMMIT:refs/heads/$TARGET"
```

11. immediately read back the target ref and require it equals `source_commit`;
12. build a **self-contained** published-revision Git bundle from complete history, prove it by cloning into a fresh empty repository and requiring exact published commit/tree, upload that one acquisition artifact, then emit a receipt binding transfer ID, trigger SHA, transport bundle hash/size/ref, published commit/tree, published-source artifact ID/name/hash/size, and `fresh_restore=PASS`.

This is not general force-push authorization. The only permitted non-fast-forward movement is deletion of the workflow's **own single request trigger commit**, guarded by exact lease identity. Any extra branch movement, mismatched parent, multi-file trigger delta, ancestry failure, or lease failure stops publication.

## Receipt and remote verification

Before reporting `SOURCE_PUSHED`:

1. require the exact selected import workflow run to complete successfully;
2. inspect its job steps/logs for bundle download/hash/verify, source commit/tree verification, ancestry check, bounded lease push, and remote readback;
3. for `FAST_PUBLISH`, require the one-line `CODEX_LOOP_FAST_IMPORT_RECEIPT=<json>` log receipt from `.github/workflows/workspace-import-fast.yml`; that receipt must bind the uploaded `published-source-<run_id>` acquisition artifact by artifact ID/name plus raw bundle SHA-256/size and `fresh_restore=PASS`; do not download it during the current publish unless reconciliation requires it;
4. for `FULL_VERIFIED_PUBLISH`, download and verify the ordinary receipt artifact from `.github/workflows/workspace-import.yml`;
5. require receipt `published_commit == audited source_commit`;
6. require receipt `published_tree == audited source_tree`;
7. independently read target branch from GitHub;
8. require remote commit == audited source commit and remote tree == audited source tree.

Tree-only equivalence is insufficient. A newly generated importer commit is a contract violation under this exact-identity design.

## FAST_PUBLISH

### Mandatory push-entry rule

For every Web-mode `push`/`publish` continuation, treat the request as delivery intent rather than a semantic `steer` unless source requirements also changed. **Normal model/controller control calls only `publish-enter --controller-abi <explicit ABI>` before any new validation, permission smoke, bundle construction, Drive staging, production packaging, or import trigger.** The router then performs the low-level continuation/planner sequence inside the current workspace runtime.

Internally, the router calls `web-publish-continuation-begin` and then `web-publish-plan`. If continuation returns `active=true` / `revalidation_forbidden=true`, the current clean generation already has reusable validation/review evidence and the router must not plan redundant validation. The Web planner remains the deterministic performance gate and defaults to FAST_PUBLISH; `--verified-tree-fast-path` is only a compatibility alias and standard publication remains explicit-only through `--standard-web`. Fresh validation/review/capability observations and a matching bundle receipt are reused when valid. A remote short-circuit is allowed only when **both** remote commit and remote tree already equal audited source commit/tree.

Do not reinterpret this internal sequence as a second model-facing publication entry. Direct `web-publish-continuation-begin` / `web-publish-plan` calls are reserved for router/protocol debugging.

Every successful FAST_PUBLISH must also close the **published-revision acquisition closure**: the same run uploads one self-contained `published-source-<run_id>` bundle after proving a fresh empty repository restores the exact published commit/tree. This artifact is for a later Web conversation; it is not the transport used for the current push and does not preserve the prior workspace.

For an unpublished audited HEAD whose observed remote head is a locally provable ancestor, the plan must return `bundle_strategy=thin_from_remote_head` and `bundle_build_prerequisite_commit=<remote_head>`. Build exactly that one thin bundle. **Do not attempt a full-history bundle first.** A full bundle belongs only to an explicitly selected standard `FULL_VERIFIED_PUBLISH` operation. Because FAST_PUBLISH is the default, failure to prove the thin direct path never permits an implicit downgrade into the standard path. A reusable bundle receipt is valid for FAST_PUBLISH only when its prerequisite exactly matches the plan; do not reuse a larger full bundle when the plan requires a thin one.

A successful FAST_PUBLISH plan carries a zero-waste budget for gates already proven in this task/session: `permission_smoke_probes=0`, `validation_commands=0`, `change_review_repeats=0`, `full_bundle_attempts=0`, `production_packaging_steps=0`, and `workflow_artifact_uploads=0`. It selects `.github/workflows/workspace-import-fast.yml`, writes the request under `.github/fast-import-requests/`, and uses a structured log receipt. The only local transport build may be one thin bundle when an exact matching receipt does not already exist. During iterative performance tuning, keep each intermediate cycle source-only and measure the real publish segment; package/deploy the Skill only after the fast-path acceptance target is met. When only ordinary freshness gates are stale, the planner returns `FAST_PUBLISH_REFRESH_REQUIRED` with exact `required_refresh_actions`; execute only those actions and retry the same default planner. It must not offer or execute a standard importer merely because validation/review/capability evidence is stale. When a structural fast-path invariant is broken, it returns fail-closed state with no workflow/request path and a **modeled recovery menu** rather than silently choosing a fallback: `retry_fast`, `standard_web`, and `local_handoff`. Ordinary stale gates may be refreshed for `retry_fast`. A structural fast-path defect still remains evidence that should be repaired before another fast retry, but it does not force the user to repair performance infrastructure before completing the underlying publication objective. `standard_web` requires explicit user selection and re-plans with `--standard-web`; it keeps `workspace_mode=web` and uses the audited full verified Web importer. `local_handoff` also requires explicit user selection and follows `references/web-to-local-handoff.md`. When the audited source already lives in Web mode, recommend `standard_web` over `local_handoff` unless a local-only requirement makes the host transition worthwhile. Never silently switch FAST_PUBLISH into either fallback.
For a push-bound change set, perform the authorized `git add`/index update **before** the final validation and final change review. The workspace freshness model is content-addressed across the subsequent commit when the staged content is unchanged, so that commit must not trigger another validation/review. Staging after validation is a real content-state transition and is therefore intentionally not fast-pathed.

## Cleanup

After exact remote readback succeeds:

1. permanently delete the exact staged Drive bundle after a fresh ID/title/parent readback;
2. if deletion fails, refresh identity and retry at most once in this publication operation;
3. report any residue explicitly; never broaden deletion scope or touch Workspace Cache/private persistence folders;
4. tiny request trigger history should already be absent because the branch was lease-replaced by the audited source commit.

`ChatGPT-GitHub-Staging` is public transport, not durable persistence. The 7-day Workspace Cache retention/consumption rules in `persistence.md` do not apply here.

## Failure classifications

Fail closed with a precise blocker, for example:

- `WEB_PUBLISH_WORKSPACE_NOT_CLEAN`
- `WEB_PUBLISH_VALIDATION_STALE`
- `WEB_PUBLISH_REVIEW_STALE`
- `WEB_PUBLISH_CAPABILITY_NOT_PREWARMED`
- `WEB_PUBLISH_BUNDLE_INTEGRITY_FAILED`
- `WEB_PUBLISH_SOURCE_IDENTITY_MISMATCH`
- `WEB_PUBLISH_BASE_DIVERGED`
- `WEB_PUBLISH_TRIGGER_NOT_MINIMAL`
- `WEB_PUBLISH_LEASE_FAILED`
- `WEB_PUBLISH_REMOTE_IDENTITY_MISMATCH`
- `WEB_PUBLISH_STAGING_CLEANUP_PENDING`

Do not respond to any of these by silently switching to Local mode, force-pushing without the exact trigger lease, reconstructing files through GitHub APIs, or lowering commit/tree equality to content similarity. A fail-closed FAST_PUBLISH result may offer the modeled explicit recovery menu above; no fallback executes until the user selects it.
