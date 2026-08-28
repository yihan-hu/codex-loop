# Source acquisition and bootstrap policy

Use this reference whenever Codex Loop must establish a new mutable workspace from GitHub source or from an installed Skill. Source acquisition happens **before** ordinary development; publication and deployment are separate stages.

## Invariants

- Resolve `workspace_mode` first. A source-transfer problem never silently selects Local mode.
- The destination development workspace must be fresh and becomes the only mutable source authority after successful acquisition.
- Transport objects (Actions ZIPs, tarballs, release packages, staging folders) are evidence/data plane, not later development baselines.
- Never edit a host-installed Skill directory in place.
- Never infer success or failure from a tool's inability to observe an event it does not support.

## GitHub -> Web workspace: required path

When the user asks to pull, open, refresh, or synchronize repository source **from GitHub** into the current Web workspace, use this path:

```text
observe exact repository + target branch/commit
  -> audited .github/workflows/workspace-download.yml
  -> workflow run whose head_sha == exact target commit
  -> source artifact from that exact run
  -> GitHub Connector download_workflow_artifact
  -> verify artifact ZIP digest when GitHub provides it
  -> read the same job log and obtain the git-archive SHA-256
  -> extract the downloaded artifact ZIP
  -> verify the contained source tarball SHA-256
  -> safely extract into a fresh Web workspace
  -> bind subsequent development to that workspace
```

The standard workflow should package `git archive HEAD`, log its SHA-256, upload a `<repo-name>-source` artifact, and support both branch pushes and `workflow_dispatch` so a capable host can request a fresh artifact without changing repository source.

Do not substitute any of the following as the ordinary Web acquisition path:

- container or shell `git clone`/`git pull`;
- GitHub Connector per-file contents/blob/tree reconstruction;
- generic GitHub archive/download URLs chosen outside the commit-bound workflow;
- model-carried text/Base64 source relay;
- an installed Skill copy when the user explicitly asked for GitHub source.

If the exact commit has no usable download run, dispatch the audited workflow when the host exposes a workflow-dispatch capability and then verify the resulting `head_sha`. If the host cannot dispatch or observe a suitable run, stop with a precise acquisition blocker. Do not mutate repository source merely to manufacture a different commit whose artifact is easier to observe.

Useful fail-precise classifications are descriptive, not additional runtime state:

- `WORKSPACE_DOWNLOAD_WORKFLOW_MISSING`: the audited download workflow is absent.
- `WORKSPACE_DOWNLOAD_TRIGGER_UNAVAILABLE`: no exact-commit run exists and the host cannot request one.
- `WORKSPACE_DOWNLOAD_OBSERVABILITY_UNAVAILABLE`: the workflow may exist/run, but the available query surface cannot observe the relevant event/run.
- `WORKSPACE_DOWNLOAD_ARTIFACT_UNAVAILABLE`: the exact run exists but its expected artifact cannot be retrieved.
- `WORKSPACE_DOWNLOAD_INTEGRITY_FAILED`: ZIP digest, archive size, or source tarball SHA-256 does not match.

An empty result from a connector action that only supports a different trigger class is `...OBSERVABILITY_UNAVAILABLE`, not proof that the workflow never ran.

## Verified-latest installed Skill bootstrap

An installed Skill is normally deployment state. Codex Loop may use it as a **one-time bootstrap source** only when all of the following hold:

1. The intended canonical repository and target branch are known.
2. The target branch's current remote HEAD is observed as a full 40-hex commit.
3. The installed copy is proven to represent that exact commit. Acceptable proof is either:
   - host/deployment evidence or a deployment receipt explicitly bound to the same repository + full commit; or
   - an audited full source/package manifest proving content equivalence to that exact revision.
4. The freshness evidence is current at the moment of bootstrap. A version string, filename, modification timestamp, install date, or spot-check of a few files is insufficient.
5. The installed directory is treated as read-only. Copy it into a fresh development workspace before the first mutation.
6. Record the bootstrap provenance: source kind `installed_skill`, repository, target branch, exact commit, and the evidence that proved freshness/content identity.
7. After the copy, bind the task to the new workspace and never return to the installed directory as a competing source authority.

If any freshness/provenance condition is missing, do not call the installed copy “latest.” Use the verified GitHub -> Web path when the requested source is GitHub, or report the missing proof when no verified acquisition path is available.

This exception does not make arbitrary copied source directories valid. `final`/`publish` folders, release staging, downloaded artifacts, unpacked release packages, and unverified installed Skills remain non-authoritative.

## Interaction with Local mode

The installed-Skill bootstrap exception does not bypass Local-mode authorization. If the installed Skill lives on a user's Mac or another RDC-backed host, Local mode and current-task filesystem authorization must already permit reading that installed directory and writing the destination workspace. The copied workspace must live inside the authorized development boundary. Do not use access to an installed Skill to infer permission for sibling repositories or broader filesystem discovery.

## Completion evidence

Before treating source acquisition as complete, retain enough evidence to answer:

- Which repository and exact revision were intended?
- Which acquisition method was used (`github_actions_artifact` or `installed_skill_bootstrap`)?
- What proved the source bytes belonged to that revision?
- What integrity checks passed?
- Which fresh workspace became the sole mutable baseline?

A later publication still follows the normal Web or Local publish contract; acquisition evidence does not replace publish/readback evidence.
