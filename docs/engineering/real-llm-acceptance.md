# Real LLM acceptance gate

`scripts/verify_real_llm_acceptance.py` is a manual, secret-safe release gate.
It is deliberately independent from the repeatable mock CI.  It creates a
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

The script registers an isolated user with the test credentials `test` / 
`test1234` semantics, but adds a unique suffix so concurrent runs cannot
collide. It never accesses a regular user database or stored configuration.

## Strict success criteria

Every audited agent execution must report `meta_observed=true`, a non-mock
actual provider, a non-empty actual model identity, `fallback_used=false`, and
`degraded=false`. A connection
failure, timeout, non-JSON provider response, schema-invalid answer, or any
fallback causes a non-zero exit code. The six covered paths are config
connection, knowledge points, grounded chat, quiz plus weak point, learning
plan, and material overview. The knowledge-point path requires at least two
source-bound points; a structurally weak first real response receives exactly
one same-model repair request, never a rule-generated replacement. The chat
path requires an out-of-scope answer to have no citations and explicitly state
insufficient evidence. The plan path requires at least one task bound to the
fixture material and course.

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

Run the command twice against the same code SHA before claiming the real-model
gate is complete. Do not create an RC tag until both runs, standard CI, and the
Windows smoke evidence have passed.

## R5 local evidence

The R5 C1 SHA `d3425ecce8ad81984ca1d46187291baeac1ce81c` passed the standard
closure check (22/22) and two isolated runs: `r5-c1-a9` and `r5-c1-b`. Each
recorded 6/6 scenarios, five observed real-model calls, zero mock/fallback/
degraded/missing-meta counts, and a passed local secret scan. These ignored
local artifacts are evidence indexes only; they contain no credential values.
