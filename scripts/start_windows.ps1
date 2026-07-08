<#
.SYNOPSIS
    Windows app-like launcher for the Course Learning Agent platform.

.DESCRIPTION
    Starts the backend (FastAPI + Uvicorn) and frontend (Vite dev server)
    in hidden windows, waits for health checks, then opens the app in
    Microsoft Edge (or Chrome) --app mode for a desktop-app experience.

    Stability Task C/D/E enhancements:
    - First-run init: creates backend/.venv, installs requirements.txt,
      runs scripts/init_db.py so a fresh checkout can boot directly.
    - PID management: writes backend.pid / frontend.pid under logs/dev-server
      so stop_windows.ps1 can safely stop only this project's processes.
    - Port-reuse accuracy: verifies port 5173 actually serves this app
      (by checking the page content for the project identifier) before
      reusing it, avoiding false reuse of other Vite projects.

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

# One-click-launch fix B3: return owning process details for a port so the
# user can see WHO is holding 8000/5173 and act on it (stop_windows or kill).
function Get-PortOwner($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if (-not $conn) { return $null }
    $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique
    $rows = @()
    foreach ($procId in $pids) {
        if (-not $procId) { continue }
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
            $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId").CommandLine
            $rows += [PSCustomObject]@{
                PID        = $procId
                Name       = $proc.Name
                CommandLine = $cmd
            }
        } catch {
            $rows += [PSCustomObject]@{ PID = $procId; Name = '<exited>'; CommandLine = '' }
        }
    }
    return $rows
}

# One-click-launch fix B2: print the last 40 lines of backend.log so the
# user can see the real startup error (import fail, port bind, etc.) without
# having to dig for the log file.
function Show-BackendFailure($backendLog) {
    Write-Host ""
    Write-Host "=== backend.log (last 40 lines) ===" -ForegroundColor Red
    if (Test-Path $backendLog) {
        Get-Content $backendLog -Tail 40 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
    } else {
        Write-Host "  (log file not found: $backendLog)" -ForegroundColor Gray
    }
    Write-Host "=== full log: $backendLog ===" -ForegroundColor Red
    Write-Host ""
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

# One-click-launch fix B5: write launch_status.json so the user (and any
# future diagnostics tool) can inspect the last launch result without
# scraping console output.
function Write-LaunchStatus($status) {
    $statusFile = Join-Path $logDir "launch_status.json"
    $status | ConvertTo-Json -Depth 4 | Out-File -FilePath $statusFile -Encoding utf8 -Force
}

# --- Create log directory ---------------------------------------------------
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# --- Check Python (system) --------------------------------------------------
Write-Step "Checking Python..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Bad "Python not found. Please install Python 3.10+ and add it to PATH."
    exit 1
}
Write-Ok "System Python found."

# --- Stability Task C: first-run backend init (venv + reqs + init_db) -------
if (-not (Test-Path $venvPython)) {
    Write-Step "Creating backend/.venv..."
    & python -m venv (Join-Path $backendDir ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Bad "Failed to create backend/.venv"; exit 1 }
    Write-Ok "backend/.venv created."
} else {
    Write-Ok "backend/.venv exists."
}

# Task B: skip `pip install -r requirements.txt` when the marker file is
# newer than requirements.txt. Avoids re-running pip on every launch (slow
# and brittle on offline machines). Marker is only written on success.
$requirementsFile = Join-Path $backendDir "requirements.txt"
$installMarker = Join-Path $backendDir ".venv\.requirements_installed"
$needInstall = $true
if (Test-Path $installMarker) {
    $needInstall = $false
    if ((Get-Item $requirementsFile).LastWriteTime -gt (Get-Item $installMarker).LastWriteTime) {
        $needInstall = $true
    }
}

if ($needInstall) {
    Write-Step "Installing backend dependencies (pip install -r requirements.txt)..."
    & $venvPython -m pip install --upgrade pip --quiet
    & $venvPython -m pip install -r $requirementsFile --quiet
    if ($LASTEXITCODE -ne 0) { Write-Bad "Failed to install backend dependencies."; exit 1 }
    # Only write the marker on success so a failed install retries next launch.
    New-Item -ItemType File -Path $installMarker -Force | Out-Null
    Write-Ok "Backend dependencies installed."
} else {
    Write-Ok "Backend dependencies already installed, skipping pip install."
}

Write-Step "Initializing database (scripts/init_db.py)..."
$initDb = Join-Path $repoRoot "scripts\init_db.py"
& $venvPython $initDb
if ($LASTEXITCODE -ne 0) { Write-Bad "Database initialization failed."; exit 1 }
Write-Ok "Database initialized."

# --- Check Node/npm ---------------------------------------------------------
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
    finally { Pop-Location }
    Write-Ok "Frontend dependencies installed."
} else {
    Write-Ok "Frontend dependencies already installed."
}

# --- Backend port 8000 ------------------------------------------------------
$backendPort = 8000
# One-click-launch fix B1: health check uses 127.0.0.1 to match the uvicorn
# bind address. Using `localhost` here previously produced a false failure
# when localhost resolved to IPv6 ::1.
$backendUrl = "http://127.0.0.1:$backendPort/api/v1/health"
$backendLog = Join-Path $logDir "backend.log"
$backendPidFile = Join-Path $logDir "backend.pid"

$backendPidValue = $null
$backendHealthOk = $false

if (Test-PortInUse $backendPort) {
    Write-Step "Port $backendPort in use. Checking if it is our backend..."
    try {
        $resp = Invoke-WebRequest -Uri $backendUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        # Task C: only reuse if /health identifies this project, so a
        # different FastAPI app on 8000 is not silently reused.
        if ($resp.Content -notmatch "course-learning-agent") {
            Write-Bad "Port $backendPort is serving a different backend (not course-learning-agent)."
            $owners = Get-PortOwner $backendPort
            if ($owners) {
                Write-Host "  Owning process(es):" -ForegroundColor Gray
                $owners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1" -ForegroundColor Cyan
            }
            exit 1
        }
        Write-Ok "Backend already running on port $backendPort. Reusing."
        $backendHealthOk = $true
        # Record the existing PID if discoverable.
        $owners = Get-PortOwner $backendPort
        if ($owners) { $backendPidValue = $owners[0].PID }
    } catch {
        Write-Bad "Port $backendPort is occupied but not serving our backend health endpoint."
        $owners = Get-PortOwner $backendPort
        if ($owners) {
            Write-Host "  Owning process(es):" -ForegroundColor Gray
            $owners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
            Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1  (or free the port manually)" -ForegroundColor Cyan
        }
        exit 1
    }
} else {
    Write-Step "Starting backend on port $backendPort..."
    $backendArgs = @(
        "-NoExit",
        "-WindowStyle", "Hidden",
        "-Command",
        "cd '$backendDir'; & '$venvPython' -m uvicorn app.main:app --reload --host 127.0.0.1 --port $backendPort 2>&1 | Tee-Object -FilePath '$backendLog'"
    )
    $backendProc = Start-Process -FilePath "powershell.exe" -ArgumentList $backendArgs -WindowStyle Hidden -PassThru
    # Stability Task D: record PID so stop_windows.ps1 can target it.
    $backendProc.Id | Out-File -FilePath $backendPidFile -Encoding ascii -Force
    $backendPidValue = $backendProc.Id
    Write-Step "Waiting for backend health check..."
    if (-not (Wait-ForUrl $backendUrl 30)) {
        Write-Bad "Backend failed to start within 30s. Backend will NOT be opened."
        # One-click-launch fix B2: show the log tail so the user sees the
        # real error, then exit WITHOUT opening the frontend — a visible
        # frontend with no backend is the exact failure mode we are fixing.
        Show-BackendFailure $backendLog
        Write-LaunchStatus @{
            launched = $false
            reason = "backend_health_check_failed"
            backend = @{ ok = $false; pid = $backendPidValue; log = $backendLog }
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    $backendHealthOk = $true
    Write-Ok "Backend is up (PID $($backendProc.Id))."
}

# --- Frontend port 5173 -----------------------------------------------------
# One-click-launch fix B4: re-verify the backend is still healthy BEFORE
# starting the frontend. If the backend crashed between the health check
# above and here (e.g. import error surfaced late), we must NOT open a
# frontend that shows "后端服务不可达" — that is the exact failure mode.
if (-not $backendHealthOk) {
    Write-Bad "Backend is not healthy. Refusing to start frontend."
    Show-BackendFailure $backendLog
    Write-LaunchStatus @{
        launched = $false
        reason = "backend_not_healthy_before_frontend"
        backend = @{ ok = $false; pid = $backendPidValue; log = $backendLog }
        last_start_time = (Get-Date).ToString("o")
    }
    exit 1
}

$frontendPort = 5173
$frontendUrl = "http://localhost:$frontendPort"
$frontendLog = Join-Path $logDir "frontend.log"
$frontendPidFile = Join-Path $logDir "frontend.pid"
$frontendPidValue = $null

if (Test-PortInUse $frontendPort) {
    Write-Step "Port $frontendPort in use. Verifying it serves Course Learning Agent..."
    try {
        $resp = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        # Stability Task E: only reuse if the page identifies this project.
        if ($resp.Content -notmatch "course-learning-agent" -and $resp.Content -notmatch "课程学习助手") {
            Write-Bad "Port $frontendPort is serving a different project (not Course Learning Agent)."
            $owners = Get-PortOwner $frontendPort
            if ($owners) {
                Write-Host "  Owning process(es):" -ForegroundColor Gray
                $owners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1" -ForegroundColor Cyan
            }
            exit 1
        }
        Write-Ok "Frontend already running on port $frontendPort. Reusing."
        $owners = Get-PortOwner $frontendPort
        if ($owners) { $frontendPidValue = $owners[0].PID }
    } catch {
        Write-Bad "Port $frontendPort is occupied but not serving the frontend."
        $owners = Get-PortOwner $frontendPort
        if ($owners) {
            Write-Host "  Owning process(es):" -ForegroundColor Gray
            $owners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
            Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1  (or free the port manually)" -ForegroundColor Cyan
        }
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
    $frontendProc = Start-Process -FilePath "powershell.exe" -ArgumentList $frontendArgs -WindowStyle Hidden -PassThru
    $frontendProc.Id | Out-File -FilePath $frontendPidFile -Encoding ascii -Force
    $frontendPidValue = $frontendProc.Id
    Write-Step "Waiting for frontend to be ready..."
    if (-not (Wait-ForUrl $frontendUrl 30)) {
        Write-Bad "Frontend failed to start within 30s. Check log: $frontendLog"
        Write-LaunchStatus @{
            launched = $false
            reason = "frontend_health_check_failed"
            backend = @{ ok = $true; pid = $backendPidValue; log = $backendLog }
            frontend = @{ ok = $false; pid = $frontendPidValue; log = $frontendLog }
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    Write-Ok "Frontend is up (PID $($frontendProc.Id))."
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
Write-Host "  RepoRoot: $repoRoot" -ForegroundColor Cyan
Write-Host "  Frontend: $frontendUrl" -ForegroundColor Cyan
Write-Host "  Backend:  http://127.0.0.1:$backendPort/docs" -ForegroundColor Cyan
Write-Host "  Logs:     $logDir" -ForegroundColor Cyan
Write-Host "  Stop:     powershell.exe -File scripts\stop_windows.ps1" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# One-click-launch fix B5: record a successful launch so the user can
# verify "did the last one-click launch actually succeed?" by reading
# logs/dev-server/launch_status.json.
Write-LaunchStatus @{
    launched = $true
    reason = "ok"
    backend = @{ ok = $true; pid = $backendPidValue; url = "http://127.0.0.1:$backendPort"; log = $backendLog }
    frontend = @{ ok = $true; pid = $frontendPidValue; url = $frontendUrl; log = $frontendLog }
    repo_root = $repoRoot
    last_start_time = (Get-Date).ToString("o")
}
