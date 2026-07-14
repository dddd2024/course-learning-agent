# V7.5.2 R4 scope: real LLM acceptance and RC3 closure

R4 starts from merged `main` at `9552c2ecd5f0b70c9be6a61eb02958ea4becfe2a`
on `codex/v7-5-2-r4-real-llm-rc3-closure`. PR #10 closed the R3 and P2
code-contract findings. The former R2 records are historical and marked
`superseded`; they must not remain false active pending work.

The release remains `in_progress` and `release_candidate=null` until all of
the following are recorded against one tested code SHA:

- Backend full pytest, frontend unit/type/build, migration, Playwright, and
  standard V7 acceptance pass without failures or skips.
- The isolated real-provider harness passes all six paths twice with zero
  mock, fallback, and degraded counts.
- The manual real-LLM workflow has retained redacted evidence and no secret
  scan finding.
- The Windows launcher smoke succeeds on the actual Windows environment.
- The final C2 state-only closure commit has successful remote CI.

Only after those gates and explicit user approval may the repository create
the `v1.0.0-rc3` tag.

The R4 release blockers are `real_llm_acceptance_harness`,
`real_llm_core_user_paths`, `real_llm_no_mock_fallback_proof`,
`windows_launcher_smoke`, and `rc3_evidence_transaction`.

The production fallback policy remains unchanged: a normal user may fall back
from personal configuration to system configuration or mock. The R4 harness is
the separate strict gate that rejects those outcomes. It reads keys only from
its process environment, writes only redacted evidence, and never reads a
developer database.

Deferred to V1.1: cross-Windows/Linux unified evidence, historical page asset
browser, bbox search highlight, and advanced document layout.
