# V7.4.4 Scope Lock

## In scope

- V7.4.4-00 through V7.4.4-08 from the V1.0 candidate-closure plan.
- Production fixes, migrations, behavior tests, browser acceptance tests, and
  a repository-tracked reproducible local evidence bundle.

## Out of scope

- New product features, V7.6 work, final report or defense material,
  deployment, mobile work, and performance expansion.
- Creating the formal `v1.0.0` tag. That requires a later independent audit
  with no P0 or P1 blockers.

## Evidence discipline

Tests must execute production paths. After `tested_sha` is captured for
V7.4.4-08, only the evidence bundle and execution-state document may change
before `release_head` is verified against the allowlist.
