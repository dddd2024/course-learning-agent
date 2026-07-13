# V7.5.1 Scope: V1.0 User-Path Closure

> Only fix document-learning issues that affect real users. Non-critical
> engineering polish is deferred to V1.1.

- Audit baseline: `4eae324ff28fa66b45da0fd587e6f51d078edd9d`
- Branch: `codex/v7-5-1-v1-user-path-closure`
- Target: `v1.0.0-rc2`

## V1.0 must-fix items

1. Existing PDFs upgraded without page images — re-parse may still skip generation.
2. Scanned / image-only PDFs have empty chunks → cannot enter original-page reader.
3. Page images complete but still falsely reports many standalone images missing.
4. Non-PDF materials default to unavailable original-page mode.
5. Knowledge-point jump branch does not load the corresponding material page images.
6. Deleting a material does not clean page-asset records; re-extraction may write the wrong version or delete historical images.
7. E2E upload directory shares `storage/uploads` with real data — risk of polluting actual data.

## Deferred to V1.1

- Cross Windows/Linux unified evidence scripts and remote CI.
- Complete Playwright HTML reports, evidence-file whitelist hardening.
- Historical version page-asset browser and historical standalone image management UI.
- PDF search-result bbox highlight, region selection questioning, complex multi-column reading-order optimization.
- Advanced thumbnails, continuous zoom, virtual scrolling, ultra-large PDF performance optimization.
- Pillow, Element Plus deprecation-warning cleanup.
