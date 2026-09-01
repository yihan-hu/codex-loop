# Verified Web-mode GitHub publishing

Use this contract when a conversation is still in Web mode and the user asks to push or publish the current ChatGPT workspace to GitHub. Do not enter Local mode merely because publication is requested.

## Standard data plane

The verified Web-mode source path is:

```text
current ChatGPT workspace
  -> deterministic source tar.gz + exact size/SHA-256
  -> Google Drive `ChatGPT-GitHub-Staging` via binary `file_uri`
  -> inherited `anyone: reader` permission verified by Drive metadata
  -> tiny GitHub import-request commit
  -> audited `.github/workflows/workspace-import.yml`
  -> runner downloads and verifies the exact archive
  -> safe extract + source commit/push
  -> GitHub branch commit/tree readback
  -> permanently delete the temporary Drive transport object
```

Source bytes must never pass through model text, Base64, GitHub blob/tree/contents payloads, issue bodies, or repeated connector writes. Google Drive is the binary data plane; the GitHub Connector is control plane only.

## One-time prerequisites

1. Google Drive is connected and exposes `upload_file` with a top-level `file_uri` input.
2. The user has a dedicated folder named `ChatGPT-GitHub-Staging` (or an explicitly chosen equivalent) whose metadata shows `permissions: type=anyone, role=reader` and `allowFileDiscovery=false` when available.
3. The target repository has GitHub Actions enabled and workflow permissions allow `contents: write` for `GITHUB_TOKEN`.
4. The target branch permits the workflow's non-force push. Branch protection remains authoritative; do not bypass it.
5. The target repository contains the audited `.github/workflows/workspace-import.yml`. For an empty/new repository, bootstrap that small trusted workflow through the GitHub Connector first, then observe the resulting branch head before creating an import request.

Never hard-code a Drive folder ID in the distributed Skill. Search by the configured folder name or use a folder URL/ID explicitly supplied in the conversation, then verify its metadata before every publication.

## Public-read staging boundary

This standard path intentionally uses an anyone-with-link temporary object so an unauthenticated GitHub-hosted runner can download it without Google credentials. Treat that as an explicit trust boundary:

- upload only publication archives to the dedicated staging folder;
- do not use this path when the source cannot tolerate temporary anyone-with-link readability;
- never place credentials, tokens, private keys, or unrelated user files in the staging folder;
- permanently delete the staged archive after verified success; after a terminal failure, preserve it only while needed for diagnosis, then permanently delete it;
- on an ambiguous GitHub outcome, reconcile the real workflow/branch state before deletion or retry.

If this trust boundary is unacceptable, stop and report that the standard Web-mode path is unavailable for that source. Do not silently switch to model-carried relay or GitHub source blobs.

## Build and stage the source archive

Create one gzip-compressed tar archive whose members live below exactly one top-level directory. Exclude `.git` and runtime-private state. The audited import workflow rejects absolute paths, parent traversal, symlinks, hardlinks, device entries, and archives without exactly one top-level root.

Before upload, record:

- archive byte size;
- full SHA-256;
- target repository and branch;
- exact target branch head observed immediately before the trigger commit.

Upload the real archive using the Google Drive `upload_file` file parameter. A string path, URL, Base64 string, or model-transcribed payload is not equivalent. Read Drive metadata back and require the uploaded size to equal the local archive size, the parent to equal the intended staging folder, and inherited `anyone: reader` permission to be present.

## Trusted workflow and control plane

The import workflow is repository control plane, not uploaded source authority. The current run must use the workflow already present in the trigger commit. The importer protects `.github/workflows/workspace-import.yml` and `.github/import-requests/` from archive replacement during that run.

The GitHub Connector may create or update only small UTF-8 control-plane files for this mechanism. It must not create source blobs/trees/commits from workspace file contents.

Create exactly one request file under `.github/import-requests/`, with this minimum schema:

```json
{
  "version": 1,
  "transfer_id": "unique-id",
  "file_id": "google-drive-file-id",
  "size": 123456,
  "sha256": "64-lowercase-hex",
  "expected_base": "40-hex-github-commit",
  "target_branch": "main"
}
```

Bind `expected_base` to the branch head observed immediately before the request commit. The workflow must require `expected_base == github.event.before` and `target_branch == github.ref_name`. A later branch move makes the publish fail closed rather than overwrite concurrent work.

## Workflow verification contract

Before importing source, the audited workflow must:

1. prove exactly one import-request file changed in the trigger commit;
2. validate the request schema and expected base/branch;
3. download the Drive object by `file_id`;
4. require exact byte size and `sha256sum -c` success;
5. safely extract without traversal or links;
6. apply source with `.git`, the trusted import workflow, and transient request files protected;
7. verify the remote branch still points to the trigger commit before committing;
8. create one fixed-message source commit and non-force push it to the target branch;
9. emit a receipt containing transfer ID, trigger SHA, source archive size/SHA-256, published commit, and published tree.

Do not execute workflow files from the uploaded archive during the current import run.

## Host-side success proof

A workflow conclusion of `success` is necessary but not sufficient. Before reporting `SOURCE_PUSHED`:

1. select the workflow run whose path is exactly `.github/workflows/workspace-import.yml` and whose `head_sha` equals the trigger commit;
2. require completed/success and inspect the import job steps or logs;
3. require the download/size/SHA step, safe-extract step, and source push step all succeeded;
4. read the emitted receipt or equivalent log lines and capture the published commit/tree bound to the staged archive hash;
5. read back the actual target branch from GitHub and require its commit and tree to equal the receipt;
6. only then permanently delete the exact staged Drive archive and report `SOURCE_PUSHED`.

The staging archive is a one-time **public transport artifact**, not durable recovery state. The persistence adapter's recoverable-delete preference does not apply here: after verified consumption, use the active Drive adapter's permanent delete operation for that exact staging object so an anyone-with-link archive is not retained in Trash. If staging cleanup fails after verified publication, keep `SOURCE_PUSHED` but report the cleanup warning and the remaining temporary object. Cleanup failure is not permission to republish or to broaden deletion to sibling files.

## Post-push active Skill reconciliation

Verified `SOURCE_PUSHED` is the terminal state of the Git publication phase, but it is not always the terminal state of the user task. If the published Web workspace is the source of a Skill that is already active/present in the current ChatGPT workspace or host-managed Skill environment, the push request also implies refresh of that same current Skill.

After the remote commit/tree readback succeeds and staging cleanup is reconciled, run `skill-deploy-handoff` for the exact published commit. That command creates only a planned `chatgpt_skill_update` action; it does **not** surface UI and does **not** prove deployment.

For the actual update, compose with the platform `skill-creator` workflow (or an explicitly equivalent native host-managed Skill update primitive) using the validated source/package generation bound to the same pushed commit. Codex Loop must never emulate a Save/Update UI in prose. When the host actually surfaces/initiates the native update control, record it with `skill-deploy-surface-record`; this may establish `UI_SURFACED` but still leaves `DEPLOY_PENDING`. Only after the intended revision is observably active may `skill-deploy-complete` establish `DEPLOYED`.

If no native Skill installation/update surface can be invoked or observed, retain `SOURCE_PUSHED`, leave the external action unresolved, and report `DEPLOY_PENDING — HOST_SKILL_INSTALL_SURFACE_NOT_OBSERVED`. Do not republish the source and do not substitute an internal handoff record for host UI evidence. Browser/computer interaction remains subject to the ordinary explicit computer-use gate.

## Empty repositories and bootstrap

An empty repository needs one control-plane bootstrap commit before it can run Actions. Creating the audited workflow file through the GitHub Connector is allowed because it is small trusted control plane, not source transport. After bootstrap, observe that commit as the branch head and bind the first import request to it.

Do not use GitHub object APIs to populate the empty repository with source files. The first source population must still come through the verified Drive -> Actions data plane.

## Relationship to Local mode

This path is Web mode only. Once a conversation has explicitly entered Local mode, local repository publishing continues to use the RDC + native Git contract in `verified-native-git.md`; do not route local source through Drive merely because the Web-mode path exists.
