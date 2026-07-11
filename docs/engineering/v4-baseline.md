# V4 functional-closure baseline

Baseline commit: `66fc110e29442473ab9d04af4c01a90918af02d7`.

The V4 gate is intentionally behavioral: it runs migration, backend, frontend, and E2E commands and writes command-level exit codes to `artifacts/verification/v4-baseline.json`. A non-zero command exit or a critical skipped suite is a failed acceptance result.
