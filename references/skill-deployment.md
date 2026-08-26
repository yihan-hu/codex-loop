# Skill source, release, deployment, and transfer boundaries

Keep development lineage and ChatGPT installation state separate. Use this reference whenever a task asks to install/update a Skill, asks whether local changes synchronize into ChatGPT, or requires moving a release artifact across the ChatGPT/PiWork boundary.

## Four distinct roles

1. `/Users/yihanhu/PiWork/<repo>` is the authoritative mutable source workspace. Make edits, tests, commits, and release planning there.
2. GitHub is the durable Git remote. Publish source only with native Git from the canonical PiWork repository and verify the remote commit/tree after push.
3. `skill.zip` is a release artifact built from an audited committed Git HEAD. It is not a development baseline and does not update an installed Skill by itself.
4. The installed ChatGPT Skill is a deployed copy. Do not treat it as source of truth, and do not assume it automatically follows PiWork or GitHub unless a supported synchronization mechanism has been explicitly observed.

## Stage separation

Use this conceptual flow:

```text
PiWork canonical repo
  -> edit / validate / review
  -> git commit
  -> native git push + remote readback
  -> package audited HEAD as skill.zip
  -> explicit ChatGPT install/update action
```

Report the stages independently. A useful user-facing status vocabulary is:

- `SOURCE_PUSHED`: GitHub remote commit/tree matches the audited PiWork commit/tree.
- `SKILL_PACKAGED`: a verified `skill.zip` exists for that commit.
- `DEPLOY_PENDING`: the release artifact exists but the installed ChatGPT Skill has not been explicitly updated.
- `DEPLOYED`: an explicit supported install/update action or user confirmation shows that the intended Skill release is installed.

These are reporting labels, not extra runtime state commands. Never report `DEPLOYED` from Git push or packaging evidence alone.

## Transfer boundary rule

Distinguish file location from tool control. Remote Desktop Commander operates the user's remote Mac filesystem; a file that exists only in ChatGPT's conversation/sandbox storage is not automatically a Mac-local file. Likewise, a PiWork artifact is not automatically installed into ChatGPT.

When no verified binary transfer bridge exists between the current source and destination:

- Stop before reconstructing the file through the model.
- State where the real bytes currently live and where they need to go.
- State that the available tools do not provide a verified direct binary bridge for that boundary.
- Ask the user to place the real file at an authorized PiWork path, use an actually supported file-transfer mechanism, or explicitly authorize a specific alternate data plane.
- Do not default to chunked text, base64, heredocs, repeated `write_file` calls, connector-created blobs, GitHub contents/object API payloads, or archive-content relay.

If the user explicitly authorizes an alternate transfer method, scope that authorization to the named transfer, preserve checksums when practical, verify the destination bytes/tree before treating the transfer as successful, and never promote a transferred artifact into the canonical source baseline.

For an explicitly authorized model-carried transfer, use `references/verified-model-relay.md`: try `GUARDED_SINGLE_SHOT_RELAY` before chunking, treat prefix/suffix guards as sacrificial framing, normalize only ASCII whitespace inside the Base64 interval, and require exact decoded size plus full SHA-256 before publishing the destination. A failed single-shot attempt may surface `VERIFIED_CHUNK_RELAY` as fallback; never heuristically repair unknown interior corruption.

## Similar-problem user guidance

When a user asks why a local repo change is not visible in ChatGPT, explain the source/release/deployment separation before trying tools. Tell them that Git push updates GitHub, packaging creates the installable release artifact, and the installed ChatGPT Skill still requires an explicit supported deployment step unless a real synchronization mechanism is available.

When a user asks to move a ChatGPT-only artifact into PiWork (or a PiWork-only artifact into ChatGPT), do not immediately start encoding or chunking it. Explain the transfer boundary first and offer the shortest verified path. If no verified path is available, surface `DEPLOY_PENDING` or the transfer blocker rather than inventing a fallback.
