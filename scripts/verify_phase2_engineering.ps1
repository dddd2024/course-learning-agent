# Phase 2 Engineering Bugfix Acceptance Script
# Verifies: backend tests pass, frontend builds, no subjective-metric UI
# residue, algorithmic-art removed, and re-parse failure preserves old chunks.
#
# Usage:  pwsh ./scripts/verify_phase2_engineering.ps1
param([switch]$SkipBackend)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$failed = $false

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Bad($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red; $script:failed = $true }

# 1. Backend tests
if (-not $SkipBackend) {
  Write-Step 'Backend pytest'
  Push-Location "$root\backend"
  & ".\.venv\Scripts\python.exe" -m pytest app/tests/ -q
  if ($LASTEXITCODE -eq 0) { Write-Ok 'backend tests passed' } else { Write-Bad 'backend tests failed' }
  Pop-Location
}

# 1b. T1-1: 指定关键测试文件运行（不只做字符串检查）
if (-not $SkipBackend) {
  Write-Step 'Key backend test files'
  Push-Location "$root\backend"
  & ".\.venv\Scripts\python.exe" -m pytest `
      app/tests/test_multi_plans.py `
      app/tests/test_api_contracts.py `
      app/tests/test_e2e_learning_flow.py `
      app/tests/test_health.py `
      -q
  if ($LASTEXITCODE -eq 0) { Write-Ok 'key backend test files passed' } else { Write-Bad 'key backend test files failed' }
  Pop-Location
}

# 2. Frontend build
Write-Step 'Frontend build'
Push-Location "$root\frontend"
npm run build 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Ok 'frontend build passed' } else { Write-Bad 'frontend build failed' }
Pop-Location

# 3. No subjective-metric UI residue in frontend src
Write-Step 'Subjective metric UI residue check'
$src = "$root\frontend\src"
# T01 fix: -SimpleMatch treats the whole pipe-delimited string as one literal,
# so the four terms were never matched independently. Use regex alternation.
$matches = Get-ChildItem -Path $src -Recurse -File |
  Select-String -Pattern '可靠性|相关度|confidencePercent|命中率'
if ($matches) {
  $matches | ForEach-Object { Write-Bad "$($_.Path):$($_.LineNumber): $($_.Line.Trim())" }
} else {
  Write-Ok 'no subjective metric UI residue'
}

# 4. algorithmic-art removed
Write-Step 'algorithmic-art removal check'
if (Test-Path "$root\algorithmic-art") {
  Write-Bad 'algorithmic-art/ directory still exists'
} else {
  Write-Ok 'algorithmic-art/ removed'
}

# 5. Re-parse failure preserves old chunks (backend test exists)
Write-Step 'Re-parse failure old-result visibility test'
Push-Location "$root\backend"
& ".\.venv\Scripts\python.exe" -m pytest app/tests/test_parse.py::test_parse_scanner_failure_rolls_back_and_preserves_old_chunks app/tests/test_parse.py::test_parse_failure_without_old_chunks_still_failed -q
if ($LASTEXITCODE -eq 0) { Write-Ok 're-parse failure tests passed' } else { Write-Bad 're-parse failure tests failed' }
Pop-Location

# 6. CI workflow_dispatch trigger present
Write-Step 'CI workflow_dispatch trigger check'
$ci = Get-Content "$root\.github\workflows\ci.yml" -Raw
if ($ci -match 'workflow_dispatch') { Write-Ok 'CI workflow_dispatch present' } else { Write-Bad 'CI workflow_dispatch missing' }

# 7. T09: production hardening checks
Write-Step 'Production hardening check'
$mainPy = Get-Content "$root\backend\app\main.py" -Raw
$configPy = Get-Content "$root\backend\app\core\config.py" -Raw

# main.py must NOT hardcode allow_origins=["*"]
if ($mainPy -match 'allow_origins=\["\*"\]') {
  Write-Bad 'main.py still hardcodes allow_origins=["*"]'
} else {
  Write-Ok 'main.py uses config-driven CORS origins'
}

# config.py must define ENVIRONMENT, CORS_ORIGINS, validate_prod_secrets
if ($configPy -match 'ENVIRONMENT' -and $configPy -match 'CORS_ORIGINS' -and $configPy -match 'def validate_prod_secrets') {
  Write-Ok 'config.py defines ENVIRONMENT/CORS_ORIGINS/validate_prod_secrets'
} else {
  Write-Bad 'config.py missing ENVIRONMENT/CORS_ORIGINS/validate_prod_secrets'
}

# 8. T01-T04 audit-submit-rectification checks
Write-Step 'Audit-submit-rectification checks'

# T01/T0-1: backend MultiCourseInput normalizes legacy priority via model_validator
$multiPlanSchema = Get-Content "$root\backend\app\schemas\multi_plan.py" -Raw
$plansPy = Get-Content "$root\backend\app\api\v1\endpoints\plans.py" -Raw
$schedulerPy = Get-Content "$root\backend\app\services\multi_scheduler.py" -Raw
if ($multiPlanSchema -match 'model_validator' -and $multiPlanSchema -match 'priority' -and $multiPlanSchema -match '/ 5.0') {
  Write-Ok 'MultiCourseInput normalizes legacy priority (1-5) to 0-1 via model_validator'
} else {
  Write-Bad 'MultiCourseInput missing priority normalization'
}

# T0-2: scheduler preserves user_priority=0.0 (uses is None, not or)
if ($schedulerPy -match 'is not None') {
  Write-Ok 'scheduler preserves user_priority=0.0'
} else {
  Write-Bad 'scheduler may override user_priority=0.0'
}

# T0-3: ENVIRONMENT check is case-insensitive
if ($configPy -match 'ENVIRONMENT.lower') {
  Write-Ok 'ENVIRONMENT check is case-insensitive'
} else {
  Write-Bad 'ENVIRONMENT check is case-sensitive'
}

# T02: schedule_multi_courses has user_config param
if ($schedulerPy -match 'user_config') {
  Write-Ok 'schedule_multi_courses accepts user_config'
} else {
  Write-Bad 'schedule_multi_courses missing user_config param'
}

# T02: create_multi_plan reads active config and passes user_config to scheduler
if ($plansPy -match 'get_active_config' -and $plansPy -match 'user_config=user_config') {
  Write-Ok 'create_multi_plan passes user_config to scheduler'
} else {
  Write-Bad 'create_multi_plan does not pass user_config'
}

# T03: frontend MultiPlanResult has no goal_ids
$planTs = Get-Content "$root\frontend\src\api\plan.ts" -Raw
if ($planTs -notmatch 'goal_ids') {
  Write-Ok 'frontend MultiPlanResult has no goal_ids'
} else {
  Write-Bad 'frontend MultiPlanResult still has goal_ids'
}

# T03: frontend MultiPlanCourseInput uses user_priority (not the legacy priority field)
# Use word-boundary regex so 'user_priority?' does not count as 'priority?'.
if ($planTs -match 'user_priority\?' -and $planTs -notmatch '(?<!user_)priority\?') {
  Write-Ok 'frontend MultiPlanCourseInput uses user_priority'
} else {
  Write-Bad 'frontend MultiPlanCourseInput still uses priority'
}

# T04: config.py rejects wildcard CORS in production
if ($configPy -match 'CORS_ORIGINS' -and $configPy -match '"\*" in origins') {
  Write-Ok 'config.py rejects wildcard CORS in production'
} else {
  Write-Bad 'config.py missing wildcard CORS rejection'
}

# 9. P0: AgentRunsView supports output_data.items
Write-Step 'AgentRunsView output_data.items support check'
$agentRunsVue = Get-Content "$root\frontend\src\views\AgentRunsView.vue" -Raw
if ($agentRunsVue -match 'obj\.items') {
  Write-Ok 'AgentRunsView supports output_data.items'
} else {
  Write-Bad 'AgentRunsView missing output_data.items support'
}

Write-Host ''
if ($failed) {
  Write-Host 'ACCEPTANCE FAILED' -ForegroundColor Red
  exit 1
} else {
  Write-Host 'ACCEPTANCE PASSED' -ForegroundColor Green
  exit 0
}
