# V7.5.2 R6 audit fixes applied directly

This note records only the fixes already applied on
`codex/v7-5-2-r6-audit-fixes`. It is not the next Agent execution plan.

## Implemented

- The real-LLM harness now consumes exact persisted `meta_observed` and
  `fallback_used` values. It no longer derives observation from provider/model
  identity and no longer converts `None` to `False`.
- REAL-03 now requires `not_found=true`, no citations, an insufficient-evidence
  statement, and a bounded refusal body.
- REAL-05 now requires an actual `learn` task resolved to the current material,
  rejects foreign-course tasks, and rejects foreign material targets.
- The production outline-repair prompt is course generic; data-link-layer
  fixture concepts no longer appear in the shared prompt.
- RC3 state has been reopened as `in_progress`; the previous R5 run names are
  retained only as superseded historical claims.
- Focused regression tests were added for strict metadata handling and for
  preventing fixture-specific repair instructions.

## Not claimed

- No full backend/frontend/Playwright regression was run in this change set.
- No new real-provider run was executed.
- No reproducible two-run evidence manifest was produced.
- No RC3 tag or release is authorized.
