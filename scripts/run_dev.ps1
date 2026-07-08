<#
.SYNOPSIS
    One-click launcher for the Course Learning Agent platform (backend + frontend).

.DESCRIPTION
    Starts the backend (FastAPI + Uvicorn) and frontend (Vite dev server) in two
    new PowerShell windows. Before starting, it verifies required dependencies
    (Python, Node, npm), auto-creates backend/.venv, installs backend/frontend
    dependencies when missing, and initializes the database.

    All output strings are ASCII-only so the script parses correctly on Chinese
    Windows under PowerShell 5.1 (avoids TerminatorExpectedAtEndOfString caused
    by misread multi-byte strings in a non-BOM file).

.NOTES
    Run from the repo root:  .\scripts\run_dev.ps1
    If execution policy blocks the script, run once in this session:
        Set-ExecutionPolicy -Scope Process Bypass
#>

$ErrorActionPreference = "Stop"

# Script lives in <repo>/scripts/run_dev.ps1; repo root is one level up.
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$venvDir = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$nodeModules = Join-Path $frontendDir "node_modules"

function Write-Header($msg) {
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host " $msg" -ForegroundColor Cyan
    Write-Host "================================================" -ForegroundColor Cyan
}

function Write-Step($msg)  { Write-Host "[..] $msg" -ForegroundColor Yellow }
function Write-Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Bad($msg)   { Write-Host "[FAIL] $msg" -ForegroundColor Red }

function Test-Command {
    param([string]$Name)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    return $null -ne $cmd
}

Write-Header "Course Learning Agent - One-Click Launcher"
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Dependency checks: Python / Node / npm
# ---------------------------------------------------------------------------
Write-Step "Checking Python..."
if (-not (Test-Command "python")) {
    Write-Bad "Python not found. Please install Python 3.10+ and add it to PATH."
    exit 1
}
$pyVersion = (python -c "import sys; print(sys.version)") 2>$null
Write-Ok "Python found: $pyVersion"

Write-Step "Checking Node.js..."
if (-not (Test-Command "node")) {
    Write-Bad "Node.js not found. Please install Node.js 18+ and add it to PATH."
    exit 1
}
$nodeVersion = (node --version) 2>$null
Write-Ok "Node.js found: $nodeVersion"

Write-Step "Checking npm..."
if (-not (Test-Command "npm")) {
    Write-Bad "npm not found. Please install Node.js 18+ (includes npm)."
    exit 1
}
$npmVersion = (npm --version) 2>$null
Write-Ok "npm found: $npmVersion"

Write-Host ""

# ---------------------------------------------------------------------------
# 2. Backend venv + dependencies
# ---------------------------------------------------------------------------
if (-not (Test-Path $venvPython)) {
    Write-Step "backend/.venv not found. Creating virtual environment..."
    Push-Location $backendDir
    try {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { Write-Bad "Failed to create backend/.venv"; exit 1 }
        Write-Ok "backend/.venv created"
    } finally { Pop-Location }
} else {
    Write-Ok "backend/.venv exists"
}

$reqFile = Join-Path $backendDir "requirements.txt"
$venvSitePackages = Join-Path $venvDir "Lib\site-packages"
$marker = Join-Path $venvSitePackages "fastapi"
if (-not (Test-Path $marker)) {
    Write-Step "Installing backend dependencies (pip install -r requirements.txt)..."
    & $venvPython -m pip install -r $reqFile
    if ($LASTEXITCODE -ne 0) { Write-Bad "Failed to install backend dependencies"; exit 1 }
    Write-Ok "Backend dependencies installed"
} else {
    Write-Ok "Backend dependencies already installed"
}

# ---------------------------------------------------------------------------
# 3. Database initialization
# ---------------------------------------------------------------------------
Write-Step "Initializing database (scripts/init_db.py)..."
$initDb = Join-Path $repoRoot "scripts\init_db.py"
& $venvPython $initDb
if ($LASTEXITCODE -ne 0) {
    Write-Bad "Database initialization failed. See error above."
    exit 1
}
Write-Ok "Database initialized"

# ---------------------------------------------------------------------------
# 4. Frontend dependencies
# ---------------------------------------------------------------------------
if (-not (Test-Path $nodeModules)) {
    Write-Step "frontend/node_modules not found. Running npm install..."
    Push-Location $frontendDir
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { Write-Bad "npm install failed"; exit 1 }
        Write-Ok "Frontend dependencies installed"
    } finally { Pop-Location }
} else {
    Write-Ok "Frontend dependencies already installed"
}

Write-Host ""

# ---------------------------------------------------------------------------
# 5. Start backend + frontend in new windows
# ---------------------------------------------------------------------------
Write-Step "Starting backend (FastAPI + Uvicorn, with reload)..."
$backendCmd = "cd '$backendDir'; & '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
$backend = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoExit", "-Command", $backendCmd `
    -PassThru

Write-Step "Starting frontend (Vue3 + Vite)..."
$frontendCmd = "cd '$frontendDir'; npm run dev"
$frontend = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoExit", "-Command", $frontendCmd `
    -PassThru

Write-Host ""
Write-Host "------------------------------------------------" -ForegroundColor Green
Write-Host " Started. Access URLs:" -ForegroundColor Green
Write-Host "------------------------------------------------" -ForegroundColor Green
Write-Host "  Backend API docs: http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Frontend page:    http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "  Demo account: demo / demo123456" -ForegroundColor Yellow
Write-Host "------------------------------------------------" -ForegroundColor Green
Write-Host ""
Write-Host "Press any key to stop backend and frontend, then exit..." -ForegroundColor Cyan
[void][System.Console]::ReadKey($true)

Write-Host ""
Write-Step "Stopping backend and frontend processes..."
foreach ($proc in @($backend, $frontend)) {
    if ($null -ne $proc -and -not $proc.HasExited) {
        # taskkill /T kills child processes (python.exe / node.exe) too.
        taskkill /T /F /PID $proc.Id 2>$null | Out-Null
        if (-not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Ok "Stopped. Bye."
