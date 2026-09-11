# Codex-style change review

Use this only when a separate review is justified by change size, uncertainty, weak tests, or material risk. One review is the default maximum.

This policy is a compact behavioral port of OpenAI Codex's public change-review rubric (`codex-rs/prompts/templates/review/rubric.md`).

Review the actual current changes against the relevant base/commit/request. Report a finding only when all of the following are true:

- it materially affects correctness, performance, security, or maintainability;
- it is discrete and actionable;
- it was introduced by the reviewed change rather than being merely pre-existing;
- the author would realistically fix it if informed;
- the problem does not depend on an unstated assumption;
- affected code or behavior can be identified rather than merely speculated about;
- it is not simply an intentional change.

Ignore trivial style unless it obscures meaning or violates an applicable repository rule. Keep each finding concise and prioritize it by impact. If there is no substantive finding, return no findings and stop; do not create another reviewer to manufacture confidence.

After a real finding is fixed, rerun only the validation plausibly affected by that fix. Escalate beyond one review only for genuinely critical/high-risk work or when the first repair creates new uncertainty.
