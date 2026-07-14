# V7.5.3 Scope: RC3 Audit Closure

> Only fix code and test-gate defects found by the independent audit of commit `b7facf8b891468010d88cf171497934763a12b77`.
> Final coursework reports, presentation material, remote CI, and V1.1 features remain out of scope.

- Audit baseline: `b7facf8b891468010d88cf171497934763a12b77`
- Branch: `codex/v7-5-3-rc3-audit-closure`
- Target candidate after executable local verification: `v1.0.0-rc4`
- Current status: `in_progress`

## P0 blockers

1. **e2e_real_service_reuse** — Local Playwright runs can reuse an already-running normal backend, worker, or frontend.
2. **e2e_non_unique_environment** — E2E inherits ordinary database settings and uses shared database/upload paths.
3. **page_asset_recovery_outside_lock** — Journal recovery happens before the rebuild lock is acquired.
4. **page_asset_recovery_db_fs_ambiguity** — Crash recovery decides from directory existence instead of database/file manifests.
5. **page_asset_lock_ownership** — Rebuild locks have no owner token or heartbeat and can be stolen or released by another request.
6. **missing_executed_e2e_evidence** — RC state is not bound to an executed release gate, current HEAD, teardown result, and six passing E2E paths.

## P1 closure items

1. Migrate or quarantine `MaterialImage.material_version_id IS NULL` rows and exclude unresolved rows from the active view.
2. Replace skippable E2E checks with six non-skippable user-path gates.
3. Use real embedded raster images and the full parse/reparse path in versioned-image tests.
4. Add per-page retry and complete Object URL lifecycle management to `PageCanvas.vue`.

## Deferred to V1.1

- Remote GitHub Actions CI and unified Windows/Linux evidence runners.
- Historical-version page-asset browser.
- bbox highlighting, region selection, and ultra-large PDF virtualization.
- Unrelated dependency upgrades and UI refactors.

## Closure rule

`verified_locally` is forbidden until a clean committed SHA has a machine-readable release-gate result proving backend tests, frontend unit/type checking/build, six E2E paths, teardown cleanup, and unchanged normal uploads. Code added in V7.5.3 must remain `in_progress` until an execution agent produces that evidence.