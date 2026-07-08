<#
.SYNOPSIS
    Stop the Course Learning Agent backend and frontend started by start_windows.ps1.

.DESCRIPTION
    Stability Task D: safely stops the hidden backend and frontend processes
    started by start_windows.ps1, using the PID files written under
    logs/dev-server. Falls back to port-based detection when PID files are
    missing. Never kills unrelated python.exe / node.exe processes.

    P0 fix (this revision): the previous version only killed the wrapper
    powershell.exe (the PID recorded in backend.pid), leaving the child
    python.exe (uvicorn worker) alive as an ORPHAN that kept holding port
    8000. This made the stale-backend restart path in start_windows.ps1
    fail because stop "succeeded" but the port stayed occupied.

    Fix:
    1. Kill the entire process TREE (taskkill /T /F) so children die too.
    2. Scan ALL processes whose command line matches the repo path AND
       references uvicorn / vite / "npm run dev", regardless of port
       ownership — catches orphans whose parent wrapper already exited.

.NOTES
    Run from anywhere:  powershell.exe -File scripts\stop_windows.ps1
#>
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot "logs\dev-server"

function Write-Step($msg)  { Write-Host "[..] $msg" -ForegroundColor Yellow }
function Write-Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Bad($msg)   { Write-Host "[FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg)  { Write-Host "[i] $msg" -ForegroundColor Gray }

# Stop a process AND its entire child tree. Stop-Process -Force only kills
# the target PID; children spawned by it survive as orphans (this was the
# P0 bug — uvicorn --reload spawns a worker child that keeps the port).
# taskkill /T /F walks the tree and kills descendants first.
function Stop-ProcessTree($targetPid) {
    try {
        # taskkill /T = kill tree, /F = force. Returns nonzero if process
        # already exited, which is fine.
        & taskkill /T /F /PID $targetPid 2>$null | Out-Null
    } catch {
        # best-effort; process may have exited already
    }
}

# Scan all processes whose command line references our repo root AND
# indicates a Course Learning Agent service (uvicorn for backend, vite/
# npm for frontend). Returns matching PIDs. Catches orphans whose parent
# wrapper powershell.exe already exited — the previous port-based fallback
# missed these because Get-NetTCPConnection.OwningProcess pointed at the
# dead wrapper, not the live child.
function Find-ProjectServicePids {
    $matched = @()
    $repoEscaped = [regex]::Escape($repoRoot)
    # uvicorn backend: command line has "uvicorn app.main:app" and the
    # python.exe path is inside the repo's .venv.
    # frontend dev: command line has "vite" or "npm run dev" and the
    # working directory / script path is inside the repo.
    $patterns = @(
        'uvicorn\s+app\.main',
        'vite',
        'npm\.exe.*run\s+dev',
        [regex]::Escape($repoRoot)
    )
    try {
        $procs = Get-CimInstance Win32_Process -ErrorAction Stop
        foreach ($p in $procs) {
            $cmd = $p.CommandLine
            if (-not $cmd) { continue }
            # Must reference the repo path AND be a known service type.
            $isInRepo = $cmd -match $repoEscaped
            $isService = $cmd -match 'uvicorn\s+app\.main' -or
                         $cmd -match 'vite' -or
                         $cmd -match 'npm\.exe.*run\s+dev'
            if ($isInRepo -and $isService) {
                $matched += $p.ProcessId
            }
        }
    } catch {
        # best-effort
    }
    return $matched
}

# Find python.exe / node.exe processes whose PARENT has already exited
# (orphaned) AND whose command line indicates a service worker. These are
# multiprocessing workers / reloader children whose parent (the original
# uvicorn / vite process) already died; the worker keeps the INHERITED
# listening socket alive, holding the port even though
# Get-NetTCPConnection reports the dead parent as OwningProcess. This was
# the hidden root cause of the "stale /health" saga: an old uvicorn worker
# (PID 10040, multiprocessing.spawn child of dead PID 43828) held port 8000
# for the whole session because every detection path only looked at the
# dead OwningProcess. A worker is only killed here when its parent is dead
# — a live parent means the worker is still supervised and will die with
# the parent's tree-kill in Fallback 1.
function Find-OrphanedServiceWorkers {
    $matched = @()
    try {
        $procs = Get-CimInstance Win32_Process -ErrorAction Stop
        foreach ($p in $procs) {
            if ($p.Name -ne 'python.exe' -and $p.Name -ne 'node.exe') { continue }
            $cmd = $p.CommandLine
            if (-not $cmd) { continue }
            $isWorker = $cmd -match 'multiprocessing' -or
                        $cmd -match 'spawn_main' -or
                        $cmd -match 'uvicorn' -or
                        $cmd -match 'app\.main' -or
                        $cmd -match 'vite'
            if (-not $isWorker) { continue }
            $parentPid = $p.ParentProcessId
            if (-not $parentPid) { continue }
            $parentAlive = Get-Process -Id $parentPid -ErrorAction SilentlyContinue
            if ($parentAlive) { continue }
            $matched += $p.ProcessId
        }
    } catch {
        # best-effort
    }
    return $matched
}

# --- Stop by PID file + process tree ---------------------------------------
$pidFiles = @(
    @{ Name = "backend";  File = Join-Path $logDir "backend.pid";  Port = 8000 },
    @{ Name = "frontend"; File = Join-Path $logDir "frontend.pid"; Port = 5173 }
)

foreach ($entry in $pidFiles) {
    $name = $entry.Name
    $pidFile = $entry.File
    $port = $entry.Port
    $stopped = $false

    if (Test-Path $pidFile) {
        $targetPid = (Get-Content $pidFile | Select-Object -First 1).Trim()
        Write-Step "Stopping $name (PID $targetPid from $pidFile) + child tree..."
        try {
            $proc = Get-Process -Id $targetPid -ErrorAction Stop
            # P0 fix: kill the entire tree so child python.exe / node.exe
            # die too. Stop-Process alone leaves orphans.
            Stop-ProcessTree $targetPid
            $stopped = $true
            Write-Ok "$name stopped (PID $targetPid + tree)."
        } catch {
            Write-Info "$name PID $targetPid not running (already stopped)."
            $stopped = $true
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    # --- Fallback 1: port-based detection (with tree kill) -----------------
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        foreach ($c in $conn) {
            $procId = $c.OwningProcess
            if (-not $procId) { continue }
            try {
                $proc = Get-Process -Id $procId -ErrorAction Stop
                $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId").CommandLine
                if ($cmd -and ($cmd -match [regex]::Escape($repoRoot))) {
                    Write-Step "Port $port still held by PID $procId (this project). Killing tree..."
                    Stop-ProcessTree $procId
                    Write-Ok "Stopped PID $procId tree on port $port."
                    $stopped = $true
                }
            } catch {
                # OwningProcess exited (zombie socket) — handled by scan below.
            }
        }
    }

    # --- Fallback 2: command-line scan for orphaned children ----------------
    # The port-based fallback misses orphans whose parent wrapper exited,
    # because Get-NetTCPConnection.OwningProcess may point at the dead
    # wrapper. Scan all processes by command line to catch the live child.
    $orphans = Find-ProjectServicePids
    if ($orphans.Count -gt 0) {
        foreach ($opid in $orphans) {
            Write-Step "Found orphaned project service PID $opid. Killing tree..."
            Stop-ProcessTree $opid
            $stopped = $true
        }
        Write-Ok "Stopped $($orphans.Count) orphaned project process(es)."
    }

    # --- Fallback 3: orphaned inherited-socket workers ---------------------
    # If the port STILL has a Listen entry whose OwningProcess is dead, an
    # inherited-socket child (a multiprocessing worker / reloader child
    # whose parent already died) is keeping the port alive.
    # Get-NetTCPConnection reports the DEAD parent as OwningProcess, so
    # Fallback 1+2 miss it. Probe with a TCP connect: if the port actually
    # ACCEPTS connections, something live is holding it via an inherited
    # socket — hunt the orphaned worker and kill it.
    Start-Sleep -Milliseconds 300
    $listenEntry = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listenEntry) {
        $ownerAlive = $false
        if ($listenEntry.OwningProcess) {
            $ownerAlive = Get-Process -Id $listenEntry.OwningProcess -ErrorAction SilentlyContinue
        }
        if (-not $ownerAlive) {
            $portHeld = $false
            try {
                $probe = New-Object System.Net.Sockets.TcpClient
                $probe.Connect('127.0.0.1', $port)
                $portHeld = $true
                $probe.Close()
            } catch { }
            if ($portHeld) {
                Write-Step "Port $port still accepts connections (inherited-socket orphan). Hunting workers..."
                $workers = Find-OrphanedServiceWorkers
                if ($workers.Count -gt 0) {
                    foreach ($wpid in $workers) {
                        Write-Step "Killing orphaned worker PID $wpid (inherited socket)..."
                        Stop-ProcessTree $wpid
                        $stopped = $true
                    }
                    Write-Ok "Stopped $($workers.Count) inherited-socket worker(s)."
                } else {
                    Write-Info "Port $port accepts connections but no orphaned worker found; may be a non-project process."
                }
            }
        }
    }

    # --- Final re-check ----------------------------------------------------
    Start-Sleep -Milliseconds 500
    $still = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($still) {
        # A Listen entry with a LIVE owner = genuinely still in use.
        $liveConns = $still | Where-Object {
            $opid = $_.OwningProcess
            if (-not $opid) { return $false }
            (Get-Process -Id $opid -ErrorAction SilentlyContinue) -ne $null
        }
        if ($liveConns -and -not $stopped) {
            Write-Info "Port $port is in use by a non-project process; not touching it."
        } elseif ($liveConns) {
            Write-Info "Port $port still has live connections after stop (may be TIME_WAIT)."
        } else {
            # Listen entry with a DEAD owner: probe whether the inherited
            # socket is still live so we report honestly instead of the
            # false "zombie/TIME_WAIT (will clear)" that hid PID 10040.
            $inheritedLive = $false
            try {
                $probe = New-Object System.Net.Sockets.TcpClient
                $probe.Connect('127.0.0.1', $port)
                $inheritedLive = $true
                $probe.Close()
            } catch { }
            if ($inheritedLive) {
                Write-Bad "Port $port STILL accepts connections via inherited socket (unresolved orphan). Manual kill needed."
            } else {
                Write-Ok "Port $port connections are zombie/TIME_WAIT (will clear)."
            }
        }
    } else {
        if (-not $stopped) { Write-Ok "$name not running (port $port free, no PID file)." }
        else { Write-Ok "Port $port is now free." }
    }
}

Write-Host ""
Write-Ok "Done. Course Learning Agent processes stopped."
