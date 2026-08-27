# Skill source, release, deployment, and transfer boundaries

Keep development location, source lineage, workspace synchronization, and ChatGPT installation state separate. Use this reference whenever a task asks to install/update a Skill, asks whether local changes synchronize into ChatGPT, or moves an artifact between the current ChatGPT workspace and the local host.

## Development modes

- **A new conversation starts in web mode.** The current ChatGPT/web workspace is the mutable source baseline. Make edits and validations there and return generated files with normal workspace download links. Do not enter Local mode or use Remote Desktop Commander merely because those capabilities are available.
- **Local mode is explicit once per conversation.** Enter it when the user asks for local/PiWork/Remote Desktop Commander development or an equivalent persistent-Mac workflow and the conversation has not already entered local mode. Once selected, keep local mode for later repository tasks in that same conversation unless the user explicitly switches back to web mode. In local mode `LOCAL_ROOT/<repo>` is the authoritative mutable source workspace and GitHub is its durable remote.
- **`LOCAL_ROOT` is user-specific configuration.** Resolve it as the absolute RDC-authorized persistent development root using `local-mode-setup.md`; never substitute an author-specific home-directory path. If it is unresolved or unauthorized, fail closed before local filesystem access.
- A generic `push` request does not silently convert a conversation that is still in web mode into local mode. If the only verified publish path requires Local mode, preserve the web result and surface that requirement instead of migrating source without authorization.
- **Conversation reset.** A new conversation starts in web mode again; local-mode state does not persist across conversations.
- `skill.zip` is a release/install artifact, not a development baseline in either mode. The installed ChatGPT Skill is a deployed copy and never becomes source-of-truth merely because installation succeeded.

## Stage separation

Use these conceptual flows:

```text
Web mode (default at conversation start)
  current ChatGPT workspace
  -> edit / validate / review
  -> return downloadable files/links
  -> if this is a Skill and installation is requested: validate/package skill.zip
  -> explicit ChatGPT install/update action

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

- `SOURCE_PUSHED`: GitHub remote commit/tree matches the audited local commit/tree.
- `WORKSPACE_SYNCED`: the exact pushed commit was materialized into the current ChatGPT workspace through the verified Actions-artifact path and passed integrity checks.
- `SKILL_PACKAGED`: a verified `skill.zip` exists for that commit.
- `DEPLOY_PENDING`: the release artifact exists but the installed ChatGPT Skill has not been explicitly updated.
- `DEPLOYED`: an explicit supported install/update action or user confirmation shows that the intended Skill release is installed.

These are reporting labels, not extra runtime state commands. Never report `DEPLOYED` from Git push or packaging evidence alone.

## Local post-push workspace synchronization

This path applies when the current conversation is in local mode and a native-Git push has been verified by remote commit/tree readback. After that success, generate a deterministic offer:

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
