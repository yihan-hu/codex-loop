# Skill source, release, deployment, and transfer boundaries

Keep development location, source lineage, workspace synchronization, and ChatGPT installation state separate. Use this reference whenever a task asks to install/update a Skill, asks whether local changes synchronize into ChatGPT, or moves an artifact between the current ChatGPT workspace and the local host.

## Development modes

- **A new conversation starts in web mode.** The current ChatGPT/web workspace is the mutable source baseline. Make edits and validations there and return generated files with normal workspace download links. Do not enter Local mode or use Remote Desktop Commander merely because those capabilities are available.
- **Development mode is a pre-tool gate.** Resolve the conversation mode before the first repository/filesystem discovery, mutation, packaging, Git, transfer/synchronization, or repository-affecting RDC action in a repository/Skill-development task. Until an explicit Local-mode selection exists, the answer is Web mode and the current ChatGPT workspace remains authoritative. Interaction-only RDC/computer use is routed separately and never selects the repository workspace. Domain-specific Skills do not get to choose a different workspace before this gate runs.
- **Web mode fails closed.** RDC availability, a visible Mac checkout, an installed Skill copy, or failure to find an obvious Web write/publish bridge does not authorize a Local-mode fallback. Preserve the Web source and report the exact missing capability instead of searching or mutating local files. A verified-latest installed Skill may bootstrap a *new* workspace under the narrow exception in `source-acquisition.md`; that exception does not make the installed directory mutable authority or select Local mode.
- **Local mode is explicit once per conversation.** Enter it only when the user explicitly asks to make a local/PiWork/Mac checkout the repository-development baseline. A request to use RDC, Chrome, computer use, or native macOS interaction by itself does not select Local mode. Once selected, keep local mode for later repository tasks in that same conversation unless the user explicitly switches back to web mode. In local mode `LOCAL_ROOT/<repo>` is the authoritative mutable source workspace and GitHub is its durable remote.
- **`LOCAL_ROOT` is user-specific configuration.** Resolve it as the absolute RDC-authorized persistent development root using `local-mode-setup.md`; never substitute an author-specific home-directory path. If it is unresolved or unauthorized, fail closed before local filesystem access.
- A generic `push` request does not silently convert a conversation that is still in Web mode into Local mode. When the verified Web-mode prerequisites are available, publish from the current workspace through `web-mode-publish.md`; if those prerequisites are unavailable or the public-read staging boundary is unacceptable, preserve the Web result and report the blocker rather than migrating source without authorization.
- **Conversation reset.** A new conversation starts in web mode again; local-mode state does not persist across conversations.
- `skill.zip` is a release/install artifact, not a development baseline in either mode. Codex Loop packages carry build-generated `references/deployment-manifest.json` bound to the exact verified repository commit/tree and deterministic runtime file-manifest digest; the generated manifest is never committed and package SHA-256 remains external receipt evidence. The installed ChatGPT Skill is a deployed copy and never becomes source-of-truth merely because installation succeeded.
- **Workspace-resident Skill/package update.** For any Skill or Skill installation package already present/active in the current workspace or host-managed Skill environment, reuse that existing workspace/host resource and perform source/package publication through supported non-browser capabilities first. When Web mode is maintaining that active Skill and the user asks to push/publish the changes, post-push refresh of the current Skill is part of the requested workflow; it is not an optional reminder. The final installation/update surface is host-owned: use the platform `skill-creator` workflow or an explicitly equivalent native host-managed Skill update primitive. Codex Loop may track the required handoff but must not invent or simulate a Save/Update UI. This does not authorize Chrome/browser automation or clicking the Skills UI; actual computer-use interaction still requires explicit current-task authorization.

## Source acquisition into a Web workspace

Read `source-acquisition.md` whenever a Web-mode task needs repository source that is not already materialized in the current workspace. Keep acquisition separate from publication.

For an explicit GitHub -> Web request, the source path is fixed: exact target revision -> audited `.github/workflows/workspace-download.yml` -> commit-bound Actions artifact -> GitHub Connector download -> ZIP digest verification -> source tarball SHA-256 verification from the same workflow job -> safe extraction into a fresh Web workspace. Do not replace this with shell `git clone`, per-file GitHub contents/blob reconstruction, generic archive URLs, or model-carried source just because the container cannot reach GitHub directly. If the required workflow is missing, no exact revision-bound run can be produced, or the host cannot observe/download the artifact, report the precise acquisition blocker. An observability gap is not evidence that the workflow did not run.

For Skill maintenance when the installed Skill itself is the only convenient local source, Codex Loop may instead perform a one-time installed-Skill bootstrap **only** when the installed copy is proven to represent the latest observed target-branch revision. For a provenance-bound Codex Loop package, run `deployment-provenance-verify` first and then require current GitHub target-branch commit/tree equality. Acceptable freshness evidence otherwise is an observed deployment/install receipt bound to the exact 40-hex commit, or an audited full source/package manifest proving content equivalence to that exact commit. A version string, filename, modification time, or spot-check of a few files is not sufficient. Copy the verified installed Skill into a fresh workspace before editing, record the repository/branch/commit and verification evidence, and immediately make that new workspace the only mutable baseline. Never edit the installed Skill in place, and never return to it as a competing authority after bootstrap.

If the user explicitly asks to pull/materialize source **from GitHub**, use the GitHub Actions artifact path even when an installed Skill exists. The installed-Skill exception is a bootstrap option for verified deployment state, not a substitute for an explicit GitHub acquisition request.

## Provenance-bound package

When Codex Loop itself is packaged, read `deployment-provenance.md`. Build only after the exact source commit/tree has been verified by publication/readback. `tools/build_skill_zip.py` verifies the full source-tree SHA, emits build-generated `references/deployment-manifest.json` inside the ZIP, and returns the package SHA externally. Never commit the generated manifest or copy private Host Profile values into the package.

## Stage separation

Use these conceptual flows:

```text
Web mode (default at conversation start)
  current ChatGPT workspace
  -> edit / validate / review
  -> if GitHub publication is requested: source archive + size/SHA-256
  -> Google Drive public-read staging via binary file_uri
  -> audited GitHub Actions import + remote commit/tree readback
  -> delete staging object
  -> SOURCE_PUSHED
  -> if the edited source is the active current-workspace Skill:
       skill-deploy-handoff for that exact pushed commit
       -> invoke skill-creator / native host Skill update flow
       -> record actual native surface with skill-deploy-surface-record
       -> record active revision with skill-deploy-complete
       -> otherwise DEPLOY_PENDING and completion remains blocked
  -> for other Skill sources: packaging/install remains separately requested
  -> return downloadable files/links

Local mode (after explicit selection; persists for this conversation)
  LOCAL_ROOT canonical repo
  -> edit / validate / review
  -> git commit
  -> native git push + remote readback
  -> SOURCE_PUSHED
  -> optionally offer sync to current ChatGPT workspace
  -> if accepted and verified: WORKSPACE_SYNCED
  -> Skill packaging/install only when separately requested
```

Report the stages independently. A useful user-facing status vocabulary is:

- `SOURCE_PUSHED`: GitHub remote commit/tree matches the verified publication identity: the audited local commit/tree in Local mode, or the archive-bound workflow receipt in Web mode.
- `WORKSPACE_SYNCED`: the exact pushed commit was materialized into the current ChatGPT workspace through the verified Actions-artifact path and passed integrity checks.
- `SKILL_PACKAGED`: a verified `skill.zip` exists for that commit/tree, its embedded deployment manifest verifies the runtime allowlist, and the external package SHA-256 receipt is known.
- `DEPLOY_PENDING`: a Skill update is required for the intended revision, but the current/installed ChatGPT Skill has not yet been observably updated. A package may or may not already exist depending on the host update surface.
- `DEPLOYED`: an explicit supported install/update action or user confirmation shows that the intended Skill release is installed.

These are reporting labels, not extra runtime state commands. Never report `DEPLOYED` from Git push or packaging evidence alone.

## Web-mode GitHub publishing

When the conversation is still in Web mode and the user asks to push/publish, use `web-mode-publish.md` as the standard path. Keep the current ChatGPT workspace authoritative; do not switch to RDC/local development just to gain Git transport.

The verified data plane is Workspace binary file -> dedicated `ChatGPT-GitHub-Staging` folder in Google Drive -> audited `.github/workflows/workspace-import.yml` -> target Git branch. The GitHub Connector is control plane only: it may bootstrap the trusted workflow and create a tiny `.github/import-requests/*.json` trigger that binds Drive file ID, byte size, SHA-256, expected base commit, and target branch. It must not carry source bytes through blobs, trees, contents payloads, comments, or Base64.

If the same user request also asks to synchronize the published result to a Mac, do not inspect the Mac before publication. Finish Web-mode edit/validation/review and prove `SOURCE_PUSHED` first. Only then begin the explicitly requested downstream local synchronization phase, resolve `LOCAL_ROOT`, and update the Mac repository from that exact verified remote commit. The Mac checkout is a destination of the completed Web generation, not a source for deciding or modifying it.

Before `SOURCE_PUSHED`, require a completed/success workflow run bound to the exact trigger commit, inspect the download/hash/extract/push evidence, read the receipt-bound published commit/tree, and read the target branch back from GitHub. Delete the temporary Drive archive only after the remote identity matches.

The dedicated Drive folder is intentionally `anyone: reader` so a GitHub-hosted runner can download without Google credentials. Treat this as a user-configured trust boundary. If the source cannot tolerate temporary anyone-with-link readability, do not use this path and do not silently substitute model relay or GitHub source-object APIs.

## Web workspace Skill post-push refresh

When Web mode modifies a Skill that is already active/present in the current ChatGPT workspace or host-managed Skill environment, an explicit request to push or publish those Skill changes also implies refresh of that current Skill after publication. This is a narrow post-push invariant for the Skill being maintained; it does not make arbitrary Skill installation automatic.

### Native Skill update surface ownership

The **native Skill update surface belongs to `skill-creator`/the ChatGPT host, not to Codex Loop**. Codex Loop owns lifecycle continuity and deployment evidence bookkeeping only. **Codex Loop must never emulate, synthesize, or infer the product Install/Update UI** from an internal action, returned JSON, assistant prose, an attachment, or a generated `skill.zip`.

After verified `SOURCE_PUSHED`, create a deterministic planning handoff for the exact published commit:

```bash
python3 scripts/codex_loop.py skill-deploy-handoff \
  --cwd REPO \
  --skill-name NAME \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA
```

The handoff records a planned non-idempotent external action with kind `chatgpt_skill_update` and stable identity `chatgpt-skill:NAME@COMMIT`. It returns `NATIVE_UPDATE_REQUIRED`, `NATIVE_SURFACE_NOT_OBSERVED`, `UI_NOT_OBSERVED`, and `DEPLOY_PENDING`. Those values are deliberately completion-blocking. Repeated handoff calls for the same Skill/commit deduplicate to the same action. For `skill-name=codex-loop`, it additionally returns `handoff_mode=terminal_self_update`, `terminal_owner=skill-creator/host`, `codex_loop_resume_allowed=false`, and `reconcile_on_next_turn=true`, and installs a runtime barrier against further Codex Loop commands in that turn.

Resolve the handoff in this order:

1. For a Skill creation/update task, invoke the platform `skill-creator` workflow with the validated package/source generation bound to the same pushed commit. If the host has an explicitly supported native host-managed update primitive, it may be used instead. Do not replace either with assistant-authored instructions that merely tell the user to click Save/Update. **For Codex Loop updating itself, this invocation is the final action of the current turn.** Do not execute another Codex Loop command and do not append a Codex Loop closing/status message after the native surface is initiated.
2. For a Codex Loop self-update, wait for a later user/host turn before reconciliation. At the start of that later turn, release the terminal barrier:

```bash
python3 scripts/codex_loop.py skill-deploy-resume \
  --cwd REPO \
  --skill-name codex-loop \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA \
  --later-host-turn-observed \
  --evidence "new user/host turn after native install handoff"
```

   `skill-deploy-resume` is a turn-boundary acknowledgement, not UI or deployment evidence. It exists to prevent same-turn Codex Loop continuation from displacing a just-surfaced native install control.
3. Only after the later-turn resume (for self-update) and after the host actually exposes/initiates that native Skill surface, record the observation:

```bash
python3 scripts/codex_loop.py skill-deploy-surface-record \
  --cwd REPO \
  --skill-name NAME \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA \
  --surface-kind skill_creator_install_ui \
  --evidence "host visibly surfaced the native Skill install/update control"
```

   This advances the external action to `dispatched` and returns `NATIVE_SURFACE_OBSERVED` plus `UI_SURFACED`; deployment is still `DEPLOY_PENDING`. For a truly host-managed update that requires no UI, use `--surface-kind host_managed_update`, which records `UI_NOT_REQUIRED` rather than pretending UI was shown.
4. Only after host-visible evidence shows the intended revision is active, record deployment completion:

```bash
python3 scripts/codex_loop.py skill-deploy-complete \
  --cwd REPO \
  --skill-name NAME \
  --repository OWNER/REPO \
  --commit FULL_40_HEX_SHA \
  --evidence "current workspace Skill reports the intended revision"
```

   `skill-deploy-complete` refuses to run while the action is merely `planned`; a native surface must have actually been dispatched/observed first.
5. If no native update/install surface can be invoked or observed, leave the action unresolved and report `DEPLOY_PENDING — HOST_SKILL_INSTALL_SURFACE_NOT_OBSERVED`. Do not downgrade this into a closing note and do not call the task deployed.

`SOURCE_PUSHED`, `SKILL_PACKAGED`, `UI_SURFACED`, and `DEPLOYED` are distinct evidence states. A Git push, package build, `skill-deploy-handoff`, or assistant-authored Save/Update instruction can never satisfy `UI_SURFACED`. Likewise, `UI_SURFACED` can never satisfy `DEPLOYED` without installed-revision evidence. For Codex Loop self-update, the native install surface is also a **terminal ownership boundary for the current turn**: the next Codex Loop lifecycle action belongs to a later host turn and starts with `skill-deploy-resume`.

This rule does not grant browser/computer-use authorization. If completing the update requires interacting with ChatGPT through Chrome or macOS UI, the normal explicit computer-use authorization gate still applies.

## Local post-push workspace synchronization

This path applies when the current conversation is in local mode and a native-Git push has been verified by remote commit/tree readback. It reuses the same verified GitHub -> Web materialization contract defined above; the difference is that synchronization is opt-in after a local push. After that success, generate a deterministic offer:

```bash
python3 scripts/codex_loop.py workspace-sync-offer --repository OWNER/REPO --commit FULL_40_HEX_SHA
```

Present the returned offer to the user. Do not synchronize automatically. If the user declines, finish with `SOURCE_PUSHED`. If the user accepts, use the verified GitHub Actions artifact -> GitHub Connector -> current ChatGPT workspace path below. This is repository synchronization and works for ordinary repositories as well as Skills.

The repository must already contain an enabled `.github/workflows/workspace-download.yml` (or an explicitly equivalent audited workflow) that packages the pushed commit. Prefer the standard contract used by Codex Loop: artifact name `<repo-name>-source`, containing a commit-built source tarball, with the build step logging that tarball's SHA-256. If the workflow is absent, offer its one-time setup as a separate repository change; do not silently add it merely because local mode was selected.

For an accepted sync, require all of the following before reporting `WORKSPACE_SYNCED`:

1. Find the workflow run whose `path` is `.github/workflows/workspace-download.yml` and whose `head_sha` exactly equals the verified pushed commit; require `status=completed` and `conclusion=success`.
2. Fetch that run's artifacts and select the exact expected source artifact. Do not select an artifact only because it is newest.
3. Download it with the GitHub Connector `download_workflow_artifact` action. Require a real binary file reference that materializes in the current ChatGPT workspace; a connector metadata object alone is not synchronization success.
4. Verify the materialized artifact ZIP SHA-256 against GitHub's artifact `digest` when the digest is available.
5. Open the artifact ZIP and locate the expected source tarball. Fetch the job log for the same commit-bound workflow run, read the SHA-256 emitted by the audited `git archive HEAD` build step, and require the materialized source tarball to match it exactly. Because the run `head_sha` already equals the native-Git-readback commit, the archive is bound to that pushed revision.
6. Only then report `WORKSPACE_SYNCED` and expose the synchronized workspace files/download link as appropriate.

Do not treat synchronization as Skill packaging or installation. If the synchronized repository contains a Skill and the user asks to install/update it, validate/package that Skill as a separate next stage and report deployment state independently. Do not fall back from this verified local-to-web path to direct GitHub archive URLs, IDrive/Dropbox URLs, model-carried Base64, or per-file reconstruction merely because artifact synchronization fails.

## Transfer boundary rule

Distinguish file location from tool control. Remote Desktop Commander operates the user's remote Mac filesystem; a file that exists only in ChatGPT's conversation/sandbox storage is not automatically a Mac-local file. Likewise, a local-host artifact is not automatically installed into ChatGPT.

The verified Web-mode Drive `upload_file(file_uri=...)` path is a real binary bridge from the current ChatGPT workspace to staging when its prerequisites are present; do not claim the boundary is missing in that case.

When no verified binary transfer bridge exists between the current source and destination:

- Stop before reconstructing the file through the model.
- State where the real bytes currently live and where they need to go.
- State that the available tools do not provide a verified direct binary bridge for that boundary.
- Ask the user to place the real file at an authorized path under `LOCAL_ROOT`, use an actually supported file-transfer mechanism, or explicitly authorize a specific alternate data plane.
- Do not default to chunked text, base64, heredocs, repeated `write_file` calls, connector-created blobs, GitHub contents/object API payloads, or archive-content relay.

If the user explicitly authorizes an alternate transfer method, scope that authorization to the named transfer, preserve checksums when practical, verify the destination bytes/tree before treating the transfer as successful, and never promote a transferred artifact into the canonical source baseline.

For an explicitly authorized model-carried transfer, use `references/verified-model-relay.md`: try `GUARDED_SINGLE_SHOT_RELAY` before chunking, treat prefix/suffix guards as sacrificial framing, normalize only ASCII whitespace inside the Base64 interval, and require exact decoded size plus full SHA-256 before publishing the destination. A failed single-shot attempt may surface `VERIFIED_CHUNK_RELAY` as fallback; never heuristically repair unknown interior corruption.

## Similar-problem user guidance

When a user asks why a local repo change is not visible in ChatGPT, explain the source/synchronization/deployment separation before trying tools. A verified local push updates GitHub; if the repository has the audited workspace-download workflow, offer the Actions-artifact synchronization path to materialize that exact commit in the current ChatGPT workspace. Skill packaging and installation remain separate even after `WORKSPACE_SYNCED`.

When a user asks to move a ChatGPT-only artifact to the local host (or a local-host artifact into ChatGPT), do not immediately start encoding or chunking it. Explain the transfer boundary first and offer the shortest verified path. If no verified path is available, surface `DEPLOY_PENDING` or the transfer blocker rather than inventing a fallback.
