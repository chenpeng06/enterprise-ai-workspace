# scripts/dev · 本地一键开发栈

前提：Docker Desktop 已启动，`ai-engine-py/.venv` 与 `frontend/node_modules` 已安装。
脚本会自动定位 Docker Desktop（优先 `D:\Docker\DockerDesktop`），
并把 PID/日志写到仓库根目录 `.local/`（已 gitignore）。

```powershell
# 启动 PostgreSQL + Redis + 引擎 + 网关 + 前端
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\start-all.ps1

# 只启动基础设施
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\start-all.ps1 -SkipApps

# 健康检查（含 Docker Compose 状态）
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\status.ps1

# 停止应用进程（保留数据库/Redis 容器）
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\stop-all.ps1

# 同时停止容器
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\stop-all.ps1 -WithInfra
```

日志：`.local/logs/{engine,gateway,frontend}.{out,err}.log`
Compose 启动日志：`.local/logs/compose.log`
PID：`.local/pids/*.pid`

> 前端端口被占用时脚本不会自动杀掉占用进程；先运行 `stop-all.ps1` 或手动处理。
