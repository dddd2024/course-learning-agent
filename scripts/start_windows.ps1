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
    # CRITICAL: run init_db.py with CWD = $backendDir so that the relative
    # DATABASE_URL "sqlite:///./course_assistant.db" resolves to the SAME
    # file that uvicorn (which also runs from $backendDir) will use.
    # Without this, init_db creates/migrates <repo>/course_assistant.db
    # while uvicorn uses <repo>/backend/course_assistant.db — the backend
    # DB never gets the migration columns and /api/v1/logs returns 500.
    Push-Location $backendDir
    try {
        & $venvPython $initDb
        $initExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($initExit -ne 0) {
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
                # P0 fix: re-check the port after stop. Test-PortInUse
                # returns true for zombie/TIME_WAIT entries whose
                # OwningProcess has exited, AND for inherited-socket orphans
                # (a multiprocessing worker whose parent died but which keeps
                # the listening socket — Get-NetTCPConnection reports the
                # dead parent as owner). Distinguish three cases:
                #  (a) LIVE owner process      -> stop failed, refuse.
                #  (b) Dead owner but port ACCEPTS TCP connects -> inherited-
                #      socket orphan. Re-run stop (its Fallback 3 kills such
                #      workers) and re-probe; if still held, fail.
                #  (c) Dead owner and port REFUSES connects -> genuine
                #      zombie/TIME_WAIT; uvicorn will bind. Proceed.
                if (Test-PortInUse $backendPort) {
                    $liveOwners = Get-PortOwner $backendPort | Where-Object {
                        $_.Name -ne '<exited>'
                    }
                    if ($liveOwners) {
                        # Case (a): genuinely still held by a live process.
                        Write-Bad "stop_windows.ps1 ran but port $backendPort is still held by a live process. Refusing to start a conflicting backend."
                        $liveOwners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                        Write-LaunchStatus @{
                            launched        = $false
                            reason          = "backend_stale_stop_failed"
                            backend         = @{ ok = $false; port = $backendPort; stale = $true }
                            last_start_time = (Get-Date).ToString("o")
                        }
                        exit 1
                    } else {
                        # Dead owner — probe whether an inherited socket is live.
                        $inheritedHeld = $false
                        try {
                            $probe = New-Object System.Net.Sockets.TcpClient
                            $probe.Connect('127.0.0.1', $backendPort)
                            $inheritedHeld = $true
                            $probe.Close()
                        } catch { }
                        if ($inheritedHeld) {
                            # Case (b): re-run stop to kill the inherited-socket worker, then re-probe.
                            Write-Step "Port $backendPort still accepts connections (inherited-socket orphan). Re-running stop to clear it..."
                            & powershell.exe -File $stopScript
                            Start-Sleep -Seconds 2
                            $stillHeld = $false
                            try {
                                $probe2 = New-Object System.Net.Sockets.TcpClient
                                $probe2.Connect('127.0.0.1', $backendPort)
                                $stillHeld = $true
                                $probe2.Close()
                            } catch { }
                            if ($stillHeld) {
                                Write-Bad "Port $backendPort STILL held by inherited-socket orphan after second stop. Refusing to start a conflicting backend. Run scripts/stop_windows.ps1 manually or reboot."
                                Write-LaunchStatus @{
                                    launched        = $false
                                    reason          = "backend_inherited_socket_orphan"
                                    backend         = @{ ok = $false; port = $backendPort; stale = $true }
                                    last_start_time = (Get-Date).ToString("o")
                                }
                                exit 1
                            }
                            Write-Ok "Inherited-socket orphan cleared. Port $backendPort now free."
                        } else {
                            Write-Step "Port $backendPort has only zombie/TIME_WAIT entries (no live owner, refuses connects). Proceeding — uvicorn will bind."
                        }
                    }
                }
                Write-Ok "Stale backend stopped. Starting fresh backend."
            } else {
                Write-Ok "Backend already running on port $backendPort. Reusing."
                $backendHealthOk = $true
                $owners = Get-PortOwner $backendPort
                if ($owners) { $backendPidValue = $owners[0].PID }
            }
        } catch {
            # The health probe failed. This can mean two things:
            #   1. A different app IS listening but returned a non-200 /
            #      non-course-learning-agent response  -> genuinely occupied.
            #   2. No app is listening at all — the Test-PortInUse hit
            #      TIME_WAIT / zombie entries left over after stop_windows.
            #      In this case uvicorn can bind fine; we must NOT exit.
            # Distinguish by checking for a LIVE owning process on the port.
            $liveOwners = Get-PortOwner $backendPort | Where-Object { $_.Name -ne '<exited>' }
            if ($liveOwners) {
                Write-Bad "Port $backendPort is occupied by a live process but not serving our backend health endpoint."
                $liveOwners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1  (or free the port manually)" -ForegroundColor Cyan
                Write-LaunchStatus @{
                    launched        = $false
                    reason          = "backend_port_occupied_unhealthy"
                    backend         = @{ ok = $false; port = $backendPort }
                    last_start_time = (Get-Date).ToString("o")
                }
                exit 1
            } else {
                # No live owner — the port has only TIME_WAIT/zombie entries.
                # uvicorn will bind (SO_REUSEADDR). Proceed to start.
                Write-Step "Port $backendPort has no live listener (TIME_WAIT/zombie after stop). Proceeding to start backend."
            }
        }
    }

    if (-not $backendHealthOk) {
        Write-Step "Starting backend on port $backendPort..."
        # Inject the current git commit so /health.build.git_commit reflects
        # the code actually running in this process. The env var is inherited
        # by the child python process launched directly below.
        $env:APP_GIT_COMMIT = $currentCommit
        # P0 fix: direct-launch uvicorn (no --reload, no powershell wrapper).
        #  - Records the REAL python.exe PID (== the single uvicorn server
        #    process) so stop_windows.ps1 can kill it precisely. The previous
        #    wrapper approach recorded the powershell.exe wrapper PID; when
        #    that wrapper died the PID went stale and stop missed the real
        #    uvicorn, leaving it orphaned on port 8000 -> stale-restart loop.
        #  - No --reload: avoids the reloader-parent + worker-child split
        #    that made tree-killing and PID tracking ambiguous. The launcher
        #    runs the app for end-users, not dev hot-reload.
        #  - uvicorn writes all logs (INFO + access) to stderr by default, so
        #    redirect stderr to backend.log; stdout (rare) to backend.out.log.
        $backendOutLog = Join-Path $logDir "backend.out.log"
        $backendProc = Start-Process -FilePath $venvPython `
            -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port",$backendPort `
            -WorkingDirectory $backendDir `
            -WindowStyle Hidden `
            -RedirectStandardError $backendLog `
            -RedirectStandardOutput $backendOutLog `
            -PassThru
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

    # --- Parse worker (V6-50) ----------------------------------------------
    # Persistent background worker that polls the DB for queued parse
    # jobs and processes them with heartbeat + retry.  Started after
    # the backend is healthy so the DB schema is guaranteed to exist.
    $workerPidFile = Join-Path $logDir "parse_worker.pid"
    $workerLog = Join-Path $logDir "parse_worker.log"
    $workerScript = Join-Path $repoRoot "scripts\run_parse_worker.py"
    $workerProc = $null

    if (-not $backendHealthOk) {
        Write-Bad "Backend is not healthy. Refusing to start parse worker."
        Show-BackendFailure $backendLog
        Write-LaunchStatus @{
            launched        = $false
            reason          = "backend_not_healthy_before_worker"
            backend         = @{ ok = $false; pid = $backendPidValue; log = $backendLog }
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }

    if (Test-Path $workerPidFile) {
        $oldWorkerPid = (Get-Content $workerPidFile -ErrorAction SilentlyContinue).Trim()
        if ($oldWorkerPid -and (Get-Process -Id $oldWorkerPid -ErrorAction SilentlyContinue)) {
            Write-Step "Stopping stale parse worker (PID $oldWorkerPid)..."
            Stop-Process -Id $oldWorkerPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
        Remove-Item $workerPidFile -Force -ErrorAction SilentlyContinue
    }

    Write-Step "Starting parse worker..."
    $workerProc = Start-Process -FilePath $venvPython `
        -ArgumentList $workerScript `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardError $workerLog `
        -RedirectStandardOutput (Join-Path $logDir "parse_worker.out.log") `
        -PassThru
    $workerProc.Id | Out-File -FilePath $workerPidFile -Encoding ascii -Force
    Write-Ok "Parse worker started (PID $($workerProc.Id))."

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

    $frontendNeedsStart = $false
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
            # Same TIME_WAIT logic as the backend port check: the probe
            # failed, but that may be because no app is listening (only
            # TIME_WAIT entries). Distinguish by checking for a LIVE owner.
            $liveOwners = Get-PortOwner $frontendPort | Where-Object { $_.Name -ne '<exited>' }
            if ($liveOwners) {
                Write-Bad "Port $frontendPort is occupied by a live process but not serving the frontend."
                $liveOwners | Format-Table PID, Name, CommandLine -AutoSize | Out-Host
                Write-Host "  Run: powershell.exe -File scripts\stop_windows.ps1  (or free the port manually)" -ForegroundColor Cyan
                Write-LaunchStatus @{
                    launched        = $false
                    reason          = "frontend_port_occupied_unhealthy"
                    backend         = @{ ok = $true; pid = $backendPidValue }
                    frontend        = @{ ok = $false; port = $frontendPort }
                    last_start_time = (Get-Date).ToString("o")
                }
                exit 1
            } else {
                Write-Step "Port $frontendPort has no live listener (TIME_WAIT/zombie after stop). Proceeding to start frontend."
                $frontendNeedsStart = $true
            }
        }
    } else {
        $frontendNeedsStart = $true
    }

    if ($frontendNeedsStart) {
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
        # P0 fix: direct-launch via cmd.exe /c npm run dev (no powershell
        # wrapper, no -NoExit). The previous wrapper recorded the
        # powershell.exe wrapper PID; when it died the PID went stale and
        # stop missed the real vite/node process. cmd /c stays alive while
        # npm -> node (vite) runs; tree-killing the recorded cmd PID in
        # stop_windows.ps1 kills the whole npm->node chain.
        # vite writes the "ready" banner + URL to stdout, so redirect stdout
        # to frontend.log; stderr (rare errors) to frontend.err.log.
        $frontendErrLog = Join-Path $logDir "frontend.err.log"
        $frontendProc = Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c","npm","run","dev","--","--host","127.0.0.1","--port",$frontendPort `
            -WorkingDirectory $frontendDir `
            -WindowStyle Hidden `
            -RedirectStandardOutput $frontendLog `
            -RedirectStandardError $frontendErrLog `
            -PassThru
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

    # --- Post-launch liveness re-check (catches "starts then dies") --------
    # Some failures only surface seconds after startup (uvicorn crashes on
    # first request, vite exits after initial compile, the direct-launched
    # process fails to bind and dies right after the health check window).
    # The Wait-ForUrl checks above passed during the startup window but the
    # process may have died by now. Re-verify BOTH services are STILL alive
    # before declaring success, so launch_status.json never claims ok for a
    # dead launch and the browser never opens onto a broken app.
    Write-Step "Liveness re-check (3s settle)..."
    Start-Sleep -Seconds 3
    $backendAlive = $false
    try {
        $beRecheck = Invoke-WebRequest -Uri $backendUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        $backendAlive = ($beRecheck.StatusCode -eq 200)
    } catch { }
    if (-not $backendAlive) {
        Write-Bad "Backend died shortly after startup. Backend will NOT be usable."
        Show-BackendFailure $backendLog
        Write-LaunchStatus @{
            launched        = $false
            reason          = "backend_died_after_startup"
            backend         = @{ ok = $false; pid = $backendPidValue; log = $backendLog }
            frontend        = @{ ok = $true; pid = $frontendPidValue; log = $frontendLog }
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    $frontendAlive = $false
    try {
        $feRecheck = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        $frontendAlive = ($feRecheck.StatusCode -eq 200)
    } catch { }
    if (-not $frontendAlive) {
        Write-Bad "Frontend died shortly after startup."
        Write-LaunchStatus @{
            launched        = $false
            reason          = "frontend_died_after_startup"
            backend         = @{ ok = $true; pid = $backendPidValue; log = $backendLog }
            frontend        = @{ ok = $false; pid = $frontendPidValue; log = $frontendLog }
            last_start_time = (Get-Date).ToString("o")
        }
        exit 1
    }
    Write-Ok "Liveness re-check passed: both services still up after 3s."

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
        worker          = @{ ok = $true; pid = $workerProc.Id; log = $workerLog }
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
