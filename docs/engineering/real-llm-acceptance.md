# Real LLM acceptance gate

`scripts/verify_real_llm_acceptance.py` is a manual, secret-safe release gate.
It is deliberately independent from the repeatable mock CI. It creates a
temporary SQLite database, uploads and parsed directories, starts only its own
API and parse-worker processes, then removes that runtime state at completion.

## Run it locally

Set the provider credentials in the process environment; never pass the key on
the command line or add it to a `.env` file committed to Git.

```powershell
$env:REAL_LLM_API_KEY = "set-this-in-your-shell-only"
$env:REAL_LLM_BASE_URL = "https://provider.example/v1"
$env:REAL_LLM_MODEL = "your-model"

& .\backend\.venv\Scripts\python.exe scripts\verify_real_llm_acceptance.py `
  --provider openai-compatible `
  --artifact-root artifacts/verification/real-llm `
  --run-id "real-llm-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"

Remove-Item Env:REAL_LLM_API_KEY
```

The script registers an isolated user with unique test credentials so concurrent
runs cannot collide. It never accesses a regular user database or stored
configuration.

## Strict success criteria

Every audited agent execution must explicitly persist `meta_observed=true`, a
non-mock actual provider, a non-empty actual model identity,
`fallback_used=false`, and `status=success`. The harness must use those exact
stored values: it may not infer observation from provider/model fields and may
not coerce a missing fallback value into `false`.

A connection failure, timeout, non-JSON provider response, schema-invalid
answer, incomplete audit metadata, or any fallback causes a non-zero exit code.
The six covered paths are config connection, knowledge points, grounded chat,
quiz plus weak point, learning plan, and material overview.

The knowledge-point path requires at least two source-bound points; a
structurally weak first real response receives exactly one same-model repair
request, never a rule-generated replacement. The repair prompt is course
generic and must not embed concepts from the acceptance fixture.

The chat path requires an out-of-scope response to have `not_found=true`, no
citations, an explicit insufficient-evidence statement, and no appended uncited
technical explanation. The plan path requires at least one `learn` task whose
resolved material target is the fixture material, and all returned tasks must
belong to the selected course.

Each run writes the following under
`artifacts/verification/real-llm/<run-id>/`:

- `real-llm-acceptance.json` — machine-readable status and counts.
- `scenario-results.json` and `redacted-agent-runs.json` — compact evidence.
- `environment-fingerprint.json` and `request-summary.json` — reproducibility
  data without credentials.
- redacted backend and worker logs.

Only the provider, scheme/host, model, statuses and timings are retained. API
keys, authorization headers, response bodies and fallback text are redacted.
Artifacts are first written to a temporary directory, then recursively scanned
for raw, URL-encoded, JSON-escaped, and common header/assignment secret forms.
Only a passed scan is atomically moved into the final artifact directory. The
summary records `secret_scan.files_scanned`, `patterns_checked`, and `matches`;
it also records observed-meta, repair, and LLM-call counters.

Run the command twice against the same frozen code SHA before claiming the
real-model gate is complete. The two runs must retain independently verifiable
redacted summaries or manifests, including artifact hashes. Do not create an RC
tag until both runs, the standard regression suite, and required release gates
have passed.

## R5 evidence status

The earlier R5 state named C1 SHA
`d3425ecce8ad81984ca1d46187291baeac1ce81c` and runs `r5-c1-a9` and
`r5-c1-b`. R6 audit found that the previous harness could infer
`meta_observed=true`, coerce a missing `fallback_used` value into `false`, and
did not retain independently verifiable run manifests in the repository.
Those run names are therefore historical claims only and are not current RC3
release evidence. A fresh same-SHA two-run gate is required after R6 regression
verification.

## R6 local evidence

The R6 code-freeze SHA is `7b7401b74833fb5fe0e187b396135fdf1c82399d`.
Runs `r6-c1-a` and `r6-c1-b` each passed all six scenarios with zero fallback,
mock, degraded, and missing-metadata counts. Their compact, redacted evidence
bundles are committed under `docs/engineering/evidence/r6/` and are checked by
`scripts/verify_real_llm_evidence.py --compact`. This is local verification
only; remote CI remains required before release approval.
