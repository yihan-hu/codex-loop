# Skill Deployment Provenance

A packaged Codex Loop Skill may contain `references/deployment-manifest.json`, generated at build time and never committed as source. It binds the installable runtime file manifest to an exact GitHub repository, full commit SHA, and tree SHA.

The embedded manifest contains only non-sensitive source/bundle provenance: repository, commit, tree, bundle profile, file count, and a deterministic SHA-256 over the runtime file list `(path,size,sha256)`. It must not contain user names, local paths, Drive IDs, OAuth/session data, task/conversation IDs, or Host Profile state.

The ZIP package SHA-256 remains external release/deployment receipt evidence to avoid self-reference. Installed-Skill bootstrap may trust provenance only after the embedded file-manifest digest verifies and the declared commit/tree matches a current GitHub observation under the normal source-acquisition policy.
