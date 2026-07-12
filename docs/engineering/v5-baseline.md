# V5 Regression Baseline

The V5 baseline is generated, never hand-authored as a passing result. Run:

```powershell
python scripts/verify_function_closure_v5.py --artifact-root artifacts
```

The generated `artifacts/verification/v5-acceptance.json` records the baseline
commit, command, exit code and passed/failed/skipped counters for every gate.
The artifact directory is intentionally ignored so local databases, logs and
real-LLM evidence cannot enter Git history.

Required P0 regression categories are document quality, image integrity,
material deletion, plan closure, knowledge grounding, multi-course scheduling,
retrieval, parse-job recovery and independently-created-browser E2E.
