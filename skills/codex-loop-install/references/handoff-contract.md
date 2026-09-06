# Codex Loop installer handoff contract

Accept one JSON object with exactly these fields:

```json
{
  "version": 1,
  "installer_skill": "codex-loop-install",
  "skill_name": "codex-loop",
  "repository": "yihan-hu/codex-loop",
  "source_state": "SOURCE_PUSHED",
  "deployment_target": "chatgpt_web_skill",
  "source_commit": "<40 lowercase hex>",
  "source_tree": "<40 lowercase hex>",
  "package_sha256": "<64 lowercase hex>"
}
```

The handoff is install authority only for the exact package whose SHA-256 matches `package_sha256` and whose bundled deployment manifest binds the same repository, commit, and tree.

Reject missing or extra fields, weak/short identities, a consumer/unbound package, a package rooted at any Skill name other than `codex-loop`, or any mismatch between the handoff and `references/deployment-manifest.json` inside the ZIP.

A successful validation authorizes only the host-native install/update submission. It is not evidence that the UI was surfaced successfully, that the host accepted the package, or that the intended revision became active. Codex Loop performs later-turn reconciliation and completion.
