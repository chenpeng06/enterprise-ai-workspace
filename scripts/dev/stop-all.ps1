# 停止本地开发栈（Windows PowerShell 5.1+）。默认保留 Docker 基础设施，
# 加 -WithInfra 一并停止容器。
# 用法: powershell.exe -ExecutionPolicy Bypass -File scripts\dev\stop-all.ps1 [-WithInfra]

[CmdletBinding()]
param(
    [switch]$WithInfra
)

$ErrorActionPreference = 'Continue'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pidDir = Join-Path $repo '.local\pids'

if (Test-Path $pidDir) {
    Get-ChildItem $pidDir -Filter '*.pid' -ErrorAction SilentlyContinue | ForEach-Object {
        $name = $_.BaseName
        $processId = Get-Content $_.FullName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($processId -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
            Write-Host "[stop] $name (pid=$processId)"
            & taskkill.exe /PID $processId /T /F *> $null
        } else {
            Write-Host "[skip] $name（进程已不存在）"
        }
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

if ($WithInfra) {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) {
        $deployDir = Join-Path $repo 'deploy'
        Write-Host '[stop] Docker 基础设施（postgres/redis）...'
        & docker compose --project-directory $deployDir -f (Join-Path $deployDir 'docker-compose.yml') down
    } else {
        Write-Host '[skip] 未找到 docker，忽略 -WithInfra。'
    }
}

Write-Host '[done] 本地开发进程已停止。'
