# Skill source, release, deployment, and transfer boundaries

Keep development location, source lineage, workspace synchronization, and ChatGPT installation state separate. Use this reference whenever a task asks to install/update a Skill, asks whether local changes synchronize into ChatGPT, or moves an artifact between the current ChatGPT workspace and the local host.

## Development modes

- **A new conversation starts in web mode.** The current ChatGPT/web workspace is the mutable source baseline. Make edits and validations there and return generated files with normal workspace download links. Do not enter Local mode or use Remote Desktop Commander merely because those capabilities are available.
- **Development mode is a pre-tool gate.** Initialize the conversation routing file and run `route-check` before the first repository/filesystem discovery, mutation, packaging, Git, install/deploy, transfer/synchronization, or repository-affecting RDC action. Until an explicit Local-mode transition exists, the authoritative state is `workspace_mode=web` and the current ChatGPT workspace remains authoritative. Interaction-only RDC/computer use and Skill deployment are routed on separate axes and never select the repository workspace. Domain-specific Skills do not get to bypass this deterministic gate.
- **Web mode fails closed.** RDC availability, a visible Mac checkout, an installed Skill copy, or failure to find an obvious Web write/publish bridge does not authorize a Local-mode fallback. Preserve the Web source and report the exact missing capability instead of searching or mutating local files. Installed Skills are not normal source acquisition and are never auto-selected; only explicit current-turn user authorization may invoke the narrow read-only copy exception in `source-acquisition.md`, and that exception does not select Local mode.
- **Local mode is explicit once per conversation.** Enter it only when the user explicitly asks to make a local/PiWork checkout the repository-development baseline. A request to use RDC, Chrome, computer use, or native macOS interaction by itself does not select Local mode. Once selected, keep local mode for later repository tasks in that same conversation unless the user explicitly switches back to web mode. In local mode `LOCAL_ROOT/<repo>` is the authoritative mutable source workspace and GitHub is its durable remote.
- **`LOCAL_ROOT` is user-specific configuration.** Resolve it as the absolute RDC-authorized persistent development root using `local-mode-setup.md`; never substitute an author-specific home-directory path. If it is unresolved or unauthorized, fail closed before local filesystem access.
- A generic `push` request does not silently convert a conversation that is still in Web mode into Local mode. When the verified Web-mode prerequisites are available, publish from the current workspace through `web-mode-publish.md`; if those prerequisites are unavailable or the public-read staging boundary is unacceptable, preserve the Web result and report the blocker rather than migrating source without authorization.
- **Conversation reset.** A new conversation starts in web mode again; local-mode state does not persist across conversations.
- `skill.zip` is a release/install artifact, not a development baseline in either mode. Every Codex Loop package carries a build-generated `references/deployment-manifest.json` bound to the deterministic runtime file-manifest digest. Consumer packages intentionally carry no repository identity; explicit maintainer packages may additionally carry exact repository/commit/tree provenance marked `provenance_only`. The generated manifest is never committed and package SHA-256 remains external receipt evidence. The installed ChatGPT Skill is a deployed copy and never becomes source-of-truth merely because installation succeeded.
- **Workspace-resident Skill/package update.** Reuse the existing workspace/host resource as source context and perform source/package publication through supported non-browser capabilities first. For Codex Loop itself, maintenance ends after the validated official `skill.zip` is copied byte-for-byte to `codex-loop.zip` and that renamed package is returned to the user; installation is manual and is not tracked by Codex Loop. Other Skills follow their own Skill Creator/host installation workflow when the user requests installation.

## Deployment target routing

Skill deployment destination is controlled by the conversation-scoped routing file, not inferred from development location or remembered tool availability. Initialize the routing plane before install/deploy work and use `route-check` for the intended action.

`deployment_target` is independent of `workspace_mode` and supports unresolved, `artifact_only`, `chatgpt_web_skill`, and `local_codex_skill`. In ChatGPT Web, a generic `install` with unresolved target resolves to the native `chatgpt_web_skill` surface. The existence of RDC, a local checkout, `~/.codex/skills`, or a prior local installation is never evidence for `local_codex_skill`. To deploy locally from a ChatGPT Web conversation, first record an explicit cross-surface transition with `route-transition --deployment-target local_codex_skill --current-user-selection-observed --selection-evidence ...`; then `route-check --action local_skill_install` must still receive current-task explicit local-install authorization.

Conversely, packaging does not imply installation: use `artifact_only` when the requested end state is only a verified `skill.zip`. If the host surface is unknown and no deployment target has been selected, installation fails closed rather than choosing a destination from context.

The routing file stores destination state and hashed selection evidence only. It never persists current-task installation consent, browser/computer-use permission, workspace grants, credentials, or source-mutation authorization.

## Source acquisition into a Web workspace

Read `source-acquisition.md` whenever a Web-mode task needs repository source that is not already materialized in the current workspace. Keep acquisition separate from publication.

For an explicit GitHub -> Web request, the source path is fixed: exact target revision -> audited `.github/workflows/workspace-download.yml` -> commit-bound **Git bundle** artifact -> GitHub Connector download -> artifact ZIP digest verification -> bundle SHA-256/size verification from the same workflow job -> `git bundle verify` -> materialization into a fresh real Git repository -> exact restored HEAD commit/tree verification. Do not replace this with shell `git clone`, per-file GitHub reconstruction, generic source archives, source-only `git archive`, or model-carried source merely because the container cannot reach GitHub directly. If the required workflow/run/artifact cannot be produced or observed, report the precise acquisition blocker.

Installed Skill bootstrap is **default off** and never participates in automatic source resolution. Only when the user explicitly authorizes the installed Skill as the source in the current conversation may Codex Loop copy it read-only into a fresh workspace. Verify deployment provenance when available; require current GitHub commit/tree equality before calling it current/latest; if the user explicitly accepts an older manifest-bound revision, record `historical_explicitly_accepted`; if provenance is unavailable but the user still selects it, record `unverified_user_selected` and require later canonical-source reconciliation before publication. Never edit the installed directory or return to it as competing authority.

If the user explicitly asks to pull/materialize source **from GitHub**, use the Git bundle Actions-artifact path even when an installed Skill exists; that explicit source choice wins.

## Consumer and maintainer packages

When Codex Loop itself is packaged, read `deployment-provenance.md`. The normal end-user artifact is the repository-neutral `consumer` profile: it packages the current validated runtime working tree, emits a build-generated manifest with `repository_binding=none`, and does not carry maintainer repository/commit/tree fields. Use the explicit `maintainer` profile only when exact source lineage is itself required evidence; that path requires a clean tracked source and verified repository/commit/tree and marks the binding `provenance_only`. Never commit the generated manifest or copy private Host Profile values into the package.

## Stage separation

Use these conceptual flows:

```text
Web mode (default at conversation start)
  current ChatGPT workspace
  -> edit / validate / review
  -> if GitHub publication is requested: verified Web publish path
  -> SOURCE_PUSHED
  -> if Codex Loop itself was updated: build + validate repository-neutral consumer skill.zip
  -> copy bytes unchanged to codex-loop.zip and verify equal SHA-256
  -> SKILL_PACKAGED
  -> return codex-loop.zip; user installs manually

Local mode (after explicit selection; persists for this conversation)
  LOCAL_ROOT canonical repo
  -> edit / validate / review
  -> git commit
  -> native git push + remote readback when requested
  -> SOURCE_PUSHED
  -> optionally offer sync to current ChatGPT workspace
  -> if Codex Loop itself was updated: build + validate repository-neutral consumer skill.zip
  -> copy bytes unchanged to codex-loop.zip and verify equal SHA-256
  -> SKILL_PACKAGED
  -> return codex-loop.zip; user installs manually
```

Report these stages independently:

- `SOURCE_PUSHED`: GitHub remote commit/tree exactly matches the audited source commit/tree.
- `WORKSPACE_SYNCED`: the exact pushed commit was materialized into the current ChatGPT workspace and passed integrity checks.
- `SKILL_PACKAGED`: a verified `skill.zip` exists, its embedded deployment manifest verifies the runtime allowlist, and the external package SHA-256 receipt is known.

For Codex Loop, packaging is the terminal update stage. Manual installation is outside Codex Loop and is not represented as a runtime deployment state.

## Web-mode GitHub publishing

When the conversation is still in Web mode and the user asks to push/publish, use `web-mode-publish.md` as the standard path. Keep the current ChatGPT workspace authoritative; do not switch to RDC/local development just to gain Git transport.

The verified data plane is Workspace binary file -> dedicated `ChatGPT-GitHub-Staging` folder in Google Drive -> audited `.github/workflows/workspace-import.yml` -> target Git branch. The GitHub Connector is control plane only: it may bootstrap the trusted workflow and create a tiny `.github/import-requests/*.json` trigger that binds the Drive Git-bundle file ID, bundle size/SHA-256/ref, exact audited source commit/tree, expected base commit, and target branch. It must not carry source bytes through blobs, trees, contents payloads, comments, or Base64.

If the same user request also asks to synchronize the published result to a local host, do not inspect the local host before publication. Finish Web-mode edit/validation/review and prove `SOURCE_PUSHED` first. Then use `web-local-sync-plan` and the fixed exact-bundle -> Google Drive staging -> RDC download path to the authorized local destination. Keep `workspace_mode=web`; the local copy is a downstream destination of the completed Web generation, not a source for deciding or modifying it. Only a separate explicit request to continue local development may later transition workspace authority.

Before `SOURCE_PUSHED`, require a completed/success workflow run bound to the exact trigger commit, inspect bundle download/hash/verify plus lease-guarded ref-update evidence, read the receipt-bound published commit/tree, and read the target branch back from GitHub. Require both to equal the audited source commit/tree exactly. Delete the temporary Drive Git bundle only after that remote identity matches.

The dedicated Drive folder is intentionally `anyone: reader` so a GitHub-hosted runner can download without Google credentials. Treat this as a user-configured trust boundary. If the source cannot tolerate temporary anyone-with-link readability, do not use this path and do not silently substitute model relay or GitHub source-object APIs.

## Codex Loop post-update manual package

When Codex Loop source changes, finish the source work, validation, review, and any explicitly requested publication first. Then produce the end-user package and return it in the same task.

1. Build the repository-neutral consumer runtime package with `tools/build_skill_zip.py`.
2. Validate the packaged `codex-loop` Skill with Skill Creator.
3. Repackage with Skill Creator's official `package_skill.py` when needed so the canonical package filename is exactly `skill.zip`.
4. Verify the official ZIP contains one top-level `codex-loop/` Skill and no development-only files or Python caches.
5. Run `python3 scripts/prepare_codex_loop_download.py --source /path/to/skill.zip --output /path/to/codex-loop.zip`. This must copy bytes only, never recompress, and must report identical SHA-256 values.
6. Return only `codex-loop.zip` and its SHA-256 to the user as the normal chat download artifact.

Stop there and return `codex-loop.zip` plus its SHA-256. The user performs installation manually through the product's supported Skills/Library interface.

For other Skills, packaging/install behavior follows the user's request and the relevant Skill Creator/host workflow; this manual-package rule is specifically the Codex Loop maintenance policy.

## Local post-push workspace synchronization

This path applies when the current conversation is in local mode and a native-Git push has been verified by remote commit/tree readback. It reuses the same verified GitHub -> Web materialization contract defined above; the difference is that synchronization is opt-in after a local push. After that success, generate a deterministic offer:

```bash
python3 scripts/codex_loop.py workspace-sync-offer --repository OWNER/REPO --commit FULL_40_HEX_SHA
```

Present the returned offer to the user. Do not synchronize automatically. If the user declines, finish with `SOURCE_PUSHED`. If the user accepts, use the verified GitHub Actions artifact -> GitHub Connector -> current ChatGPT workspace path below. This is repository synchronization and works for ordinary repositories as well as Skills.

The repository must already contain an enabled `.github/workflows/workspace-download.yml` (or an explicitly equivalent audited workflow) that packages the pushed commit. Prefer the standard Codex Loop contract: artifact name `<repo-name>-source`, containing a Git bundle whose export ref points at the exact commit, with the build step logging bundle SHA-256/size plus commit/tree. If the workflow is absent, offer its one-time setup as a separate repository change; do not silently add it merely because local mode was selected.

For an accepted sync, require all of the following before reporting `WORKSPACE_SYNCED`:

1. Find the workflow run whose `path` is `.github/workflows/workspace-download.yml` and whose `head_sha` exactly equals the verified pushed commit; require `status=completed` and `conclusion=success`.
2. Fetch that run's artifacts and select the exact expected source artifact. Do not select an artifact only because it is newest.
3. Download it with the GitHub Connector `download_workflow_artifact` action. Require a real binary file reference that materializes in the current ChatGPT workspace; a connector metadata object alone is not synchronization success.
4. Verify the materialized artifact ZIP SHA-256 against GitHub's artifact `digest` when the digest is available.
5. Open the artifact ZIP and locate the expected Git bundle. Fetch the same run's job log, read the emitted bundle SHA-256/size and exact commit/tree, require the materialized bundle to match, run `git bundle verify`, restore into a fresh real Git repository, and require restored HEAD/tree to equal the pushed commit/tree.
6. Only then report `WORKSPACE_SYNCED`; the restored Git workspace, not the downloaded artifact itself, becomes the synchronized development baseline.

Do not treat synchronization as Skill packaging or installation. If the synchronized repository contains a Skill and the user asks to install/update it, validate/package that Skill as a separate next stage and report deployment state independently. Do not fall back from this verified local-to-web path to direct GitHub archive URLs, IDrive/Dropbox URLs, model-carried Base64, or per-file reconstruction merely because artifact synchronization fails.

## Transfer boundary rule

Distinguish file location from tool control. Remote Desktop Commander operates the user's authorized remote host filesystem (macOS or Windows); a file that exists only in ChatGPT's conversation/sandbox storage is not automatically a Mac-local file. Likewise, a local-host artifact is not automatically installed into ChatGPT.

The verified Web-mode Drive `upload_file(file_uri=...)` path is a real binary bridge from the current ChatGPT workspace to staging when its prerequisites are present; do not claim the boundary is missing in that case. For an ordinary Web -> Mac/local file request, this Drive staging -> RDC path is the default transport. The user's request to move/save/copy/deliver that file is sufficient intent to choose the Drive data plane and to authorize the narrow downstream `rdc_transfer`; do not ask for a second transfer/data-plane/computer-use confirmation. Read `web-to-local-handoff.md` and preserve destination-path/host permission gates, exact size/SHA-256 verification, exact-object cleanup, and Web workspace authority. If the configured staging boundary is public-read, do not use it for secrets or content that cannot tolerate temporary link-readable exposure.

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

When a user asks to move a ChatGPT-only artifact to the local host, use the verified Drive staging -> RDC path by default when available and do not ask for a second data-plane authorization. For the reverse local-host -> ChatGPT direction, use the shortest verified host-supported binary path that actually exists; do not assume symmetry. Never immediately start encoding or chunking. If no verified path is available, surface the transfer blocker rather than inventing a fallback.
