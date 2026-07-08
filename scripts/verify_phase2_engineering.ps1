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

# 10. P6: Cross-course knowledge graph feature files present
Write-Step 'Cross-course knowledge graph feature file checks'
$kgApiTs = "$root\frontend\src\api\conceptGraph.ts"
$kgView = "$root\frontend\src\views\KnowledgeGraphView.vue"
$kgRouter = "$root\frontend\src\router\index.ts"
$kgLayout = "$root\frontend\src\layouts\MainLayout.vue"
$kgEndpoint = "$root\backend\app\api\v1\endpoints\concept_graph.py"
$kgService = "$root\backend\app\services\concept_graph_service.py"
$kgCompareAgent = "$root\backend\app\agents\concept_compare.py"
$kgCompareService = "$root\backend\app\services\concept_compare_service.py"
$kgModels = "$root\backend\app\models\concept_graph.py"

if (Test-Path $kgApiTs) { Write-Ok "frontend api/conceptGraph.ts exists" } else { Write-Bad "missing frontend/src/api/conceptGraph.ts" }
if (Test-Path $kgView) { Write-Ok "frontend KnowledgeGraphView.vue exists" } else { Write-Bad "missing frontend/src/views/KnowledgeGraphView.vue" }
if (Test-Path $kgEndpoint) { Write-Ok "backend concept_graph endpoint exists" } else { Write-Bad "missing backend/app/api/v1/endpoints/concept_graph.py" }
if (Test-Path $kgService) { Write-Ok "backend concept_graph_service exists" } else { Write-Bad "missing backend/app/services/concept_graph_service.py" }
if (Test-Path $kgCompareAgent) { Write-Ok "backend concept_compare agent exists" } else { Write-Bad "missing backend/app/agents/concept_compare.py" }
if (Test-Path $kgCompareService) { Write-Ok "backend concept_compare_service exists" } else { Write-Bad "missing backend/app/services/concept_compare_service.py" }
if (Test-Path $kgModels) { Write-Ok "backend concept_graph models exist" } else { Write-Bad "missing backend/app/models/concept_graph.py" }

# Static-content checks: route registered, menu item added, SVG graph present
$routerContent = Get-Content $kgRouter -Raw
if ($routerContent -match "knowledge-graph") { Write-Ok "router has /knowledge-graph route" } else { Write-Bad "router missing /knowledge-graph route" }
$layoutContent = Get-Content $kgLayout -Raw
if ($layoutContent -match '/knowledge-graph') { Write-Ok "MainLayout has knowledge-graph menu item" } else { Write-Bad "MainLayout missing knowledge-graph menu item" }
$kgViewContent = Get-Content $kgView -Raw
if ($kgViewContent -match '<svg') { Write-Ok "KnowledgeGraphView uses SVG graph" } else { Write-Bad "KnowledgeGraphView missing SVG graph" }
if ($kgViewContent -match 'compareDrawerVisible') { Write-Ok "KnowledgeGraphView has compare drawer" } else { Write-Bad "KnowledgeGraphView missing compare drawer" }

# 11. P3: Evidence binding and unified error checks (audit remediation)
Write-Step 'Concept graph evidence binding check'
$kgServiceContent = Get-Content "$root\backend\app\services\concept_graph_service.py" -Raw
if ($kgServiceContent -match '_merge_evidence_ids') {
  Write-Ok 'concept_graph_service binds evidence_chunk_ids'
} else {
  Write-Bad 'concept_graph_service missing evidence binding'
}

Write-Step 'Concept graph unified error check'
$kgEndpointContent = Get-Content "$root\backend\app\api\v1\endpoints\concept_graph.py" -Raw
if ($kgEndpointContent -match 'NotFoundException') {
  Write-Ok 'concept_graph endpoint uses unified exceptions'
} else {
  Write-Bad 'concept_graph endpoint still uses HTTPException'
}
if ($kgEndpointContent -match 'HTTPException') {
  Write-Bad 'concept_graph endpoint still references HTTPException'
} else {
  Write-Ok 'concept_graph endpoint has no HTTPException references'
}

Write-Step 'Concept compare evidence loading check'
$kgCompareContent = Get-Content "$root\backend\app\services\concept_compare_service.py" -Raw
if ($kgCompareContent -match '_load_evidence_chunks') {
  Write-Ok 'concept_compare_service loads evidence chunks'
} else {
  Write-Bad 'concept_compare_service missing evidence loading'
}
if ($kgCompareContent -match 'user_config') {
  Write-Ok 'concept_compare_service supports user_config'
} else {
  Write-Bad 'concept_compare_service missing user_config support'
}

# 12. P3: v2 audit remediation static checks
Write-Step 'v2 audit remediation checks'

# 12a. concept_compare mock builder registered in llm.py
$llmPy = Get-Content "$root\backend\app\agents\llm.py" -Raw
if ($llmPy -match '"concept_compare":\s*_mock_concept_compare') {
  Write-Ok 'concept_compare mock builder registered'
} else {
  Write-Bad 'concept_compare mock builder not registered'
}

# 12b. compare service loads evidence (never hardcodes evidence_chunks=[])
if ($kgCompareContent -match 'evidence_chunks=evidence_chunks' -and $kgCompareContent -notmatch 'evidence_chunks=\[\]') {
  Write-Ok 'compare service loads evidence (no hardcoded [])'
} else {
  Write-Bad 'compare service may hardcode evidence_chunks=[]'
}

# 12c. compare prompt template has user_focus placeholder
$comparePrompt = Get-Content "$root\backend\app\agents\prompts\concept_compare_v1.md" -Raw
if ($comparePrompt -match '\{user_focus\}') {
  Write-Ok 'compare prompt has user_focus placeholder'
} else {
  Write-Bad 'compare prompt missing user_focus placeholder'
}

# 12d. ConceptCompareReport model has evidence_hash + user_focus columns
$kgModelsContent = Get-Content "$root\backend\app\models\concept_graph.py" -Raw
if ($kgModelsContent -match 'evidence_hash' -and $kgModelsContent -match 'user_focus') {
  Write-Ok 'ConceptCompareReport has evidence_hash + user_focus columns'
} else {
  Write-Bad 'ConceptCompareReport missing evidence_hash/user_focus columns'
}

# 13. P3: v3 收尾 — compare 关键行为测试显式运行
Write-Step 'v3 compare behavior tests'
Push-Location "$root\backend"
& ".\.venv\Scripts\python.exe" -m pytest `
    app/tests/test_concept_compare_agent.py::test_concept_compare_mock_returns_citations_when_evidence_given `
    app/tests/test_concept_compare_agent.py::test_compare_prompt_contains_user_focus `
    app/tests/test_concept_compare_agent.py::test_compare_cache_separates_user_focus `
    app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_changes `
    app/tests/test_concept_compare_agent.py::test_compare_cache_invalidates_when_evidence_text_changes `
    app/tests/test_concept_compare_agent.py::test_compare_rejects_mismatched_edge_id `
    app/tests/test_concept_graph_api.py::test_compare_mismatched_edge_returns_400 `
    app/tests/test_concept_graph_api.py::test_compare_invalid_user_focus_returns_422 `
    app/tests/test_db_migrations.py `
    -q
if ($LASTEXITCODE -eq 0) { Write-Ok 'v3 compare behavior tests passed' } else { Write-Bad 'v3 compare behavior tests failed' }
Pop-Location

Write-Host ''
if ($failed) {
  Write-Host 'ACCEPTANCE FAILED' -ForegroundColor Red
  exit 1
} else {
  Write-Host 'ACCEPTANCE PASSED' -ForegroundColor Green
  exit 0
}
