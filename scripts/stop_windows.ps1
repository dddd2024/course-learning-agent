<#
.SYNOPSIS
    Stop the Course Learning Agent backend and frontend started by start_windows.ps1.

.DESCRIPTION
    Stability Task D: safely stops the hidden backend and frontend processes
    started by start_windows.ps1, using the PID files written under
    logs/dev-server. Falls back to port-based detection when PID files are
    missing. Never kills unrelated python.exe / node.exe processes.

.NOTES
    Run from anywhere:  powershell.exe -File scripts/stop_windows.ps1
#>

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repoRoot "logs\dev-server"

function Write-Step($msg)  { Write-Host "[..] $msg" -ForegroundColor Yellow }
function Write-Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Bad($msg)   { Write-Host "[FAIL] $msg" -ForegroundColor Red }
function Write-Info($msg)  { Write-Host "[i] $msg" -ForegroundColor Gray }

# --- Stop by PID file -------------------------------------------------------
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
        Write-Step "Stopping $name (PID $targetPid from $pidFile)..."
        try {
            $proc = Get-Process -Id $targetPid -ErrorAction Stop
            # Kill the process tree (the launcher spawns child python/node).
            Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
            # Also stop child processes on the same port.
            $stopped = $true
            Write-Ok "$name stopped (PID $targetPid)."
        } catch {
            Write-Info "$name PID $targetPid not running (already stopped)."
            $stopped = $true
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    # --- Fallback: port-based detection -------------------------------------
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conn) {
        # Find processes on this port whose command line references our repo.
        foreach ($c in $conn) {
            $procId = $c.OwningProcess
            if (-not $procId) { continue }
            try {
                $proc = Get-Process -Id $procId -ErrorAction Stop
                $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$procId").CommandLine
                if ($cmd -and ($cmd -match [regex]::Escape($repoRoot))) {
                    Write-Step "Port $port still held by PID $procId (this project). Stopping..."
                    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                    Write-Ok "Stopped PID $procId on port $port."
                    $stopped = $true
                }
            } catch {
                # Process may have exited between checks.
            }
        }
        # Re-check; if still in use by a non-project process, warn.
        $still = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        if ($still) {
            if (-not $stopped) {
                Write-Info "Port $port is in use by a non-project process; not touching it."
            }
        } else {
            Write-Ok "Port $port is now free."
        }
    } else {
        if (-not $stopped) { Write-Ok "$name not running (port $port free, no PID file)." }
    }
}

Write-Host ""
Write-Ok "Done. Course Learning Agent processes stopped."
