# V7.5.3 Agent Execution and RC4 Closure Plan

> This document starts after the V7.5.3 code implementation. Tasks V7.5.3-00 through V7.5.3-07 are present on the branch but have **not** been executed in a local Python/Node/Playwright environment. The agent must verify them without weakening any gate.

## 1. Fixed scope

- Repository: `dddd2024/course-learning-agent`
- Branch: `codex/v7-5-3-rc3-audit-closure`
- Audit baseline: `b7facf8b891468010d88cf171497934763a12b77`
- Target only after evidence passes: `v1.0.0-rc4`
- Current state must remain: `in_progress`
- Current task: `V7.5.3-08`

Do not merge unrelated changes, rewrite the branch history, lower integrity checks, reuse a normal backend/database/upload directory, or mark the state verified before the release gate passes.

## 2. Checkout and preflight

```powershell
git fetch origin
git switch codex/v7-5-3-rc3-audit-closure
git pull --ff-only

git rev-parse HEAD
git status --short
git diff --stat b7facf8b891468010d88cf171497934763a12b77..HEAD
```

Required before testing:

- The branch is exactly `codex/v7-5-3-rc3-audit-closure`.
- The worktree is clean.
- `docs/engineering/v7-execution-state.json` says `in_progress`.
- Do not edit the execution state merely to make its tests pass.

## 3. Targeted backend verification

Run from `backend`:

```powershell
python -m pytest app/tests/test_v7_5_3_execution_state.py -q
python -m pytest app/tests/test_v7_5_3_e2e_guard.py app/tests/test_v7_5_3_e2e_config_contract.py -q
python -m pytest app/tests/test_v7_5_3_page_asset_recovery.py app/tests/test_v7_5_3_page_asset_prepromotion.py -q
python -m pytest app/tests/test_v7_5_3_legacy_image_migration.py app/tests/test_v7_5_3_active_image_view.py -q
python -m pytest app/tests/test_v7_5_3_versioned_image_parse.py -q
```

The page-asset tests must prove all of the following:

- Journal recovery occurs only after acquiring the material/version lock.
- A different owner token cannot release another request's lock.
- A live heartbeat is not treated as stale.
- A crash before the old directory is renamed keeps the old directory byte-for-byte.
- A pre-commit crash restores the verified old manifest.
- A post-commit crash keeps the verified new manifest.
- An ambiguous DB/filesystem state returns `recovery_required` and preserves evidence.

If a recovery test fails, do not replace manifest comparison with directory-existence heuristics and do not delete backup/journal evidence to make the test pass.

## 4. Frontend unit and static verification

Run from `frontend`:

```powershell
npm run test -- PageCanvas.spec.ts
npm run type-check
npm run build
```

Verify that `PageCanvas`:

- retries a failed page independently;
- reloads when the same page ID receives a different URL or SHA-256;
- ignores stale in-flight responses;
- revokes URLs when pages disappear and when the component unmounts;
- does not hide other pages when one page fails.

If selectors or component timing fail, fix the implementation or test harness. Do not remove retry, URL-revocation, or source-change assertions.

## 5. Isolated six-path Playwright gate

Run from `frontend`:

```powershell
npx playwright test tests/e2e/v7-5-3-user-paths.spec.ts
```

If Chromium is not installed, install only the browser runtime and rerun:

```powershell
npx playwright install chromium
```

Exactly six tests must pass with zero failed, flaky, or skipped tests:

1. PDF upload -> decoded original page -> structured chunks -> visible answer and citation.
2. Real `kp_source_chunk_ids` across multiple materials -> best matching material selected -> its page decoded.
3. Delete -> Material/Version/Page/PageAsset/Image/Chunk/FTS/files all absent -> same-name re-upload works.
4. Ready legacy PDF with page assets removed -> real frontend repair button -> complete decoded page preview.
5. Non-PDF material -> structured-text radio actually checked -> content visible -> no page canvas.
6. Scanned PDF with zero chunks -> complete original-page preview -> no blocking unreadable alert.

Mandatory isolation checks:

- `reuseExistingServer` must remain `false` for backend, worker, and frontend.
- The run uses `storage/e2e-runs/<runId>/e2e.db` and `uploads` under the same run root.
- It never inherits the normal development `DATABASE_URL` or `storage/uploads`.
- `frontend/test-results/e2e-runtime/<runId>/teardown-result.json` reports:
  - `passed: true`
  - `normal_uploads_unchanged: true`
  - `cleanup_passed: true`
- Failure traces, screenshots, and videos must be retained and inspected.

Do not add `if (isVisible())`, conditional skips, broader selectors that can match unrelated elements, or API-200-only acceptance.

## 6. Legacy image migration check on a database copy

Before touching user data, copy the SQLite database to a temporary location. Point `DATABASE_URL` at the copy and keep a second backup.

Run from the repository root:

```powershell
python scripts/migrate_v7_5_3_images.py
```

Required result:

```json
{
  "bound_from_chunk": 0,
  "bound_single_version": 0,
  "quarantined": 0,
  "remaining_null_ready": 0
}
```

The first three counts depend on existing data and may be nonzero. `remaining_null_ready` must be zero. Inspect quarantined rows before applying the migration to the real development database. Do not assign ambiguous rows to the active version merely to eliminate NULL values.

## 7. Fix loop

When any targeted test fails:

1. Preserve the full error, trace, screenshot, and relevant database/filesystem state.
2. Identify whether the defect is production code, test fixture, environment, or selector.
3. Fix the actual defect without lowering the acceptance condition.
4. Run the smallest failing test.
5. Run all affected V7.5.3 tests.
6. Commit the fix.
7. Return to a clean worktree before the release gate.

Every fix commit must describe the actual failure. Do not record manual inspection as a test result.

## 8. Full clean-SHA release gate

After all targeted checks pass and all fixes are committed:

```powershell
git status --short
python scripts/run_v7_5_3_release_gate.py
```

The script runs:

- full backend pytest;
- every `test_v7_5_3_*.py` backend test;
- all frontend unit tests;
- frontend type-check;
- frontend build;
- the six V7.5.3 Playwright paths.

The generated `release-gate-result.json` must show:

```json
{
  "head_unchanged": true,
  "dirty_before": false,
  "dirty_after": false,
  "e2e": {
    "passed": 6,
    "failed": 0,
    "flaky": 0,
    "skipped": 0
  },
  "teardown": {
    "passed": true,
    "normal_uploads_unchanged": true,
    "cleanup_passed": true
  },
  "passed": true
}
```

Also verify:

- `tested_sha == final_sha`;
- every step exit code is zero;
- stdout/stderr files exist;
- the sibling `.sha256` matches the result file.

A failed gate must not produce RC4 state closure. Fix, commit, and run the complete gate again on the new clean SHA.

## 9. Evidence-only closure commit

A committed evidence file necessarily changes HEAD after the tested code SHA. The state contract permits exactly one evidence-only closure commit.

After a successful gate on code SHA `A`:

1. Update `docs/engineering/v7-execution-state.json`:
   - all tasks `status: done`;
   - every `tests_run` entry is a structured object with `command` and `exit_code: 0`;
   - `overall_status: verified_locally`;
   - `current_task: null`;
   - `local_closure: V7.5.3_AUDIT_BLOCKERS_CLOSED_LOCALLY`;
   - `release_candidate: v1.0.0-rc4`;
   - `audit_blockers: []`;
   - `closure_evidence` contains:

```json
{
  "result_path": "artifacts/v7-5-3-local/<runId>/release-gate-result.json",
  "sha256": "<actual SHA-256>",
  "closure_mode": "evidence_only_commit"
}
```

2. Force-add only the successful run directory and the execution state:

```powershell
git add docs/engineering/v7-execution-state.json
git add -f artifacts/v7-5-3-local/<runId>
git diff --cached --name-only
```

3. The staged paths must contain only:
   - `docs/engineering/v7-execution-state.json`
   - `artifacts/v7-5-3-local/<runId>/...`

4. Commit:

```powershell
git commit -m "chore(v7.5.3-08): close RC4 with executable local evidence"
```

5. After the closure commit, run:

```powershell
cd backend
python -m pytest app/tests/test_v7_5_3_execution_state.py -q
```

The state test verifies that the closure commit's parent is the tested SHA and that no production or test code changed in the post-test commit. Do not amend code into the evidence-only commit.

## 10. Push and final response

```powershell
git push -u origin codex/v7-5-3-rc3-audit-closure
```

Return all of the following:

1. Final branch and HEAD.
2. Tested code SHA and evidence-only closure SHA.
3. `git diff --stat b7facf8b891468010d88cf171497934763a12b77..HEAD`.
4. Backend full-suite counts.
5. V7.5.3 targeted counts.
6. Frontend unit/type-check/build results.
7. Six Playwright results individually.
8. E2E run ID, database path, upload path, teardown result, and normal-upload snapshot result.
9. Migration-copy output and quarantined-row review.
10. Evidence result path and SHA-256.
11. Any remaining failure, uncertainty, or deferred item.

## 11. Stop conditions

Stop RC closure and report rather than bypassing the gate if:

- a normal backend or normal database is reused;
- normal `storage/uploads` changes;
- any recovery path returns `recovery_required`;
- a test passes only after weakening an assertion;
- any of the six E2E paths is failed, flaky, or skipped;
- teardown cannot delete the isolated run directory;
- the worktree is dirty before or after the gate;
- the evidence SHA does not match;
- the closure commit contains code changes;
- the tested SHA is not the closure commit's direct parent.
