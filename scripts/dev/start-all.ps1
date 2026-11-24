# 本地开发一键启动脚本（Windows PowerShell 5.1+）
# 启动 Docker 基础设施 + ai-engine-py + gateway-go + frontend。
# 用法: powershell.exe -ExecutionPolicy Bypass -File scripts\dev\start-all.ps1 [-SkipFrontend] [-SkipApps]

[CmdletBinding()]
param(
    [switch]$SkipFrontend,
    [switch]$SkipApps
)

$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$localDir = Join-Path $repo '.local'
$logDir = Join-Path $localDir 'logs'
$pidDir = Join-Path $localDir 'pids'
$binDir = Join-Path $localDir 'bin'
New-Item -ItemType Directory -Force -Path $logDir, $pidDir, $binDir | Out-Null

function Find-Executable {
    param([string[]]$Candidates, [string]$FallbackName)
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $command = Get-Command $FallbackName -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $null
}

$docker = Find-Executable -Candidates @(
    'D:\Docker\DockerDesktop\resources\bin\docker.exe',
    (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe')
) -FallbackName 'docker'
if (-not $docker) {
    throw '未找到 docker CLI。请先安装 Docker Desktop（参考 docs/LOCAL_SETUP.md）。'
}
$dockerDir = Split-Path -Parent $docker
$env:Path = "$dockerDir;D:\tools\go\bin;D:\tools\git\cmd;$env:Path"

function Test-DockerEngine {
    & $docker info *> $null
    return $LASTEXITCODE -eq 0
}

if (-not (Test-DockerEngine)) {
    $desktop = Find-Executable -Candidates @(
        'D:\Docker\DockerDesktop\Docker Desktop.exe',
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
    ) -FallbackName 'Docker Desktop'
    if (-not $desktop) {
        throw 'Docker Desktop 未安装或找不到 Docker Desktop.exe。'
    }
    Write-Host '[start] Docker Desktop ...'
    Start-Process -FilePath $desktop -ArgumentList '--accept-license' | Out-Null
    $ready = $false
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 2
        if (Test-DockerEngine) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        throw 'Docker 引擎在 180 秒内未就绪，请打开 Docker Desktop 查看诊断信息。'
    }
}

$deployDir = Join-Path $repo 'deploy'
$composeFile = Join-Path $deployDir 'docker-compose.yml'
$deployEnv = Join-Path $deployDir '.env'
if (-not (Test-Path $deployEnv)) {
    Copy-Item (Join-Path $deployDir '.env.example') $deployEnv
}

Write-Host '[start] PostgreSQL(pgvector) + Redis ...'
$composeLog = Join-Path $logDir 'compose.log'
& $docker compose --project-directory $deployDir -f $composeFile up -d --wait --wait-timeout 300 *> $composeLog
$composeExit = $LASTEXITCODE
if ($composeExit -ne 0) {
    Get-Content $composeLog -Tail 40 -ErrorAction SilentlyContinue
    throw 'docker compose up 失败，请查看 .local/logs/compose.log 与 docker compose logs。'
}
Write-Host '[ok] 基础设施健康'

if ($SkipApps) {
    Write-Host '[done] 基础设施已启动（-SkipApps）。'
    exit 0
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory
    )

    $pidFile = Join-Path $pidDir "$Name.pid"
    if (Test-Path $pidFile) {
        $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
            Write-Host "[skip] $Name 已在运行 (pid=$existingPid)"
            return
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }

    $stdout = Join-Path $logDir "$Name.out.log"
    $stderr = Join-Path $logDir "$Name.err.log"
    $startParams = @{
        FilePath               = $FilePath
        WorkingDirectory       = $WorkingDirectory
        RedirectStandardOutput = $stdout
        RedirectStandardError  = $stderr
        PassThru               = $true
        WindowStyle            = 'Hidden'
        ErrorAction            = 'Stop'
    }
    if ($Arguments -and $Arguments.Count -gt 0) {
        $startParams['ArgumentList'] = $Arguments
    }
    $process = Start-Process @startParams
    Set-Content -Path $pidFile -Value $process.Id -Encoding ascii
    Write-Host "[start] $Name (pid=$($process.Id), logs=.local/logs/$Name.*.log)"
}

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSeconds = 90, [hashtable]$Headers = @{})
    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -Headers $Headers -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return $true
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

$engineDir = Join-Path $repo 'ai-engine-py'
$enginePython = Join-Path $engineDir '.venv\Scripts\python.exe'
if (-not (Test-Path $enginePython)) {
    $enginePython = Find-Executable -Candidates @() -FallbackName 'python'
}
if (-not $enginePython) {
    throw '找不到 Python。请按 ai-engine-py/README.md 创建 .venv。'
}

$gatewayDir = Join-Path $repo 'gateway-go'
$go = Find-Executable -Candidates @('D:\tools\go\bin\go.exe') -FallbackName 'go'
if (-not $go) {
    throw '找不到 Go 工具链。请参考 docs/LOCAL_SETUP.md。'
}
Write-Host '[build] gateway-go ...'
Push-Location $gatewayDir
try {
    & $go build -trimpath -o (Join-Path $binDir 'gateway.exe') ./cmd/gateway
    if ($LASTEXITCODE -ne 0) {
        throw 'gateway-go 构建失败。'
    }
} finally {
    Pop-Location
}

$token = 'dev-internal-token-change-me'
$engineEnv = Join-Path $engineDir '.env'
if (Test-Path $engineEnv) {
    $tokenLine = Get-Content $engineEnv | Where-Object { $_ -match '^INTERNAL_TOKEN=' } | Select-Object -First 1
    if ($tokenLine) {
        $token = $tokenLine.Split('=', 2)[1].Trim()
    }
}

Start-LoggedProcess -Name 'engine' -FilePath $enginePython -Arguments @(
    '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'
) -WorkingDirectory $engineDir

Start-LoggedProcess -Name 'gateway' -FilePath (Join-Path $binDir 'gateway.exe') `
    -Arguments @() -WorkingDirectory $gatewayDir

if (-not $SkipFrontend) {
    $npm = Find-Executable -Candidates @(
        (Join-Path $env:ProgramFiles 'nodejs\npm.cmd'),
        'C:\Program Files\nodejs\npm.cmd'
    ) -FallbackName 'npm.cmd'
    if (-not $npm) {
        throw '找不到 npm。请先安装 Node.js >= 20.19。'
    }
    Start-LoggedProcess -Name 'frontend' -FilePath 'cmd.exe' -Arguments @(
        '/c', "`"$npm`" run dev -- --host 127.0.0.1"
    ) -WorkingDirectory (Join-Path $repo 'frontend')
}

Write-Host '[wait] 检查服务健康状态 ...'
$engineOk = Wait-HttpOk -Url 'http://127.0.0.1:8000/internal/v1/health' -Headers @{ 'X-Internal-Token' = $token }
$gatewayOk = Wait-HttpOk -Url 'http://127.0.0.1:8080/readyz'
$frontendOk = $SkipFrontend -or (Wait-HttpOk -Url 'http://127.0.0.1:5173/')

[pscustomobject]@{
    PostgreSQL = '127.0.0.1:5432'
    Redis = '127.0.0.1:6379'
    Engine = if ($engineOk) { 'ok' } else { 'check logs' }
    Gateway = if ($gatewayOk) { 'ok' } else { 'check logs' }
    Frontend = if ($SkipFrontend) { 'skipped' } elseif ($frontendOk) { 'ok' } else { 'check logs' }
} | Format-Table -AutoSize

if (-not ($engineOk -and $gatewayOk -and $frontendOk)) {
    Write-Warning '部分服务未在超时时间内就绪，请查看 .local/logs/ 与 docker compose ps。'
    exit 1
}

Write-Host '[ready] 全栈已启动：http://127.0.0.1:5173'
