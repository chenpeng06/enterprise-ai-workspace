# 本地开发栈状态自检（Windows PowerShell 5.1+）：Docker 基础设施 + 引擎 + 网关 + 前端。
# 用法: powershell.exe -ExecutionPolicy Bypass -File scripts\dev\status.ps1

[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$dockerCandidates = @(
    'D:\Docker\DockerDesktop\resources\bin\docker.exe',
    (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe')
)
$docker = $null
foreach ($candidate in $dockerCandidates) {
    if ($candidate -and (Test-Path $candidate)) {
        $docker = $candidate
        break
    }
}
if (-not $docker) {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) {
        $docker = $command.Source
    }
}

function Get-PortState {
    param([int]$Port)
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        return "LISTEN (pid=$($listener.OwningProcess))"
    }
    return 'CLOSED'
}

function Get-HttpState {
    param([string]$Url, [hashtable]$Headers = @{})
    try {
        $response = Invoke-WebRequest -Uri $Url -Headers $Headers -UseBasicParsing -TimeoutSec 3
        return "HTTP $($response.StatusCode)"
    } catch {
        if ($_.Exception.Response) {
            return "HTTP $([int]$_.Exception.Response.StatusCode)"
        }
        return 'UNREACHABLE'
    }
}

$token = 'dev-internal-token-change-me'
$engineEnv = Join-Path $repo 'ai-engine-py\.env'
if (Test-Path $engineEnv) {
    $tokenLine = Get-Content $engineEnv | Where-Object { $_ -match '^INTERNAL_TOKEN=' } | Select-Object -First 1
    if ($tokenLine) {
        $token = $tokenLine.Split('=', 2)[1].Trim()
    }
}

$rows = @(
    [pscustomobject]@{ Component = 'PostgreSQL'; Address = '127.0.0.1:5432'; State = (Get-PortState 5432) }
    [pscustomobject]@{ Component = 'Redis'; Address = '127.0.0.1:6379'; State = (Get-PortState 6379) }
    [pscustomobject]@{ Component = 'ai-engine-py'; Address = '/internal/v1/health'; State = (Get-HttpState 'http://127.0.0.1:8000/internal/v1/health' @{ 'X-Internal-Token' = $token }) }
    [pscustomobject]@{ Component = 'gateway-go'; Address = '/readyz'; State = (Get-HttpState 'http://127.0.0.1:8080/readyz') }
    [pscustomobject]@{ Component = 'frontend'; Address = 'http://127.0.0.1:5173/'; State = (Get-HttpState 'http://127.0.0.1:5173/') }
)
$rows | Format-Table -AutoSize

if ($docker) {
    Write-Host '--- Docker Compose ---'
    & $docker compose --project-directory (Join-Path $repo 'deploy') `
        -f (Join-Path $repo 'deploy\docker-compose.yml') ps 2>&1
}

$failed = @($rows | Where-Object { $_.State -notmatch '^HTTP 200' -and $_.State -notmatch '^LISTEN' })
if ($failed.Count -gt 0) {
    Write-Warning '存在未就绪的组件，请查看 .local/logs/ 或 docker compose logs。'
    exit 1
}
Write-Host '[ok] 所有组件均可访问。'
