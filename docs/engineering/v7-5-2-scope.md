# V7.5.2 Scope: V1.0 RC Blocker Recovery

> Only fix code-level release blockers and acceptance failures found by the independent audit and the complete regression gate.
> No final report and no unrelated feature expansion.

## Audit recovery supersession

The previous local closure is invalidated by the legacy condition where page
assets are complete but active-version `MaterialPage` rows are absent.  The
recovery branch must keep the state `in_progress` until page catalogue,
existing-database migration, scanned-PDF classification, Blob lifecycle and
remote CI evidence are all verified on the final commit.

- Audit baseline: `fd5198b63e25b869b3a31fb0e7178b9c02f3c294`
- Current integration branch: `main`
- Target after all gates pass: `v1.0.0-rc3`
- Current status: `in_progress`

## Verified regression facts

GitHub Actions PR #6, run #96, was executed against the recovery branch.

Passed gates:

- Backend full pytest.
- Frontend unit tests.
- Frontend type-check.
- Frontend production build.
- Migration dry-run and smoke test.

Failed or incomplete gates:

- Playwright E2E: **47 passed, 27 failed, 2 did not run**.
- V7 acceptance verification: **not run**, because it depends on Playwright success.

Therefore `verified_locally`, `V7.5.2_RC_BLOCKERS_CLOSED_LOCALLY`, and `v1.0.0-rc3` are not valid current-state claims.

## Implemented code blockers

The following production-code blockers have implementations and backend regression coverage, but remain subject to final browser acceptance:

1. **new_version_image_binding** — New extracted images bind to the target material version and do not rewrite historical versions.
2. **page_asset_expected_page_coverage** — Page completeness is calculated against the expected page-number set.
3. **page_asset_db_fs_compensation** — Page-asset rebuild uses recoverable database/filesystem compensation.

## Active release blockers

1. **e2e_environment_isolation** — The release gate still needs per-run database/upload paths, no existing-server reuse, setup/teardown cleanup, and normal-upload snapshot protection.
2. **e2e_user_path_acceptance** — Multiple real user paths still fail their final visible-state assertions, including knowledge-point navigation, deletion cleanup, document repair, non-PDF structured text, and scanned-PDF page preview.
3. **v7_acceptance_verification** — Acceptance has not run successfully on a clean committed SHA.

## Current execution order

```text
V7.5.2-04 E2E environment isolation
  -> V7.5.2-05 real user-path acceptance
  -> V7.5.2-06 damaged/legacy/single-page edge cases
  -> V7.5.2-07 tested RC3 closure
```

## Closure requirements

The state may return to `verified_locally` only when all of the following are true on one clean committed SHA:

- Backend full pytest passes.
- Frontend unit tests pass.
- Frontend type-check passes.
- Frontend production build passes.
- Migration dry-run and smoke test pass.
- Playwright E2E reports zero failed and zero skipped/not-run tests.
- V7 acceptance verification passes.
- `audit_blockers` is empty.
- Every completed task contains non-empty test evidence.

## Deferred to V1.1

- Cross-Windows/Linux unified evidence scripts.
- Historical version page-asset browser UI.
- bbox search highlight and region-selection questioning.
- Ultra-large PDF virtual scrolling and advanced thumbnails.
- Dependency upgrade and deprecation-warning cleanup.
