# Enterprise AI Workspace · 企业级智能知识库与数字员工工作台

面向企业研发运维场景的全栈 AI 项目：知识库问答、原文角标溯源、检索过程透视、
数字员工多智能体工作流，以及网关限流/TTFT/Token 监控。

> 当前进度：**Phase 1 + Phase 2 已完成** —— 四端脚手架、跨语言契约、
> pgvector 建模，以及混合检索（向量 + BM25 + RRF + Rerank）与 LangGraph
> 数字员工。Phase 3 开始实现 Go 限流、SSE 代理与前端交互。

## 架构一览

```
React 工作台 ──HTTPS/SSE──▶ gateway-go（Gin）
                               │  鉴权 / 租户 / Redis 令牌桶 / SSE 透传 / TTFT
                               │  内部 REST + SSE（X-Internal-Token）
                               ▼
                          ai-engine-py（FastAPI + LangGraph）
                               │  解析 / 父子切片 / 向量 + BM25 / RRF / Rerank
                               ▼
                   PostgreSQL 16 + pgvector（RLS 多租户）
```

| 子项目 | 技术栈 | 目录 |
| --- | --- | --- |
| 前端工作台 | React 18、TypeScript、Vite 6、TailwindCSS 3.4 | [`frontend/`](frontend/) |
| 高并发网关 | Go 1.23、Gin、Redis、pgx | [`gateway-go/`](gateway-go/) |
| AI 引擎 | Python 3.12+、FastAPI、LangGraph、SQLAlchemy/asyncpg | [`ai-engine-py/`](ai-engine-py/) |
| 部署 | Docker Compose、pgvector、阿里云 RDS/Redis/OSS/SAE/FC | [`deploy/`](deploy/) |

## 核心文档

- [本地开发环境（Windows 11 / Docker）](docs/LOCAL_SETUP.md) —— 实际安装路径、
  Docker 数据盘、一键启停、验证清单与排障。
- [模型供应商选型](docs/LLM_PROVIDERS.md) —— DeepSeek / 百炼 / 本地模型的组合，
  以及"DeepSeek 不提供 Embedding/Rerank"的边界说明。
- [密钥与 Git 账号配置](docs/SECRETS_AND_GIT.md) —— API Key、PAT、SSH 私钥
  的安全存放与配置方式。
- [架构与接口契约](docs/ARCHITECTURE.md) —— 服务边界、REST/SSE 契约、
  完整 JSON Schema、pgvector 建表 SQL、多租户与可观测性设计。
- [阶段路线图](docs/TASKS.md)
- [项目协作规则](AGENTS.md)
- 机器可读契约：[`docs/contracts/ai-engine-internal-v1.schema.json`](docs/contracts/ai-engine-internal-v1.schema.json)
- 契约样例：[`docs/contracts/examples/`](docs/contracts/examples/)
- 可执行 DDL：[`deploy/initdb/01_schema.sql`](deploy/initdb/01_schema.sql)

## 快速开始（本地）

### 0. 前置依赖

- Docker Desktop（WSL2 后端；per-user 安装无需管理员，本机数据盘位于
  `D:\Docker\data`）
- Node.js ≥ 20.19，npm
- Go ≥ 1.23（Phase 1 仅网关需要）
- Python ≥ 3.12
- Git（用于版本管理；运行时不是必需）
- `INTERNAL_TOKEN` 本地默认 `dev-internal-token-change-me`，生产必须替换。

### 一键启动（推荐）

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\start-all.ps1
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\status.ps1
```

脚本会启动 Docker Desktop（如未运行）、PostgreSQL/Redis、AI 引擎、网关与前端，
并把 PID/日志写入 `.local/`。停止：

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\stop-all.ps1
```

### 手工步骤

#### 1. 启动基础设施

```powershell
cd deploy
Copy-Item .env.example .env
docker compose up -d --wait
docker compose ps
```

首次启动会自动执行 `deploy/initdb/01_schema.sql`（pgvector、全文索引、RLS、
HNSW、BM25 函数等）。连接信息：`workspace / workspace @ 127.0.0.1:5432`。

#### 2. 启动 AI 引擎

```powershell
cd ai-engine-py
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

健康检查：

```powershell
curl.exe -H "X-Internal-Token: dev-internal-token-change-me" `
  http://127.0.0.1:8000/internal/v1/health
```

#### 3. 启动网关

```powershell
cd gateway-go
Copy-Item .env.example .env
go run ./cmd/gateway
curl.exe http://127.0.0.1:8080/readyz
```

#### 4. 启动前端

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
# http://127.0.0.1:5173
```

前端通过 Vite 代理访问网关；`/readyz` 会聚合 PostgreSQL、Redis 与 AI 引擎状态，
并校验契约版本。

## Phase 2 验证与演示

```powershell
cd ai-engine-py

# 1) 最小请求验证 DeepSeek / 百炼 Embedding（不打印 Key）
.\.venv\Scripts\python.exe scripts\check_models.py

# 2) 写入演示知识库（真实 1024 维 Embedding，可重复执行）
.\.venv\Scripts\python.exe scripts\seed_demo.py

# 3) 全量测试（含真实 PostgreSQL 检索 + 契约校验）
.\.venv\Scripts\python.exe -m pytest -q
```

真实链路已验收：

- `/internal/v1/retrieval/search` 返回 3 条候选，向量分/BM25 分/RRF 排名/页码/bbox 完整；
- `/internal/v1/chat/stream` 的 372 条真实 SSE 事件全部通过 JSON Schema 校验；
- DeepSeek `deepseek-flash` 生成带 `[1][2][3]` 角标的报告，usage 与 TTFT 正常回传。

## 契约与质量校验

```powershell
# 契约：Schema 自检 + 15 个样例 + 根 oneOf 唯一性
ai-engine-py\.venv\Scripts\python.exe scripts\validate_contracts.py

# 同步 ARCHITECTURE.md 中的完整 Schema / DDL 注入区块
ai-engine-py\.venv\Scripts\python.exe scripts\sync_architecture.py
ai-engine-py\.venv\Scripts\python.exe scripts\sync_architecture.py --check

# 本地全栈状态
powershell.exe -ExecutionPolicy Bypass -File scripts\dev\status.ps1

# 数据库冒烟（事务回滚，不污染数据）
powershell.exe -ExecutionPolicy Bypass -File scripts\db\verify.ps1

# 前端
cd frontend
npm run typecheck
npm run lint
npm run build

# Go
cd gateway-go
go vet ./...
go test ./...

# Python
cd ai-engine-py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

> 修改任何跨服务字段时，先改 `docs/contracts/ai-engine-internal-v1.schema.json`，
> 再同步三端类型与本文档；禁止新增“隐形字段”。

## 安全与成本基线

- 内部服务仅走 VPC；数据库/Redis 不暴露公网；
- 生产禁用默认 `INTERNAL_TOKEN`，回调使用 HMAC-SHA256 验签；
- 多租户 RLS + 复合索引；日志与提示词脱敏；
- 阿里云目标月度总成本 ≤ 1000 元，具体账单与选型见
  [`deploy/aliyun/README.md`](deploy/aliyun/README.md)。

## 阶段状态

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| Phase 1 | 脚手架、JSON Schema 契约、pgvector 建表 | ✅ 已交付，本地 Docker 全链路已跑通 |
| Phase 2 | 混合检索 + RRF + Rerank、LangGraph 数字员工 | ✅ 已交付，真实 DeepSeek/百炼链路已验证 |
| Phase 3 | Redis 令牌桶、SSE 代理、前端交互与管理看板 | 待开始 |
| Phase 4 | 容器化、阿里云部署与成本核算 | 待开始 |
