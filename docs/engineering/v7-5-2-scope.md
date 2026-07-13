# V7.5.2 Scope: V1.0 RC Blocker Fix

> Only fix code-level release blockers found in the independent audit.
> No final report, no new features.

- Audit baseline: `fd5198b63e25b869b3a31fb0e7178b9c02f3c294`
- Branch: `codex/v7-5-2-rc-blocker-fix`
- Target: `v1.0.0-rc3`

## P0 blockers (must fix before RC3)

1. **new_version_image_binding** — Re-parsing may write new images to the old version or rewrite historical image paths.
2. **page_asset_expected_page_coverage** — Page asset completeness uses record count instead of actual page-number set, misjudging missing pages as complete.
3. **page_asset_db_fs_compensation** — Page asset rebuild lacks compensation transaction; failures can corrupt the old readable version.
4. **e2e_environment_isolation** — Playwright may reuse the normal backend/database/uploads, polluting real data.

## P1 issues (fix in this round)

5. Six E2E user-path tests have weak assertions that don't prove the target path truly works.
6. Corrupted page images, NULL-version images, and single-page load failures are not handled.

## Deferred to V1.1

- Remote CI and cross Windows/Linux unified evidence scripts.
- Historical version page-asset browser UI.
- bbox search highlight, region selection questioning.
- Ultra-large PDF virtual scrolling and advanced thumbnails.
- Dependency upgrade and deprecation-warning cleanup.
