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
- derive requirements again from the authoritative user request and referenced current specifications/instructions;
- identify authoritative evidence for every explicit requirement, numbered item, named artifact, command, test, gate, invariant, and deliverable;
- match verification scope to requirement scope;
- treat uncertain, indirect, incomplete, or missing evidence as not achieved;
- never use intent, partial progress, memory, or a plausible final answer as proof of completion.

## Thin host adapter

The ChatGPT Skill host does not expose Codex's `update_goal` primitive. Codex Loop therefore keeps the upstream completion semantics but records the audit in its private task runtime with `objective-audit` and requires a fresh passing audit before `completion` may return `PASS` for newly CLI-bootstrapped tasks.

The audit is bound to `effective_request_sha256` plus the current workspace generation. The effective request is the immutable request anchor plus ordered user steers. A later steer changes that request hash, and a later workspace mutation changes generation, so either makes prior completion evidence stale. Rewriting a working objective summary does not alter request authority.

Working bootstrap criteria remain execution aids and do not replace the upstream-style objective audit.

## Coding-precision semantics observed upstream

The completion resource above remains the exact vendored normative resource. Separately, the precision behavior in this release was spot-checked against public Codex `main` at `33bdf976ccd1130823d4fe041e4d5075ab511d67` on 2026-09-11; this targeted observation does not advance the repository-wide frozen source-map audit pin.

- `codex-rs/protocol/src/protocol.rs` blob `81d799b61578e5e8140b7ecf90079b38b8ee501b` explicitly marks model-visible user requests with `USER_MESSAGE_BEGIN = "## My request for Codex:"`. Codex Loop adapts that retained-request authority to the ChatGPT host as a task-private immutable, privacy-scrubbed `request_anchor`; ordered later user steers extend the effective request rather than rewriting the anchor.
- `codex-rs/protocol/src/plan_tool.rs` blob `affb4c1896b604356984fa0e1202178e961c8bbb` defines plan steps with `pending`, `in_progress`, and `completed` status. The Codex base instructions require exactly one `in_progress` plan step while work remains. Codex Loop ports only the useful working-memory invariant: one current `in_progress` focus, with optional non-goals and expected change surface, rather than cloning the full plan/tool runtime.
- `codex-rs/protocol/src/prompts/base_instructions/default.md` blob `907ff8b877026871b088f01f4366cea36e1f02cd` instructs existing-code work to be surgical/minimal, not to fix unrelated bugs or broken tests, to use patch-style editing, and to validate from the most specific changed behavior toward broader checks. Codex Loop adopts those behavioral rules directly while leaving actual host patch/sandbox/tool authority with ChatGPT or the active execution host.

`expected_change_surface` and `scope_drift` are Codex Loop local extensions. They make the existing deterministic change tracker useful as an attention signal, but they do not create a new mutation gate or substitute for semantic diff review.

## Intentionally not emulated

Do not invent local equivalents for upstream host primitives merely to imitate their names. In particular, this adaptation does not add a domain-workflow dependency registry, domain-specific completion handshake, automatic goal continuation, Codex token-budget accounting, or `update_goal` emulation when the ChatGPT host does not expose equivalent authority.

When an objective names another Skill or workflow, Codex Loop remains domain-agnostic: the audit may require authoritative evidence that the named workflow reached its required end state, but Codex Loop does not duplicate or interpret that workflow's internal semantics.
