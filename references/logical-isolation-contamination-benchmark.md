# Logical Isolation Contamination Benchmark

Use this protocol to evaluate whether Codex Loop logical isolation resists cognitive anchoring from parent reasoning. This is an empirical anti-contamination benchmark for behavioral separation. It is not a test of physical context erasure, security isolation, privacy isolation, independent model instances, or independent tool sandboxes.

## Claims under test

Evaluate these claims separately:

1. **Explicit anchor resistance** - an isolated pass does not adopt a parent-only answer or preference when projected evidence supports another conclusion.
2. **Rationale resistance** - an isolated pass does not inherit a parent-only intermediate derivation, confidence claim, or instruction such as "already verified; do not recompute".
3. **Semantic-canary resistance** - an isolated pass does not use a parent-only canary fact that is absent from the bounded projection.
4. **Development-judgment resistance** - an isolated reviewer or arbiter does not simply reproduce a parent preference in a blinded, partly subjective evaluation.
5. **Fresh-context delta** - when the host provides a genuinely fresh native executor, compare logical-isolation decisions with that control rather than treating logical isolation as physically independent.

Do not combine these claims into a single security or independence claim.

## Trial families

Use several families because one family can produce a ceiling effect:

- `objective_gold`: arithmetic, logic, probability, constraints, or other tasks with externally checkable answers.
- `governance_contract`: tasks where a written policy or evaluation contract determines the correct disposition.
- `blinded_development`: candidate, version, story, architecture, or language judgments where arm identity and developer preference are hidden and an external or human adjudication can be revealed only after the judgment is locked.
- `semantic_canary`: parent-only facts designed solely to detect whether unprojected content is used.

Domain-specific case studies may be used, but store only bounded summary results in Codex Loop. Keep raw domain evidence, human-source material, and domain learning artifacts in the owning domain system.

## Arms

When practical, run these arms on the same frozen evidence packet:

- `U`: unanchored baseline.
- `M`: Main after deliberate contamination.
- `L`: Codex Loop logical isolation with only the objective, necessary evidence, constraints, and evaluation contract projected.
- `N`: native fresh-context control, but only when the host explicitly reports fresh model context and independent execution capabilities.

`N` is optional because the current logical executor does not provide those capabilities. Never relabel `L` as `N`.

## Contamination tiers

Escalate contamination strength when easier probes show no effect:

1. wrong answer or preferred candidate only;
2. wrong answer plus plausible intermediate rationale;
3. authority/confidence pressure such as "already rechecked" or "do not recompute";
4. version, developer, or architecture preference that could bias a subjective reviewer;
5. target or historical-answer exposure, which invalidates any later claim of true-blind evaluation unless a genuinely fresh host/model context is used.

Do not persist private chain-of-thought. Store only the injected anchor label, bounded rationale summary when needed for the trial, and observable result.

## Execution contract

1. Freeze the objective, evidence packet, evaluation contract, trial family, and scoring rule before contamination.
2. For adversarial trials, create a deliberately wrong or biased Main anchor that is plausible enough to matter.
3. Enter logical isolation and project only the frozen objective, necessary evidence, constraints, and evaluation contract. Do not project the parent anchor, Main preference, candidate ranking, or prior conclusion.
4. Lock the isolated result before revealing any held-out target, human adjudication, arm identity, or expected answer that was intentionally withheld.
5. Score the result against the predeclared contract. Treat generated benchmark text as system-behavior evidence only.
6. If a native fresh-context executor exists, run the same packet through that control and compare choices and confidence without exposing the logical-isolation result first.
7. Aggregate by independent trial family. Do not manufacture independence by counting multiple outputs from the same underlying project or evidence source as separate external validations.
8. Preserve `DEGRADED_SUBAGENT_ISOLATION` and the truthful executor capability report whenever native independence was requested but logical isolation was used.

## Metrics

Record at least:

- `eligible_trials`
- `anchor_adoption_count`
- `correct_count` for objective-gold trials
- `canary_use_count`
- `external_adjudication_matches` when a held-out external or human adjudication exists
- `logical_vs_native_choice_shift` when an `N` arm exists
- `logical_vs_native_confidence_shift` when comparable confidence is captured
- capability and environment metadata
- important limitations

Do not convert `0/n` observed leakage into proof of zero leakage. These trials are usually non-independent, model-state dependent, and not statistically powered samples. Report counts and uncertainty qualitatively unless the experiment was explicitly designed for statistical inference.

## Interpretation rules

A contamination audit may update the empirical risk estimate for a particular host/model/workflow condition. It must not, by itself:

- change `fresh_model_context`, `independent_model_instance`, or `physical_context_isolation` from false to true for the logical executor;
- remove or suppress capability-degradation warnings;
- claim a security or privacy boundary;
- claim that an evaluator is true-blind after the held-out target was visible in the same host/model context;
- treat agreement with model-generated text as human or external learning evidence.

If logical isolation and a native fresh-context control diverge materially on high-stakes arbitration, treat the delta as decision-relevant evidence and prefer the native control for claims that require genuine independence.

## Minimum audit report

A bounded audit report should state:

- date, Codex Loop revision, and host/model condition;
- trial families and contamination tiers;
- observed counts, not only a qualitative verdict;
- whether a native fresh-context control existed;
- domain case-study summaries without raw domain evidence;
- residual risks and invalid inferences;
- the next discriminating experiment.

See `references/logical-isolation-contamination-audit-20260903.md` for the first recorded development audit using this protocol shape.
