---
name: codex-loop-install
description: "Fixed installer companion for Codex Loop. Use only when the user explicitly invokes codex-loop-install or when an active Codex Loop self-update handoff explicitly names codex-loop-install as the terminal installer. Validate the exact yihan-hu/codex-loop source commit/tree and provenance-bound production package, then own the host Skill install/update surface for codex-loop. Never choose a revision, modify source, publish code, install arbitrary Skills, or update codex-loop-install itself."
---

# Codex Loop Install

Act only as the fixed terminal installer for `codex-loop`. Do not perform Codex Loop development, source publication, repository mutation, or general Skill installation.

## Accepted entry conditions

Proceed only when at least one of these is true:

1. The user explicitly asks to use `codex-loop-install` to install/update Codex Loop.
2. An active Codex Loop self-update handoff explicitly names `codex-loop-install` as the terminal installer and supplies the structured handoff defined in `references/handoff-contract.md`.

Reject implicit or unrelated installation requests. Never install a Skill whose name is not exactly `codex-loop`, and never install from a repository other than `yihan-hu/codex-loop`.

## Installation workflow

1. Require a real local `skill.zip` (or equivalent host file reference materialized to a local path) plus the structured handoff.
2. Run `scripts/validate_handoff.py --handoff HANDOFF_JSON --package SKILL_ZIP`.
3. Require `status=PASS`. Treat any mismatch in repository, Skill name, source state, deployment target, commit, tree, package SHA-256, ZIP root, or deployment manifest as a hard stop.
4. Invoke the host/Skill Creator native install-or-update surface for the verified `codex-loop` package. Do not reconstruct or rewrite the package.
5. Make the host install/update invocation the final current-turn installation action. Do not continue Codex Loop lifecycle bookkeeping in the same terminal install turn.
6. On a later host/user turn, Codex Loop—not this installer—must verify that the intended production revision is actually active before deployment is marked complete.

## Ownership boundaries

- Treat the handoff as authority to install exactly the bound `codex-loop` package, not as authority to modify GitHub, Drive, source files, or other Skills.
- Never choose a newer commit, rebuild from `main`, substitute another ZIP, or infer missing provenance.
- Never update or reinstall `codex-loop-install` while it is acting as terminal installer. Installer maintenance is owned by `codex-loop` as a separate deployment.
- Never mark deployment complete merely because the install/update UI appeared or accepted the package. Activation evidence belongs to the later Codex Loop reconciliation turn.
- Do not generate per-update bridge Skills. A legacy bridge may exist only as an explicit recovery mechanism outside the normal path.

## Resources

- `references/handoff-contract.md`: exact self-update handoff schema and state boundary.
- `scripts/validate_handoff.py`: deterministic package and provenance validator. Run it before every install/update action.
