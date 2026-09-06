---
name: codex-loop-install
description: "Fixed installer companion for Codex Loop. Use when the user asks to install, update, or reinstall Codex Loop in ChatGPT Web, or when an active Codex Loop self-update handoff names codex-loop-install as the terminal installer. Validate the exact yihan-hu/codex-loop source commit/tree and provenance-bound production package, then present that exact package through the host-native Skill update surface. Never choose a revision, modify source, publish code, install arbitrary Skills, repackage the canonical production ZIP, or update codex-loop-install itself."
---

# Codex Loop Install

Act only as the fixed terminal installer for `codex-loop`. This Skill permanently replaces the disposable bridge's post-save executor stage. Do not perform Codex Loop development, source publication, repository mutation, or general Skill installation.

## Accepted entry conditions

Proceed only when both the target is exactly `codex-loop` and one of these routing conditions is true:

1. The user asks to install, update, or reinstall Codex Loop in ChatGPT Web. This exact Codex Loop installation intent may route here implicitly.
2. An active Codex Loop self-update handoff explicitly names `codex-loop-install` as the terminal installer and supplies the structured handoff defined in `references/handoff-contract.md`.

Implicit routing is narrow, not authorization. A generic request to install another Skill must not route here. Never install a Skill whose name is not exactly `codex-loop`, and never install from a repository other than `yihan-hu/codex-loop`.

## Installation workflow

1. Require a real local canonical production `skill.zip` (or equivalent host file reference materialized to a local path) plus the structured handoff.
2. Run `scripts/validate_handoff.py --handoff HANDOFF_JSON --package SKILL_ZIP`.
3. Require `status=PASS`. Treat any mismatch in repository, Skill name, source state, deployment target, commit, tree, package SHA-256, ZIP root, or deployment manifest as a hard stop.
4. After validation passes, execute the same terminal contract as the user-verified bridge executor: **When explicitly invoked, require the already-validated canonical `codex-loop` `skill.zip` from the current conversation, present that exact package through the host-native Skill update surface, and end the turn immediately. Do not invoke Codex Loop and do not edit, repackage, rename, or substitute the canonical package.**
5. The host-native Skill update surface is the installation action. Do not substitute a sandbox/download link, a normal attachment-only response, assistant prose telling the user to install the ZIP, or a claim that UI was surfaced. Do not run a Skill Creator repackaging flow on the canonical production ZIP; its SHA-256 is part of the handoff authority.
6. Make the host-native update-surface invocation the only remaining installation action in the terminal turn. After initiating it, emit no further Codex Loop lifecycle commands or post-install bookkeeping in that turn.
7. On a later host/user turn, Codex Loop—not this installer—must verify that the intended production revision is actually active before deployment is marked complete.

## Ownership boundaries

- Treat the handoff as authority to install exactly the bound `codex-loop` package, not as authority to modify GitHub, Drive, source files, or other Skills.
- Never choose a newer commit, rebuild from `main`, substitute another ZIP, or infer missing provenance.
- Never update or reinstall `codex-loop-install` while it is acting as terminal installer. Installer maintenance is owned by `codex-loop` as a separate deployment.
- Never mark deployment complete merely because the install/update UI appeared or accepted the package. Activation evidence belongs to the later Codex Loop reconciliation turn.
- Do not generate per-update bridge Skills. A legacy bridge may exist only as an explicit recovery mechanism outside the normal path.

## Resources

- `references/handoff-contract.md`: exact self-update handoff schema, routing scope, and state boundary.
- `scripts/validate_handoff.py`: deterministic package and provenance validator. Run it before every install/update action.
