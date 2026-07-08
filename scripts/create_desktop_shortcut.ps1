<#
.SYNOPSIS
    Creates a desktop shortcut for the Course Learning Agent app.

.DESCRIPTION
    Creates a "Course Learning Agent.lnk" file on the current user's desktop
    that launches start_windows.ps1 via powershell.exe with -ExecutionPolicy Bypass.
    The shortcut's WorkingDirectory is set to the repo root so the launcher
    can auto-locate backend/ and frontend/.

    Icon: uses frontend/public/icons/app.ico if it exists, otherwise the
    default PowerShell icon.

.NOTES
    Run from anywhere:  powershell.exe -File scripts/create_desktop_shortcut.ps1
#>

$ErrorActionPreference = "Stop"

# --- Locate repo root -------------------------------------------------------
$repoRoot = Split-Path -Parent $PSScriptRoot
$startScript = Join-Path $PSScriptRoot "start_windows.ps1"

if (-not (Test-Path $startScript)) {
    Write-Host "[FAIL] start_windows.ps1 not found at: $startScript" -ForegroundColor Red
    exit 1
}

# --- Determine icon path ----------------------------------------------------
$iconPath = Join-Path $repoRoot "frontend\public\icons\app.ico"
if (-not (Test-Path $iconPath)) {
    $iconPath = ""  # Use default icon
    Write-Host "[INFO] app.ico not found, using default PowerShell icon." -ForegroundColor Yellow
}

# --- Create shortcut --------------------------------------------------------
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Course Learning Agent.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$startScript`""
$shortcut.WorkingDirectory = $repoRoot
$shortcut.WindowStyle = 1  # Normal window
$shortcut.Description = "Launch Course Learning Agent (backend + frontend + app window)"
if ($iconPath) {
    $shortcut.IconLocation = $iconPath
}
$shortcut.Save()

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host " Desktop shortcut created successfully!" -ForegroundColor Green
Write-Host "  Path: $shortcutPath" -ForegroundColor Green
Write-Host "  Target: powershell.exe -File `"$startScript`"" -ForegroundColor Green
Write-Host "  WorkingDir: $repoRoot" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Double-click the shortcut on your desktop to launch the app." -ForegroundColor Cyan
