<#
.SYNOPSIS
    Windows app-like launcher for the Course Learning Agent platform.

.DESCRIPTION
    Starts the backend (FastAPI + Uvicorn) and frontend (Vite dev server)
    in hidden windows, waits for health checks, then opens the app in
    Microsoft Edge (or Chrome) --app mode for a desktop-app experience.

    P0 regression fix (this revision):
    - All helper functions are now defined BEFORE any call site. The
      previous revision called Write-Ok / Write-LaunchStatus before their
      definitions, breaking one-click launch entirely.
    - Added -DryRun / -NoOpen params so the acceptance script can verify
      the launcher without spawning long-lived processes or a browser.
    - Main flow is wrapped in a try/catch so any unhandled exception
      still writes launch_status.json instead of silently dying.

.PARAMETER DryRun
    Run all preflight checks (repo structure, Python/Node, venv, deps,
    config parsing) WITHOUT starting backend/frontend processes or
    opening a browser. Exits 0 and writes launch_status.json with
    reason="dry_run_ok" on success. Used by verify_phase2_engineering.ps1.

.PARAMETER NoOpen
    Start backend and frontend as usual but do NOT open the browser
    app-mode window. Used for automated acceptance or local debugging
    where the user already has a tab open.

.NOTES
    Run from anywhere:  powershell.exe -File scripts/start_windows.ps1
    Or via desktop shortcut created by create_desktop_shortcut.ps1.
#>
param(
    [switch]$DryRun,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

# --- Locate repo root -------------------------------------------------------
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$logDir = Join-Path $repoRoot "logs\dev-server"

# ============================================================================
# Helper functions — MUST be defined before any call site.
# PowerShell resolves function calls at runtime top-to-bottom; calling a
# function before its definition throws "not recognized as the name of a
# cmdlet, function, script file, or operable program" and (with
# $ErrorActionPreference="Stop") aborts the script. This was the P0
# regression: Write-Ok / Write-LaunchStatus were called before definition.
# ============================================================================
function Write-Step($msg) { Write-Host "[..] $msg" -ForegroundColor Yellow }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Bad($msg)  { Write-Host "[FAIL] $msg" -ForegroundColor Red }

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
                PID         = $procId
                Name        = $proc.Name
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
# Task E1: ensure the log directory exists before writing — early exit
# branches (project structure missing, Python/Node missing) run BEFORE
# the log-dir creation block and must still record a launch_status.json
# so the user can see "why did the last launch fail?".
function Write-LaunchStatus($status) {
    if (-not (Test-Path $logDir)) {
        try {
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        } catch {
            # If we cannot create the log dir we cannot record status —
            # fail silently so the actual failure message still prints.
            return
        }
    }
    $statusFile = Join-Path $logDir "launch_status.json"
    try {
        $status | ConvertTo-Json -Depth 4 | Out-File -FilePath $statusFile -Encoding utf8 -Force
    } catch {
        # best-effort; never let status writing mask the real failure.
    }
}

# ============================================================================
# Main flow — wrapped in try/catch so any unhandled exception still writes
# launch_status.json (Task C). Without this, a surprise error mid-launch
# would leave the user staring at a dead desktop shortcut with no feedback.
# ============================================================================
function Invoke-Main {
    # --- Create log directory (early, so Write-LaunchStatus always works) ---
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    # --- Task D: capture the current git commit ----------------------------
    # Used to (a) inject into the backend as APP_GIT_COMMIT for /health.build,
    # and (b) detect when port 8000 is held by a stale backend running an
    # older commit. Falls back to empty string if git is unavailable — the
    # launcher then skips the commit-mismatch restart path.
    $currentCommit = ""
    try {
        $gitCommit = git -C $repoRoot rev-parse HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $gitCommit) {
            $currentCommit = $gitCommit.Trim()
        }
    } catch {
        # git not installed or not a git repo — leave $currentCommit empty.
    }
    if ($currentCommit) {
        Write-Ok "Repo commit: $currentCommit"
    } else {
        Write-Step "Git commit unavailable (git missing or not a repo); skipping stale-backend commit check."
    }

    # --- Verify project structure ------------------------------------------
    if (-not (Test-Path (Join-Path $backendDir "app\main.py"))) {
        Write-Bad "backend/app/main.py not found. Is the repo root correct?"
        Write-Host "  Expected: $repoRoot" -ForegroundColor Gray
        Write-LaunchStatus @{
            launched        = $false
            reason          = "backend_main_missing"
            repo_root       = $repoRoot
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    if (-not (Test-Path (Join-Path $frontendDir "package.json"))) {
        Write-Bad "frontend/package.json not found."
        Write-LaunchStatus @{
            launched        = $false
            reason          = "frontend_package_missing"
            repo_root       = $repoRoot
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }

    # --- Check Python (system) ---------------------------------------------
    Write-Step "Checking Python..."
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Bad "Python not found. Please install Python 3.10+ and add it to PATH."
        Write-LaunchStatus @{
            launched        = $false
            reason          = "python_not_found"
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    Write-Ok "System Python found."

    # --- first-run backend init (venv + reqs + init_db) --------------------
    if (-not (Test-Path $venvPython)) {
        Write-Step "Creating backend/.venv..."
        & python -m venv (Join-Path $backendDir ".venv")
        if ($LASTEXITCODE -ne 0) {
            Write-Bad "Failed to create backend/.venv"
            Write-LaunchStatus @{
                launched        = $false
                reason          = "venv_creation_failed"
                last_start_time = (Get-Date).ToString("o")
            }
            exit 1
        }
        Write-Ok "backend/.venv created."
    } else {
        Write-Ok "backend/.venv exists."
    }

    # Skip `pip install` when the marker file is newer than requirements.txt.
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
        if ($LASTEXITCODE -ne 0) {
            Write-Bad "Failed to install backend dependencies."
            Write-LaunchStatus @{
                launched        = $false
                reason          = "pip_install_failed"
                last_start_time = (Get-Date).ToString("o")
            }
            exit 1
        }
        New-Item -ItemType File -Path $installMarker -Force | Out-Null
        Write-Ok "Backend dependencies installed."
    } else {
        Write-Ok "Backend dependencies already installed, skipping pip install."
    }

    Write-Step "Initializing database (scripts/init_db.py)..."
    $initDb = Join-Path $repoRoot "scripts\init_db.py"
    & $venvPython $initDb
    if ($LASTEXITCODE -ne 0) {
        Write-Bad "Database initialization failed."
        Write-LaunchStatus @{
            launched        = $false
            reason          = "db_init_failed"
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    Write-Ok "Database initialized."

    # --- Check Node/npm ----------------------------------------------------
    Write-Step "Checking Node.js..."
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Bad "Node.js not found. Please install Node 18+ and add it to PATH."
        Write-LaunchStatus @{
            launched        = $false
            reason          = "node_not_found"
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Bad "npm not found. Please install Node 18+."
        Write-LaunchStatus @{
            launched        = $false
            reason          = "npm_not_found"
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    Write-Ok "Node.js and npm found."

    # --- Check frontend node_modules ---------------------------------------
    $nodeModules = Join-Path $frontendDir "node_modules"
    if (-not (Test-Path $nodeModules)) {
        Write-Step "Installing frontend dependencies..."
        Push-Location $frontendDir
        try {
            npm install
            if ($LASTEXITCODE -ne 0) {
                Write-Bad "npm install failed."
                Write-LaunchStatus @{
                    launched        = $false
                    reason          = "npm_install_failed"
                    last_start_time = (Get-Date).ToString("o")
                }
                exit 1
            }
        } catch {
            Write-Bad "npm install failed."
            Write-LaunchStatus @{
                launched        = $false
                reason          = "npm_install_failed"
                last_start_time = (Get-Date).ToString("o")
            }
            exit 1
        } finally { Pop-Location }
        Write-Ok "Frontend dependencies installed."
    } else {
        Write-Ok "Frontend dependencies already installed."
    }

    # --- DryRun exit point (Task B) ----------------------------------------
    # All preflight checks (repo structure, Python/Node, venv, deps, db,
    # node_modules) have passed. DryRun does NOT start long-lived processes
    # or open a browser — it only proves the launcher itself is runnable.
    if ($DryRun) {
        Write-Ok "DryRun: all preflight checks passed. Not starting services."
        Write-LaunchStatus @{
            launched        = $true
            reason          = "dry_run_ok"
            dry_run         = $true
            repo_root       = $repoRoot
            git_commit      = $currentCommit
            last_start_time = (Get-Date).ToString("o")
        }
        return
    }

    # --- Backend port 8000 -------------------------------------------------
    $backendPort = 8000
    $backendUrl = "http://127.0.0.1:$backendPort/api/v1/health"
    $backendLog = Join-Path $logDir "backend.log"
    $backendPidFile = Join-Path $logDir "backend.pid"

    $backendPidValue = $null
    $backendHealthOk = $false

    if (Test-PortInUse $backendPort) {
        Write-Step "Port $backendPort in use. Checking if it is our backend..."
        try {
            $resp = Invoke-WebRequest -Uri $backendUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($resp.Content -notmatch "course-learning-agent") {
                Write-Bad "Port $backendPort is serving a different backend (not course-learning-agent)."
                $owners = Get-PortOwner $backendPort
                if ($owners) {
                    Write-Host "  Owning process(es):" -ForegroundColor Gray
                    $owners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                    Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1" -ForegroundColor Cyan
                }
                Write-LaunchStatus @{
                    launched        = $false
                    reason          = "backend_port_held_by_other_app"
                    backend         = @{ ok = $false; port = $backendPort }
                    last_start_time = (Get-Date).ToString("o")
                }
                exit 1
            }
            # Task D: stale-backend detection. If the running backend's
            # git_commit does not match the repo commit, stop it and restart.
            # Skip when $currentCommit is empty (git missing) — never fail
            # just because git is unavailable.
            $staleBackend = $false
            if ($currentCommit) {
                try {
                    $healthJson = $resp.Content | ConvertFrom-Json
                    $runningCommit = $healthJson.build.git_commit
                    if ($runningCommit -and $runningCommit -ne $currentCommit) {
                        Write-Step "Stale backend detected: running commit $runningCommit, repo commit $currentCommit. Restarting..."
                        $staleBackend = $true
                    }
                } catch {
                    Write-Step "Running backend has no build info (old version). Restarting..."
                    $staleBackend = $true
                }
            }
            if ($staleBackend) {
                $stopScript = Join-Path $PSScriptRoot "stop_windows.ps1"
                if (Test-Path $stopScript) {
                    & powershell.exe -File $stopScript
                    Start-Sleep -Seconds 2
                }
                # Task D hardening: re-check the port after stop. If stop
                # failed to release 8000, do NOT continue — opening a new
                # backend would just fail to bind. Fail with a clear reason.
                if (Test-PortInUse $backendPort) {
                    Write-Bad "stop_windows.ps1 ran but port $backendPort is still in use. Refusing to start a conflicting backend."
                    $owners = Get-PortOwner $backendPort
                    if ($owners) {
                        $owners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                    }
                    Write-LaunchStatus @{
                        launched        = $false
                        reason          = "backend_stale_stop_failed"
                        backend         = @{ ok = $false; port = $backendPort; stale = $true }
                        last_start_time = (Get-Date).ToString("o")
                    }
                    exit 1
                }
                Write-Ok "Stale backend stopped, port released. Starting fresh backend."
            } else {
                Write-Ok "Backend already running on port $backendPort. Reusing."
                $backendHealthOk = $true
                $owners = Get-PortOwner $backendPort
                if ($owners) { $backendPidValue = $owners[0].PID }
            }
        } catch {
            Write-Bad "Port $backendPort is occupied but not serving our backend health endpoint."
            $owners = Get-PortOwner $backendPort
            if ($owners) {
                Write-Host "  Owning process(es):" -ForegroundColor Gray
                $owners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1  (or free the port manually)" -ForegroundColor Cyan
            }
            Write-LaunchStatus @{
                launched        = $false
                reason          = "backend_port_occupied_unhealthy"
                backend         = @{ ok = $false; port = $backendPort }
                last_start_time = (Get-Date).ToString("o")
            }
            exit 1
        }
    }

    if (-not $backendHealthOk) {
        Write-Step "Starting backend on port $backendPort..."
        # Task D: inject the current git commit so /health.build.git_commit
        # reflects the code actually running in this process.
        $env:APP_GIT_COMMIT = $currentCommit
        $backendArgs = @(
            "-NoExit",
            "-WindowStyle", "Hidden",
            "-Command",
            "cd '$backendDir'; & '$venvPython' -m uvicorn app.main:app --reload --host 127.0.0.1 --port $backendPort 2>&1 | Tee-Object -FilePath '$backendLog'"
        )
        $backendProc = Start-Process -FilePath "powershell.exe" -ArgumentList $backendArgs -WindowStyle Hidden -PassThru
        $backendProc.Id | Out-File -FilePath $backendPidFile -Encoding ascii -Force
        $backendPidValue = $backendProc.Id
        Write-Step "Waiting for backend health check..."
        if (-not (Wait-ForUrl $backendUrl 30)) {
            Write-Bad "Backend failed to start within 30s. Backend will NOT be opened."
            Show-BackendFailure $backendLog
            Write-LaunchStatus @{
                launched        = $false
                reason          = "backend_health_check_failed"
                backend         = @{ ok = $false; pid = $backendPidValue; log = $backendLog }
                last_start_time = (Get-Date).ToString("o")
            }
            exit 1
        }
        $backendHealthOk = $true
        Write-Ok "Backend is up (PID $($backendProc.Id))."
    }

    # --- Frontend port 5173 -------------------------------------------------
    if (-not $backendHealthOk) {
        Write-Bad "Backend is not healthy. Refusing to start frontend."
        Show-BackendFailure $backendLog
        Write-LaunchStatus @{
            launched        = $false
            reason          = "backend_not_healthy_before_frontend"
            backend         = @{ ok = $false; pid = $backendPidValue; log = $backendLog }
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }

    $frontendPort = 5173
    $frontendUrl = "http://127.0.0.1:$frontendPort"
    $frontendLog = Join-Path $logDir "frontend.log"
    $frontendPidFile = Join-Path $logDir "frontend.pid"
    $frontendPidValue = $null

    if (Test-PortInUse $frontendPort) {
        Write-Step "Port $frontendPort in use. Verifying it serves Course Learning Agent..."
        try {
            $resp = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($resp.Content -notmatch "course-learning-agent" -and $resp.Content -notmatch "课程学习助手") {
                Write-Bad "Port $frontendPort is serving a different project (not Course Learning Agent)."
                $owners = Get-PortOwner $frontendPort
                if ($owners) {
                    Write-Host "  Owning process(es):" -ForegroundColor Gray
                    $owners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                    Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1" -ForegroundColor Cyan
                }
                Write-LaunchStatus @{
                    launched        = $false
                    reason          = "frontend_port_held_by_other_app"
                    backend         = @{ ok = $true; pid = $backendPidValue }
                    frontend        = @{ ok = $false; port = $frontendPort }
                    last_start_time = (Get-Date).ToString("o")
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
            Write-LaunchStatus @{
                launched        = $false
                reason          = "frontend_port_occupied_unhealthy"
                backend         = @{ ok = $true; pid = $backendPidValue }
                frontend        = @{ ok = $false; port = $frontendPort }
                last_start_time = (Get-Date).ToString("o")
            }
            exit 1
        }
    } else {
        Write-Step "Starting frontend on port $frontendPort..."
        # ERR_NETWORK fix: clear any inherited VITE_API_BASE_URL so the
        # frontend defaults to '/api/v1' (same-origin via Vite proxy).
        # A leftover VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1 from
        # a previous session would re-introduce cross-origin preflight and
        # the /logs ERR_NETWORK-with-token failure we just fixed.
        if ($env:VITE_API_BASE_URL) {
            Write-Step "Clearing inherited VITE_API_BASE_URL='$env:VITE_API_BASE_URL' (using same-origin proxy default)."
            Remove-Item Env:VITE_API_BASE_URL -ErrorAction SilentlyContinue
        }
        $apiMode = if ($env:VITE_API_BASE_URL) { "cross-origin ($env:VITE_API_BASE_URL)" } else { "same-origin proxy (/api/v1 -> 127.0.0.1:8000)" }
        Write-Ok "Frontend API mode: $apiMode"
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
                launched        = $false
                reason          = "frontend_health_check_failed"
                backend         = @{ ok = $true; pid = $backendPidValue; log = $backendLog }
                frontend        = @{ ok = $false; pid = $frontendPidValue; log = $frontendLog }
                last_start_time = (Get-Date).ToString("o")
            }
            exit 1
        }
        Write-Ok "Frontend is up (PID $($frontendProc.Id))."
    }

    # --- Open in browser app mode (skipped with -NoOpen) -------------------
    if (-not $NoOpen) {
        Write-Step "Opening app in browser..."
        $appUrl = $frontendUrl

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
    } else {
        Write-Ok "NoOpen: skipping browser launch. Services are running."
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

    Write-LaunchStatus @{
        launched        = $true
        reason          = "ok"
        backend         = @{ ok = $true; pid = $backendPidValue; url = "http://127.0.0.1:$backendPort"; log = $backendLog }
        frontend        = @{ ok = $true; pid = $frontendPidValue; url = $frontendUrl; log = $frontendLog }
        repo_root       = $repoRoot
        last_start_time = (Get-Date).ToString("o")
    }
}

# ============================================================================
# Entry point — try/catch wrapper (Task C). Any unhandled exception inside
# Invoke-Main lands here so the user always gets a launch_status.json
# explaining why the shortcut "did nothing".
# ============================================================================
try {
    Invoke-Main
} catch {
    $err = $_
    $errMsg = if ($err.Exception) { $err.Exception.Message } else { "$err" }
    $errLine = if ($err.InvocationInfo) { $err.InvocationInfo.ScriptLineNumber } else { 0 }
    $errPos = if ($err.InvocationInfo) { $err.InvocationInfo.PositionMessage } else { '' }
    Write-Bad "Unhandled exception in launcher: $errMsg"
    if ($errPos) { Write-Host "  at: $errPos" -ForegroundColor Gray }
    Write-Bad "See logs/dev-server/launch_status.json for details."
    Write-LaunchStatus @{
        launched         = $false
        reason           = "unhandled_exception"
        exception_message = $errMsg
        script_line       = $errLine
        position_message  = $errPos
        last_start_time   = (Get-Date).ToString("o")
    }
    exit 1
}
