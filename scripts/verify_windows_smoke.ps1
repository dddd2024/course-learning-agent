[CmdletBinding()]
param(
    [int]$ApiPort = 18080,
    [int]$FrontendPort = 15173,
    [string]$ArtifactRoot = "artifacts/verification/windows-smoke"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$artifactDir = Join-Path $root $ArtifactRoot
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
$logPath = Join-Path $artifactDir 'redacted.log'
Set-Content -LiteralPath $logPath -Value '' -Encoding utf8
$result = [ordered]@{ schema_version = 1; started_at = [DateTime]::UtcNow.ToString('o'); passed = $false; checks = @() }
$runtime = $null

function Add-Check([string]$Name, [bool]$Passed, [string]$Detail) {
    $script:result.checks += [ordered]@{ name = $Name; passed = $Passed; detail = $Detail }
    if (-not $Passed) { throw "Windows smoke failed: $Name - $Detail" }
}
function Redact([string]$Value) {
    return ($Value -replace '(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+','$1[REDACTED]' -replace '\b(sk|rk|pk)-[A-Za-z0-9_-]{8,}\b','[REDACTED]')
}

$started = @()
try {
    Add-Check 'powershell' ($PSVersionTable.PSVersion.Major -ge 5) $PSVersionTable.PSVersion.ToString()
    $python = Join-Path $root 'backend\.venv\Scripts\python.exe'
    Add-Check 'python-venv' (Test-Path $python) $python
    Add-Check 'node' ([bool](Get-Command node -ErrorAction SilentlyContinue)) (node --version)
    Add-Check 'npm' ([bool](Get-Command npm -ErrorAction SilentlyContinue)) (npm --version)

    $env:APP_GIT_COMMIT = (git -C $root rev-parse HEAD).Trim()
    $smokeRun = "windows-smoke-$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
    $runtime = Join-Path $root ".windows-smoke-runs\$smokeRun"
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $env:DATABASE_URL = "sqlite:///$($runtime.Replace('\','/'))/smoke.db"
    $env:UPLOAD_DIR = Join-Path $runtime 'uploads'
    $env:PARSED_DIR = Join-Path $runtime 'parsed'
    $env:LLM_PROVIDER = 'mock'
    & $python (Join-Path $root 'scripts\init_db.py') | Out-Null
    Add-Check 'isolated-database' ($LASTEXITCODE -eq 0) 'created a smoke-only SQLite database'
    $backendLog = Join-Path $artifactDir 'backend.raw.log'
    $backendErr = Join-Path $artifactDir 'backend.err.log'
    $backend = Start-Process -FilePath $python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port',$ApiPort -WorkingDirectory (Join-Path $root 'backend') -PassThru -WindowStyle Hidden -RedirectStandardOutput $backendLog -RedirectStandardError $backendErr
    $started += $backend
    $deadline = (Get-Date).AddSeconds(30)
    do { Start-Sleep -Milliseconds 300; try { $health = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/health" } catch {} } until ($health -or (Get-Date) -gt $deadline)
    Add-Check 'backend-health' ($null -ne $health) 'health endpoint reachable'
    Add-Check 'backend-identity' ($health.app -eq 'course-learning-agent' -and $health.build.git_commit -eq $env:APP_GIT_COMMIT) 'app name and git commit match'

    $workerLog = Join-Path $artifactDir 'worker.raw.log'
    $workerErr = Join-Path $artifactDir 'worker.err.log'
    $worker = Start-Process -FilePath $python -ArgumentList (Join-Path $root 'scripts\run_parse_worker.py') -WorkingDirectory $root -PassThru -WindowStyle Hidden -RedirectStandardOutput $workerLog -RedirectStandardError $workerErr
    $started += $worker

    $userName = "test-smoke-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    $register = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/auth/register" -Method Post -ContentType 'application/json' -Body (@{ username = $userName; password = 'test1234' } | ConvertTo-Json)
    $login = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/auth/login" -Method Post -ContentType 'application/json' -Body (@{ username = $userName; password = 'test1234' } | ConvertTo-Json)
    Add-Check 'register-login' ($register.username -eq $userName -and [bool]$login.access_token) 'isolated test user authenticated'
    $headers = @{ Authorization = "Bearer $($login.access_token)" }
    $course = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/courses" -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ name = 'Windows smoke course'; teacher = 'smoke' } | ConvertTo-Json)
    Add-Check 'create-course' ($course.id -gt 0) 'course creation succeeded'
    $fixture = Join-Path $runtime 'fixture.txt'
    Set-Content -LiteralPath $fixture -Value "CRC 用于差错检测。停止等待协议每发送一帧后等待确认。" -Encoding utf8
    $uploadJson = & curl.exe --silent --show-error --fail -X POST "http://127.0.0.1:$ApiPort/api/v1/courses/$($course.id)/materials" -H "Authorization: Bearer $($login.access_token)" -F "file=@$fixture;type=text/plain"
    $material = $uploadJson | ConvertFrom-Json
    Add-Check 'upload-material' ([bool]$material.public_id) 'short TXT fixture uploaded'
    Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/materials/$($material.public_id)/parse" -Method Post -Headers $headers | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    do { Start-Sleep -Milliseconds 500; $materials = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/courses/$($course.id)/materials" -Headers $headers; $parsed = $materials.items | Where-Object { $_.public_id -eq $material.public_id } } until ($parsed.status -in @('ready','failed') -or (Get-Date) -gt $deadline)
    Add-Check 'parse-material' ($parsed.status -eq 'ready') "parse status: $($parsed.status)"
    $chunks = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/materials/$($material.public_id)/chunks" -Headers $headers
    Add-Check 'learning-page-data' ($chunks.total -gt 0) 'parsed chunks are available to the learning page'

    $frontendLog = Join-Path $artifactDir 'frontend.raw.log'
    $frontendErr = Join-Path $artifactDir 'frontend.err.log'
    # cmd.exe remains the tracked parent for npm -> node, so the finally block
    # can terminate only this script's process tree without touching a user's
    # pre-existing dev server.
    $frontend = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npm','run','dev','--','--host','127.0.0.1','--port',$FrontendPort,'--strictPort' -WorkingDirectory (Join-Path $root 'frontend') -PassThru -WindowStyle Hidden -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErr
    $started += $frontend
    $deadline = (Get-Date).AddSeconds(30)
    $frontCode = '000'
    do { Start-Sleep -Milliseconds 300; $frontCode = (& curl.exe --silent --output NUL --write-out '%{http_code}' "http://127.0.0.1:$FrontendPort/") } until ($frontCode -eq '200' -or (Get-Date) -gt $deadline)
    Add-Check 'frontend-home' ($frontCode -eq '200') "frontend homepage status: $frontCode"
    $result.passed = $true
}
catch {
    Add-Content -LiteralPath $logPath -Value (Redact $_.Exception.ToString())
    throw
}
finally {
    foreach ($process in $started) {
        if ($process -and -not $process.HasExited) {
            # /T applies only below the PID started by this script; it avoids
            # leaking Vite's node child while never discovering/killing an
            # unrelated existing process.
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
    }
    Start-Sleep -Seconds 1
    Start-Sleep -Milliseconds 500
    foreach ($raw in @('backend.raw.log','backend.err.log','worker.raw.log','worker.err.log','frontend.raw.log','frontend.err.log')) {
        $rawPath = Join-Path $artifactDir $raw
        if (Test-Path $rawPath) {
            try { Add-Content -LiteralPath $logPath -Value (Redact (Get-Content -LiteralPath $rawPath -Raw)) } catch { Add-Content -LiteralPath $logPath -Value 'log read unavailable after shutdown' }
            Remove-Item -LiteralPath $rawPath -Force -ErrorAction SilentlyContinue
        }
    }
    if ($runtime) {
        # SQLite WAL files can remain briefly locked while the worker exits.
        # Retry only the run directory constructed above; no user workspace
        # path is ever discovered or removed.
        for ($attempt = 0; $attempt -lt 5 -and (Test-Path $runtime); $attempt++) {
            Remove-Item -LiteralPath $runtime -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path $runtime) { Start-Sleep -Seconds 1 }
        }
    }
    $result.finished_at = [DateTime]::UtcNow.ToString('o')
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $artifactDir 'windows-smoke.json') -Encoding utf8
    if ($health) { $health | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $artifactDir 'health.json') -Encoding utf8 }
}
