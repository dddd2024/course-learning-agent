<#
.SYNOPSIS
    Windows app-like launcher for the Course Learning Agent platform.

.DESCRIPTION
    Starts the backend (FastAPI + Uvicorn) and frontend (Vite dev server)
    in hidden windows, waits for health checks, then opens the app in
    Microsoft Edge (or Chrome) --app mode for a desktop-app experience.

    - Auto-locates the repo root (no hard-coded paths).
    - Prefers backend/.venv/Scripts/python.exe; falls back to system python.
    - Checks ports 8000 and 5173; reuses if already serving this app.
    - Logs to logs/dev-server/backend.log and frontend.log.

.NOTES
    Run from anywhere:  powershell.exe -File scripts/start_windows.ps1
    Or via desktop shortcut created by create_desktop_shortcut.ps1.
#>

$ErrorActionPreference = "Stop"

# --- Locate repo root -------------------------------------------------------
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$logDir = Join-Path $repoRoot "logs\dev-server"

# --- Verify project structure ----------------------------------------------
if (-not (Test-Path (Join-Path $backendDir "app\main.py"))) {
    Write-Host "[FAIL] backend/app/main.py not found. Is the repo root correct?" -ForegroundColor Red
    Write-Host "  Expected: $repoRoot" -ForegroundColor Gray
    exit 1
}
if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
    Write-Host "[FAIL] frontend/package.json not found." -ForegroundColor Red
    exit 1
}

# --- Helper functions -------------------------------------------------------
function Write-Step($msg)  { Write-Host "[..] $msg" -ForegroundColor Yellow }
function Write-Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Bad($msg)   { Write-Host "[FAIL] $msg" -ForegroundColor Red }

function Test-PortInUse($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    return $null -ne $conn
}

function Wait-ForUrl($url, $timeoutSec = 30) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Milliseconds 1000
        }
    }
    return $false
}

# --- Check dependencies -----------------------------------------------------
Write-Step "Checking Python..."
$pythonExe = $null
if (Test-Path $venvPython) {
    $pythonExe = $venvPython
    Write-Ok "Using venv Python: $pythonExe"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonExe = "python"
    Write-Ok "Using system Python."
} else {
    Write-Bad "Python not found. Please install Python 3.10+ or create backend/.venv."
    exit 1
}

Write-Step "Checking Node.js..."
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Bad "Node.js not found. Please install Node 18+ and add it to PATH."
    exit 1
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Bad "npm not found. Please install Node 18+."
    exit 1
}
Write-Ok "Node.js and npm found."

# --- Check frontend node_modules --------------------------------------------
$nodeModules = Join-Path $frontendDir "node_modules"
if (-not (Test-Path $nodeModules)) {
    Write-Step "Installing frontend dependencies..."
    Push-Location $frontendDir
    try { npm install } catch { Write-Bad "npm install failed."; exit 1 }
    Pop-Location
    Write-Ok "Frontend dependencies installed."
}

# --- Create log directory ---------------------------------------------------
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# --- Backend port 8000 ------------------------------------------------------
$backendPort = 8000
$backendUrl = "http://localhost:$backendPort/api/v1/health"
$backendLog = Join-Path $logDir "backend.log"

if (Test-PortInUse $backendPort) {
    Write-Step "Port $backendPort in use. Checking if it is our backend..."
    if (Wait-ForUrl $backendUrl 5) {
        Write-Ok "Backend already running on port $backendPort. Reusing."
    } else {
        Write-Bad "Port $backendPort is occupied by another process. Please free it or change the port."
        exit 1
    }
} else {
    Write-Step "Starting backend on port $backendPort..."
    $backendArgs = @(
        "-NoExit",
        "-WindowStyle", "Hidden",
        "-Command",
        "cd '$backendDir'; & '$pythonExe' -m uvicorn app.main:app --reload --host 127.0.0.1 --port $backendPort 2>&1 | Tee-Object -FilePath '$backendLog'"
    )
    Start-Process -FilePath "powershell.exe" -ArgumentList $backendArgs -WindowStyle Hidden
    Write-Step "Waiting for backend health check..."
    if (-not (Wait-ForUrl $backendUrl 30)) {
        Write-Bad "Backend failed to start within 30s. Check log: $backendLog"
        exit 1
    }
    Write-Ok "Backend is up."
}

# --- Frontend port 5173 -----------------------------------------------------
$frontendPort = 5173
$frontendUrl = "http://localhost:$frontendPort"
$frontendLog = Join-Path $logDir "frontend.log"

if (Test-PortInUse $frontendPort) {
    Write-Step "Port $frontendPort in use. Checking if it is our frontend..."
    try {
        $resp = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        Write-Ok "Frontend already running on port $frontendPort. Reusing."
    } catch {
        Write-Bad "Port $frontendPort is occupied by another process. Please free it."
        exit 1
    }
} else {
    Write-Step "Starting frontend on port $frontendPort..."
    $frontendArgs = @(
        "-NoExit",
        "-WindowStyle", "Hidden",
        "-Command",
        "cd '$frontendDir'; npm run dev -- --host 127.0.0.1 --port $frontendPort 2>&1 | Tee-Object -FilePath '$frontendLog'"
    )
    Start-Process -FilePath "powershell.exe" -ArgumentList $frontendArgs -WindowStyle Hidden
    Write-Step "Waiting for frontend to be ready..."
    if (-not (Wait-ForUrl $frontendUrl 30)) {
        Write-Bad "Frontend failed to start within 30s. Check log: $frontendLog"
        exit 1
    }
    Write-Ok "Frontend is up."
}

# --- Open in browser app mode ----------------------------------------------
Write-Step "Opening app in browser..."
$appUrl = $frontendUrl

# Try Edge first, then Chrome, then default browser.
$edgePath = @(
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

$chromePath = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($edgePath) {
    Write-Ok "Opening with Microsoft Edge (--app mode)."
    Start-Process -FilePath $edgePath -ArgumentList "--app=$appUrl", "--window-size=1400,900"
} elseif ($chromePath) {
    Write-Ok "Opening with Google Chrome (--app mode)."
    Start-Process -FilePath $chromePath -ArgumentList "--app=$appUrl", "--window-size=1400,900"
} else {
    Write-Ok "Edge/Chrome not found. Opening with default browser."
    Start-Process $appUrl
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Course Learning Agent is running!" -ForegroundColor Cyan
Write-Host "  Frontend: $frontendUrl" -ForegroundColor Cyan
Write-Host "  Backend:  http://localhost:$backendPort/docs" -ForegroundColor Cyan
Write-Host "  Logs:     $logDir" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
