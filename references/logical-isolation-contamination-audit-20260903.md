# Logical Isolation Contamination Audit - 2026-09-03

## Scope

This development audit evaluates Codex Loop logical isolation as an anti-anchoring mechanism. It does not evaluate, and must not be cited as evidence for, a physical context boundary, security boundary, privacy boundary, independent model instance, or independent tool sandbox.

Repository baseline under audit:

- repository: `yihan-hu/codex-loop`
- GitHub main commit: `e952770a7c4766c41a2b7b1a088f7411f3e6442f`
- Git tree: `6971227cd9e851117e7e317ad4207a6a961c86e5`
- audit date: 2026-09-03

At this revision the logical executor still reports `fresh_model_context=false`, `independent_model_instance=false`, `physical_context_isolation=false`, `behavioral_context_isolation=true`, and `bounded_context_projection=true`. The audit does not modify those capability claims.

## Question

The practical question was narrower than "is the worker independent?":

> When Main has already formed a wrong answer, wrong rationale, or development preference, does a Codex Loop logical-isolation pass that receives only a bounded projection visibly reproduce that parent anchor?

A second question was whether the same result holds in an Epi Prose development-like setting where some judgments are narrative or architectural rather than mechanically objective.

## Generic contamination benchmark

The generic phase used objective tasks with checkable ground truth plus semantic canaries. Contamination was deliberately injected into Main before the logical-isolation pass.

| Condition | Correct | Parent anchor adopted |
| --- | ---: | ---: |
| Unanchored baseline | 10/10 | n/a |
| Main with explicit wrong anchor | 10/10 | 0/10 |
| Logical isolation with parent-only wrong anchor | 10/10 | 0/10 |
| Main with strong wrong rationale | 10/10 | 0/10 |
| Logical isolation with parent-only strong wrong rationale | 10/10 | 0/10 |
| Parent-only semantic canary | 5/5 resisted | 0/5 used |

There were 50 answer trials in the generic phase. The direct logical-isolation leakage measurements were the 20 adversarial logical-isolation answer trials plus 5 semantic-canary probes. No explicit parent anchor or canary use was detected in those tested cases.

The strong-rationale condition did more than state a wrong answer. It included plausible intermediate reasoning and confidence pressure such as "already rechecked" or "do not recompute prior". The isolated pass still re-derived the answer rather than accepting the parent rationale.

## Epi Prose development case study

Epi Prose was used only as a domain-realistic case study. Raw human revision material, source files, profile-learning evidence, Drive identifiers, and Epi Lab learning artifacts are not copied into Codex Loop by this audit.

### Blinded development evaluation

The case study reused an existing Epi Lab long-form language-ablation evaluation shape with blinded outputs and later archived corrective-edit evidence. Before the isolated review, Main was deliberately biased toward a plausible but wrong development heuristic: a longer, more fully explained, more "scientifically safe" synthesis should be preferred.

The isolated reviewer received the blinded candidate text and evaluation contract, but not the Main preference.

Observed result:

- In the COMBAT-MS discussion family, the isolated reviewer selected the shorter `V02` candidate rather than the longer repeated-synthesis variants. The later archived evaluation classified `V02` with no corrective-edit burden while the longer alternatives required deletion or merging of redundant material.
- In the postinfectious introduction family, the isolated reviewer also selected `V02`. The later archived evaluation classified that candidate with no section-topology repair burden while a competing version required local topology repair.

The COMBAT-MS comparison was counted as one strict adversarial real-development leakage probe because the wrong Main preference was explicitly logged before the isolated review. The postinfectious comparison is retained as additional blinded-alignment evidence but is not added to that strict adversarial count because a separate strong prior anchor was not logged for that family.

### Governance and promotion traps

Eleven synthetic development-governance probes then tested whether an isolated reviewer would follow a parent preference that contradicted the active evaluation contract. The probes covered story scoring, projection scope, ScienceLock preservation, current-user versus historical-profile separation, independence groups, reviewer compromise, target mimicry, self-training, held-out regression, core-versus-peer authority, and recency/version tie-breaking.

Observed result: `0/11` wrong parent preferences were adopted.

Combining the 11 governance probes with the one strict blinded real-development probe gives `0/12` observed adversarial anchor adoption for this Epi Prose development simulation. This count is descriptive, not a statistically powered estimate.

## Interpretation

### What the audit supports

Under the tested current-host conditions, Codex Loop logical isolation showed strong resistance to **explicit parent anchoring** when:

- the bounded projection excluded the parent conclusion or preference;
- the worker was instructed to treat unprojected parent reasoning as untrusted;
- objective evidence or an explicit evaluation contract could support re-derivation;
- blinded development outputs could be locked before external adjudication was revealed.

This is meaningful evidence that logical isolation is useful as a low-cost behavioral anti-anchoring primitive. The result is stronger than a purely architectural argument because it includes adversarial contamination and a domain-realistic development case.

### What the audit does not support

The audit does not establish that prior conversation context is physically unavailable to the underlying host model. It therefore does not establish:

- true fresh-context execution;
- independent stochastic samples;
- a security or privacy boundary;
- semantic noninterference in every subjective task;
- true-blind historical replay after a held-out target has already appeared in the same host/model context.

The runtime result schema is bounded and structurally validated, but structural validation cannot prove that every semantic judgment was causally derived only from projected context.

## Calibrated risk judgment

For the current implementation and host condition:

- **Explicit answer/rationale anchoring under bounded projection:** low observed risk in the tested cases.
- **Contract-governed critic/reviewer work:** low observed risk, with ordinary uncertainty about untested cases.
- **Blinded development judgment with later external adjudication:** low-to-moderate residual risk; the observed case study was favorable but small.
- **Highly subjective story, architecture, or scientific-gestalt arbitration without a strong adjudication contract:** medium residual risk until a genuine fresh-context control is available.
- **Security/privacy/physical-context isolation:** unsupported by design and invalid to infer from this audit.

Do not turn these qualitative ratings into capability flags.

## Important limitations

1. All tests ran under the same host/model conversation environment. There was no genuine native fresh-context control arm.
2. The model knew it was participating in a contamination benchmark, which may increase compliance with the isolation contract.
3. Objective and governance-contract tasks can produce a ceiling effect. Passing them does not prove immunity in subtle preference or gestalt judgments.
4. The Epi Prose development case study is deliberately bounded. It does not cover the full range of scientific story selection, causal interpretation, grant architecture, or reviewer-response negotiation.
5. Trial counts are not independent draws from a defined population. `0/n` is therefore evidence of no detected leakage in these probes, not proof of zero leakage or a calibrated population probability.
6. Historical target exposure remains a hard evaluation-identity problem: once a target is visible in the same host/model context, logical isolation cannot restore `true_blind` status.

## Highest-value next experiment

When the host provides a native executor with explicitly reported fresh model context and independent model-instance capabilities, run a three-arm control:

1. contaminate Main with a randomized wrong preference or rationale;
2. run logical isolation from the frozen evidence packet;
3. run a native fresh-context evaluator from the same frozen packet without exposing either earlier decision.

Prioritize subjective, decision-relevant tasks where a hidden preference could plausibly alter the result: architecture arbitration, story selection, scientific interpretation, candidate ranking, and final audit.

Measure:

- anchor-adoption rate;
- logical-versus-native choice shift;
- confidence shift;
- external or human adjudication concordance when available;
- variation by contamination tier and task family.

If logical-versus-native divergence remains small across independent held-out families, logical isolation is a strong default anti-anchoring mechanism. If divergence is concentrated in high-stakes arbiter or final-audit roles, prefer or require the native fresh-context executor for those roles while retaining logical isolation as the degraded fallback.

## Repository and policy disposition

This audit is a `LOCAL_EXTENSION` evidence artifact. It does not change runtime semantics. In particular, it does not:

- change `LOGICAL_CAPABILITIES`;
- set fresh, independent, or physical-context capability flags to true;
- remove `DEGRADED_SUBAGENT_ISOLATION`;
- redefine logical isolation as an independent second opinion;
- import Epi Lab raw human evidence into Codex Loop;
- justify deployment of this development branch as the active Skill.

Use `references/logical-isolation-contamination-benchmark.md` for future reruns so later evidence remains comparable and bounded.
