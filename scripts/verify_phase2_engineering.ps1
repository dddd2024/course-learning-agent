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

# 2. Frontend build
Write-Step 'Frontend build'
Push-Location "$root\frontend"
npm run build 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Ok 'frontend build passed' } else { Write-Bad 'frontend build failed' }
Pop-Location

# 3. No subjective-metric UI residue in frontend src
Write-Step 'Subjective metric UI residue check'
$src = "$root\frontend\src"
$matches = Get-ChildItem -Path $src -Recurse -File |
  Select-String -Pattern '可靠性|相关度|confidencePercent|命中率' -SimpleMatch
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

Write-Host ''
if ($failed) {
  Write-Host 'ACCEPTANCE FAILED' -ForegroundColor Red
  exit 1
} else {
  Write-Host 'ACCEPTANCE PASSED' -ForegroundColor Green
  exit 0
}
