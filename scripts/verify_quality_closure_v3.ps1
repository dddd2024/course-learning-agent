<#
.SYNOPSIS
    V3 Quality Closure Verification (PowerShell wrapper)

.DESCRIPTION
    Wraps scripts/verify_quality_closure_v3.py so the V3 baseline
    checks can be run from the repo root with the same invocation
    pattern as the existing Phase 2 acceptance scripts.

    The Python script performs these checks:
      1. No hardcoded "梯度下降" quiz content in backend/app/agents/
      2. No direct AgentAudit.finish_run(status="success") in agents
      3. V3 test files exist and pass via pytest
      4. Citation support_status supports "verified" for formal citations
      5. Quiz items carry source_evidence linked to chunks with quote_text

    Exits 0 if all checks pass, 1 if any fail.

.PARAMETER JsonOnly
    Output JSON only (suppress per-check console lines).

.PARAMETER Check
    Run a single check by name (e.g. no_hardcoded_quiz).

.EXAMPLE
    pwsh -NoProfile -File scripts/verify_quality_closure_v3.ps1

.EXAMPLE
    pwsh -NoProfile -File scripts/verify_quality_closure_v3.ps1 -Check no_hardcoded_quiz
#>
param(
    [switch]$JsonOnly,
    [string]$Check
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Prefer the backend venv Python so pytest dependencies are available.
$venvPython = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    # Fall back to system python.
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) {
        $python = (Get-Command python3 -ErrorAction SilentlyContinue).Source
    }
}

if (-not $python) {
    Write-Host '[FAIL] No Python interpreter found (checked backend\.venv and PATH)' -ForegroundColor Red
    exit 1
}

$scriptPath = Join-Path $root 'scripts\verify_quality_closure_v3.py'

Write-Host ''
Write-Host '=== V3 Quality Closure Verification ===' -ForegroundColor Cyan
Write-Host "  Python : $python"
Write-Host "  Script : $scriptPath"
Write-Host ''

$args = @($scriptPath)
if ($JsonOnly) { $args += '--json' }
if ($Check)    { $args += '--check'; $args += $Check }

& $python @args
$exitCode = $LASTEXITCODE

Write-Host ''
if ($exitCode -eq 0) {
    Write-Host 'V3 QUALITY CLOSURE: PASSED' -ForegroundColor Green
} else {
    Write-Host 'V3 QUALITY CLOSURE: FAILED' -ForegroundColor Red
}
exit $exitCode
