# V7.5.2 R5 scope: real LLM acceptance hardening and RC3 closure

R5 starts from merged `main` at `a07b9332ac0a11ef53bd4e9081b845c1073da445`
on `codex/v7-5-2-r5-real-llm-hardening`. It keeps R4's isolated real-provider
harness while making its observed metadata, one-pass outline repair, secret
scan, and grounding assertions independently verifiable.

The release remains `in_progress` and `release_candidate=null` until all of
the following are recorded against one tested code SHA:

- Backend full pytest, frontend unit/type/build, migration, Playwright, and
  standard V7 acceptance pass without failures or skips.
- The isolated real-provider harness passes all six paths twice with zero
  mock, fallback, degraded, and missing-observed-meta counts, and with a real
  local artifact secret scan passed.
- The manual real-LLM workflow has retained redacted evidence and no secret
  scan finding.
- The Windows launcher is recorded only as user manual verification; R5 does
  not modify launcher scripts or desktop shortcut automation.
- The final C2 state-only closure commit has successful remote CI.

Only after those gates and explicit user approval may the repository create
the `v1.0.0-rc3` tag.

The R5 release blockers are `real_llm_acceptance_harness`,
`real_llm_core_user_paths`, `real_llm_no_mock_fallback_proof`, and
`rc3_evidence_transaction`.

The production fallback policy remains unchanged: a normal user may fall back
from personal configuration to system configuration or mock. The R5 harness is
the separate strict gate that rejects those outcomes. It reads keys only from
its process environment, writes only redacted evidence, and never reads a
developer database.

Deferred to V1.1: cross-Windows/Linux unified evidence, historical page asset
browser, bbox search highlight, and advanced document layout.
