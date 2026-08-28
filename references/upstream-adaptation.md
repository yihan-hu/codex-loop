# Upstream Codex goal adaptation

Codex Loop adopts the completion-audit semantics from the public OpenAI Codex goal continuation template before adding local policy.

## Exact upstream resource

- Repository: `openai/codex`
- Upstream path: `codex-rs/ext/goal/templates/goals/continuation.md`
- Observed upstream `main`: `2008d27e98d7b46170d2d464b36dbf97008611b8`
- Exact file Git blob SHA-1: `62391c523cab01022a32c6bb685292ed1e8d3205`
- Local exact copy: `references/upstream-codex-goal-continuation.md`
- License: Apache License 2.0, as already carried by this repository

Verify the local copy with `git hash-object references/upstream-codex-goal-continuation.md`; it must equal the blob above.

## Directly adopted semantics

Use the upstream `Completion audit` section as the normative completion rule:

- treat completion as unproven before the audit;
- derive requirements again from the original objective and referenced current specifications/instructions;
- identify authoritative evidence for every explicit requirement, numbered item, named artifact, command, test, gate, invariant, and deliverable;
- match verification scope to requirement scope;
- treat uncertain, indirect, incomplete, or missing evidence as not achieved;
- never use intent, partial progress, memory, or a plausible final answer as proof of completion.

## Thin host adapter

The ChatGPT Skill host does not expose Codex's `update_goal` primitive. Codex Loop therefore keeps the upstream completion semantics but records the audit in its private task runtime with `objective-audit` and requires a fresh passing audit before `completion` may return `PASS` for newly CLI-bootstrapped tasks.

The audit is bound to the stored objective, current workspace generation, and current `plan_revision`. Workspace mutation or a later user steer therefore makes prior objective-completion evidence stale.

Working bootstrap criteria remain execution aids and do not replace the upstream-style objective audit.

## Intentionally not emulated

Do not invent local equivalents for upstream host primitives merely to imitate their names. In particular, this adaptation does not add a domain-workflow dependency registry, domain-specific completion handshake, automatic goal continuation, Codex token-budget accounting, or `update_goal` emulation when the ChatGPT host does not expose equivalent authority.

When an objective names another Skill or workflow, Codex Loop remains domain-agnostic: the audit may require authoritative evidence that the named workflow reached its required end state, but Codex Loop does not duplicate or interpret that workflow's internal semantics.
