# V7.4.4 V1.0 Candidate Closure Audit Baseline

Baseline commit: `9af524e9e1c7ff149256170931cf7fc9d766858e`.

This round starts from an explicitly unclosed state. The V7.4.3 local closure
claim is not accepted as V7.4.4 evidence because the declared manifest,
verification result, and raw command logs are not all available as tracked,
reviewable repository artifacts at the claimed commit.

V7.4.4 is limited to the following blockers from the candidate-closure plan:

1. closure evidence is not independently reproducible;
2. protected-term split direction is incorrect;
3. long table headers can fall back to the first source block;
4. the production mock cannot satisfy a pure multiple-choice contract;
5. submitted quizzes are omitted from plan deletion history;
6. unscheduled diff items do not have stable identities;
7. knowledge-point status vocabulary and stale target rebinding diverge; and
8. browser assertions and evidence are incomplete.

The expected output is `v1.0.0-rc1`, never an automatic `v1.0.0` release.
Remote CI remains deferred to V7.6.
