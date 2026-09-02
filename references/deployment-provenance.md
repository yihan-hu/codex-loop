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

For a Git working tree, the builder packages the **Git-tracked runtime projection of `HEAD`**, not an arbitrary recursive filesystem snapshot. Untracked files and ignored runtime/cache material are neither part of the package nor part of Git tree identity, so transient `__pycache__`, `.pyc`, scratch files, or other untracked workspace residue cannot force a manual export/repack workaround. The builder still fails closed when any tracked source file is modified/staged relative to `HEAD`, requires the supplied commit to equal the actual `HEAD`, and requires the supplied tree to equal `HEAD^{tree}`. For a non-Git exported source directory, the existing deterministic filesystem-tree verification remains the compatibility path.

The exact commit/tree must already come from verified Git publication/readback; a package builder cannot invent repository lineage. A packaging surprise caused only by untracked/ignored residue is a design regression, not a reason to switch to `git archive` or another ad hoc packaging source.

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

Deployment provenance verification never auto-authorizes an installed Skill as development source. Installed-Skill bootstrap is default-off and requires explicit current-turn user selection under `source-acquisition.md`. If the user expects current/latest, exact manifest commit/tree must equal a fresh target-branch observation; an explicitly accepted older revision may be labeled `historical_explicitly_accepted`. The installed directory always remains read-only deployment state.

The manifest schema cannot carry host-private values such as user names, local paths, Drive IDs, OAuth/session information, task/conversation IDs, or Host Profile contents.
