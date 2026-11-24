# 数据库冒烟测试（Windows PowerShell 5.1+）。
# 先 docker compose cp 再 psql -f，避免 PowerShell 管道改写 SQL 文本。
# 用法: powershell.exe -ExecutionPolicy Bypass -File scripts\db\verify.ps1

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
if (-not $docker) {
    throw '未找到 docker，请先启动 Docker Desktop。'
}

$smokeFile = Join-Path $repo 'deploy\verify\01_smoke.sql'
$containerName = 'eaw-postgres'

$running = (& $docker inspect --format '{{.State.Running}}' $containerName 2>$null)
if ($LASTEXITCODE -ne 0 -or $running -ne 'true') {
    throw 'PostgreSQL 容器 eaw-postgres 未运行，请先启动 docker compose。'
}

& $docker cp $smokeFile "${containerName}:/tmp/01_smoke.sql"
if ($LASTEXITCODE -ne 0) {
    throw '复制 smoke SQL 到容器失败。'
}

& $docker exec $containerName psql -v ON_ERROR_STOP=1 -U workspace -d workspace -f /tmp/01_smoke.sql
if ($LASTEXITCODE -ne 0) {
    throw '数据库冒烟测试失败。'
}

& $docker exec $containerName rm -f /tmp/01_smoke.sql | Out-Null

Write-Host '[ok] Phase 1 数据库冒烟测试通过。'
