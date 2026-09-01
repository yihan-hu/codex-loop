# Skill deployment provenance

Skill source publication, package construction, and ChatGPT deployment are separate evidence stages. Every installable Codex Loop ZIP now carries a build-generated, non-sensitive provenance file at:

```text
codex-loop/references/deployment-manifest.json
```

That file is **not committed to the repository**. The builder rejects a source tree that already contains it.

## Manifest

```json
{
  "schema_version": 1,
  "skill_name": "codex-loop",
  "source": {
    "repository": "OWNER/REPO",
    "commit": "FULL_40_HEX",
    "tree": "FULL_40_HEX"
  },
  "bundle": {
    "profile": "chatgpt-runtime",
    "file_count": 72,
    "manifest_sha256": "..."
  }
}
```

`manifest_sha256` binds the deterministic runtime allowlist as canonical path/size/SHA-256 entries. The package SHA-256 is calculated **outside** the ZIP and belongs in the release/deployment receipt; putting it inside the ZIP would create self-reference.

The builder verifies that the full Web/local source tree hashes to the supplied Git tree before packaging. The exact commit/tree must already come from verified Git publication/readback; a package builder cannot invent repository lineage.

Example:

```bash
python3 tools/build_skill_zip.py --source REPO --output skill.zip \
  --source-repository OWNER/REPO \
  --source-commit FULL_COMMIT \
  --source-tree FULL_TREE
```

After unpack/install, verify bundle integrity with:

```bash
python3 scripts/codex_loop.py deployment-provenance-verify --skill-root PATH_TO_INSTALLED_SKILL
```

A verified installed-Skill bootstrap still requires a fresh GitHub target-branch observation. Only when the installed bundle manifest verifies and its exact commit/tree match the intended current remote revision may it bootstrap a fresh mutable workspace. The installed directory itself remains read-only deployment state.

The manifest schema cannot carry host-private values such as user names, local paths, Drive IDs, OAuth/session information, task/conversation IDs, or Host Profile contents.
