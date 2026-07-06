<#
.SYNOPSIS
    一键启动课程学习助手 Agent 平台的前后端开发环境。

.DESCRIPTION
    在两个新的 PowerShell 窗口中分别启动后端（FastAPI + Uvicorn）和
    前端（Vite 开发服务器），并在控制台打印访问地址与 demo 账号。
    用户按下任意键后，脚本会关闭这两个窗口并退出。

.NOTES
    运行前请确保：
      - backend/.venv 已创建并安装 requirements.txt 中的依赖
      - frontend 已执行过 npm install
    在项目根目录执行：.\scripts\run_dev.ps1
#>

$ErrorActionPreference = "Stop"

# 脚本位于 <repo>/scripts/run_dev.ps1，项目根目录为其上一级。
$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host " 课程学习助手 Agent 平台 - 一键启动" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# 启动后端：在新窗口运行 Uvicorn（带热重载）。
Write-Host "正在启动后端（FastAPI + Uvicorn）..." -ForegroundColor Yellow
$backendCmd = "cd '$backendDir'; .venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
$backend = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoExit", "-Command", $backendCmd `
    -PassThru

# 启动前端：在新窗口运行 npm run dev。
Write-Host "正在启动前端（Vue3 + Vite）..." -ForegroundColor Yellow
$frontendCmd = "cd '$frontendDir'; npm run dev"
$frontend = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoExit", "-Command", $frontendCmd `
    -PassThru

Write-Host ""
Write-Host "------------------------------------------------" -ForegroundColor Green
Write-Host " 启动完成，访问地址：" -ForegroundColor Green
Write-Host "------------------------------------------------" -ForegroundColor Green
Write-Host "  后端 API 文档: http://localhost:8000/docs" -ForegroundColor White
Write-Host "  前端页面:     http://localhost:5173" -ForegroundColor White
Write-Host ""
Write-Host "  默认账号: demo / demo123456" -ForegroundColor Yellow
Write-Host "------------------------------------------------" -ForegroundColor Green
Write-Host ""
Write-Host "按任意键关闭前后端窗口并退出..." -ForegroundColor Cyan
[void][System.Console]::ReadKey($true)

Write-Host ""
Write-Host "正在关闭后端与前端进程..." -ForegroundColor Yellow
foreach ($proc in @($backend, $frontend)) {
    if ($null -ne $proc -and -not $proc.HasExited) {
        # 使用 taskkill /T 连同子进程（python.exe / node.exe）一起终止。
        taskkill /T /F /PID $proc.Id 2>$null | Out-Null
        if (-not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "已退出。" -ForegroundColor Cyan
