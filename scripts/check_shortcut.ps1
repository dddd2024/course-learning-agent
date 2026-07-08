<#
.SYNOPSIS
    Inspect the Course Learning Agent desktop shortcut.

.DESCRIPTION
    One-click-launch fix C2: prints TargetPath, Arguments, WorkingDirectory,
    and IconLocation of the "Course Learning Agent.lnk" desktop shortcut so
    the user can quickly verify the icon points at the CURRENT repo (not a
    stale clone or an old script path).

    Exit codes:
      0 — shortcut found and printed
      1 — shortcut not found (run create_desktop_shortcut.ps1 first)

.NOTES
    Run from anywhere:  powershell.exe -File scripts/check_shortcut.ps1
#>

$ErrorActionPreference = "Stop"

$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "Course Learning Agent.lnk"

if (-not (Test-Path $shortcutPath)) {
    Write-Host "[FAIL] Desktop shortcut not found: $shortcutPath" -ForegroundColor Red
    Write-Host "  Run: powershell.exe -File scripts\create_desktop_shortcut.ps1" -ForegroundColor Cyan
    exit 1
}

try {
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($shortcutPath)
    Write-Host ""
    Write-Host "=== Course Learning Agent desktop shortcut ===" -ForegroundColor Cyan
    Write-Host "  Path:           $shortcutPath" -ForegroundColor White
    Write-Host "  TargetPath:     $($sc.TargetPath)" -ForegroundColor White
    Write-Host "  Arguments:      $($sc.Arguments)" -ForegroundColor White
    Write-Host "  WorkingDir:     $($sc.WorkingDirectory)" -ForegroundColor White
    Write-Host "  IconLocation:   $($sc.IconLocation)" -ForegroundColor White
    Write-Host "  Description:    $($sc.Description)" -ForegroundColor White
    Write-Host "================================================" -ForegroundColor Cyan

    # Sanity check: does the WorkingDirectory look like a course-learning-agent repo?
    $wd = $sc.WorkingDirectory
    if ($wd -and (Test-Path (Join-Path $wd "scripts\start_windows.ps1"))) {
        Write-Host "[OK] WorkingDirectory contains scripts\start_windows.ps1 — looks valid." -ForegroundColor Green
    } else {
        Write-Host "[WARN] WorkingDirectory does NOT contain scripts\start_windows.ps1." -ForegroundColor Yellow
        Write-Host "       The shortcut may point at a stale repo. Regenerate it:" -ForegroundColor Yellow
        Write-Host "       powershell.exe -File scripts\create_desktop_shortcut.ps1" -ForegroundColor Cyan
    }
} catch {
    Write-Host "[FAIL] Could not read shortcut: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
