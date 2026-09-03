# Skill distribution and deployment provenance

Skill source publication, package construction, consumer installation, and maintainer provenance are separate concerns. `references/deployment-manifest.json` is build-generated and must not be committed to the source repository.

## Two distribution profiles

### Consumer (default)

Ordinary installable Codex Loop packages use schema v2 with no repository identity:

```json
{
  "schema_version": 2,
  "skill_name": "codex-loop",
  "distribution": {
    "profile": "consumer",
    "repository_binding": "none"
  },
  "bundle": {
    "profile": "chatgpt-runtime",
    "file_count": 72,
    "manifest_sha256": "..."
  }
}
```

A consumer package must not contain `source.repository`, `source.commit`, or `source.tree`. Installing it never means that the user has selected, connected, forked, or authorized the maintainer repository or any other repository. The bundle manifest proves installed runtime-byte integrity only.

Build the consumer artifact from the current validated runtime working tree:

```bash
python3 tools/build_skill_zip.py --source REPO --output skill.zip
```

This is the normal artifact returned to end users. Because a consumer package is repository-neutral, it cannot be used by itself to infer a canonical repository or to prove that an installed copy is the latest GitHub revision.

### Maintainer (explicit)

Use the maintainer profile only when exact repository lineage is itself required evidence:

```json
{
  "schema_version": 2,
  "skill_name": "codex-loop",
  "distribution": {
    "profile": "maintainer",
    "repository_binding": "provenance_only"
  },
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

Build it only from a clean tracked Git source whose HEAD and tree exactly match the supplied evidence:

```bash
python3 tools/build_skill_zip.py --source REPO --output skill.zip \
  --distribution-profile maintainer \
  --source-repository OWNER/REPO \
  --source-commit FULL_COMMIT \
  --source-tree FULL_TREE
```

`repository_binding: provenance_only` means “this maintainer artifact came from this exact source,” not “the installing user must bind this repository.” Never convert provenance into user authorization, repository selection, or connector setup.

## Compatibility and verification

The verifier accepts legacy schema-v1 provenance packages so existing maintainer installations remain inspectable. Legacy repository fields are treated as provenance only, never as a consumer repository binding.

After unpack/install, verify bundle integrity with:

```bash
python3 scripts/codex_loop.py deployment-provenance-verify --skill-root PATH_TO_INSTALLED_SKILL
```

For a consumer package, verification proves only runtime file count/hash. For a maintainer package, it additionally exposes source provenance. A maintainer installed-Skill bootstrap still requires a fresh target-branch observation and exact commit/tree equality; package provenance alone is never enough to claim freshness.

The manifest must never carry host-private values such as user names, local paths, Drive IDs, OAuth/session material, task/conversation IDs, or Host Profile contents. Package SHA-256 remains external receipt evidence because embedding it inside the ZIP would create self-reference.
