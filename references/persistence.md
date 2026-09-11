# Optional cross-conversation persistence

Persistence exists only to recover a long task after conversation loss. It is not a second workflow engine and is off by default.

## State-only resume manifest

`persistence-export --backend google_drive` writes a small private manifest containing only facts worth carrying across conversations:

- immutable request anchor;
- ordered user steers;
- concise working objective;
- acceptance text;
- optional `pending / in_progress / completed` plan;
- repository commit/tree identity when available;
- hashed lineage for consequential unresolved external actions;
- whether validation existed historically.

It must not contain chain of thought, hidden instructions, credentials, cookies, approval/session tokens, raw tool transcripts, environment secrets, or raw external-action identities.

```bash
python3 scripts/codex_loop.py persistence-export --cwd REPO \
  --backend google_drive --output /PRIVATE/TEMP/state-only.json
```

The current schema is v4. Older schemas are intentionally not accepted by this direct-upgrade runtime; recover the original request from an authoritative source and start a fresh task instead of maintaining migration logic.

## Resume

A later conversation validates the manifest, asks the host to re-observe current repository/external reality, then creates a fresh task from the durable facts:

```bash
python3 scripts/codex_loop.py persistence-validate --manifest state-only.json
python3 scripts/codex_loop.py persistence-resume-plan --manifest state-only.json
python3 scripts/codex_loop.py persistence-resume --cwd REPO \
  --manifest state-only.json --observations-json observations.json
```

Current reality wins. Previous validation is historical, not proof about a changed workspace. Plan steps and user steers are recovered as working memory; the model inspects the actual state before continuing.

## Workspace Cache

Use Workspace Cache only when the user explicitly needs uncommitted Web workspace state to survive conversation loss. It remains a separate immutable Git/worktree capsule with bounded cleanup. See `persistence-resume.md` for restore ordering and `repository-continuity.md` for HOT/WARM/COLD source recovery.

A disconnected Drive connector is not a correctness failure unless cross-conversation recovery is itself an explicit requirement.
