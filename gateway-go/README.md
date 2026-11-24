# gateway-go · Go + Gin 高并发网关

项目入口与治理层：鉴权、租户上下文、Redis 分布式限流、业务 CRUD、SSE 流式代理、
TTFT / Token 统计与审计。**不包含**任何 RAG、文档解析或 Agent 编排逻辑。

## Phase 1 交付范围

- 可直接运行的 Gin 服务骨架：结构化日志、请求 ID、优雅停机；
- 配置加载与 fail-fast 校验（`.env` + 环境变量）；
- PostgreSQL（pgx）与 Redis（go-redis）客户端；
- `/healthz`、`/readyz`、`/version` 健康探针，`/readyz` 并发探测
  PostgreSQL / Redis / AI 引擎，并校验契约版本 `1.0.0`；
- 与 `docs/contracts/ai-engine-internal-v1.schema.json` 对齐的事件常量与
  `done` / `usage` / `citation` 消息类型。

限流、SSE 代理、监控落库等核心业务在 Phase 3 实现。

## 目录结构

```
gateway-go/
├── cmd/gateway/main.go           # 启动、依赖装配、优雅停机
├── internal/
│   ├── config/                   # 环境变量解析与校验
│   ├── observability/            # slog 结构化日志
│   ├── httpserver/
│   │   ├── server.go             # http.Server 生命周期
│   │   ├── router.go             # 路由注册（Phase 3 扩展点）
│   │   ├── health.go             # 存活/就绪探针
│   │   └── middleware/           # 请求 ID、访问日志
│   ├── client/aiengine/          # AI 引擎内部 REST 客户端
│   ├── contract/                 # 内部契约常量与流式消息结构
│   ├── store/                    # pgx 连接池
│   └── cache/                    # Redis 客户端
├── .env.example
├── Makefile
└── go.mod
```

## 本地运行

要求 Go 1.23+。

```bash
cd gateway-go
cp .env.example .env            # Windows: Copy-Item .env.example .env
go mod tidy                     # 首次拉取依赖并生成 go.sum
go run ./cmd/gateway
```

验证：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/readyz
curl http://127.0.0.1:8080/version
```

> 已在 Go 1.23.4 下验证 `go build` / `go vet` / `go test`。
> `go.mod` 将测试链路上的 `rogpeppe/go-internal` 固定为 v1.14.1，避免
> `go mod tidy` 追最新版本时自动切换到 Go 1.25 工具链。

`/readyz` 在任一依赖不可用时返回 `503` 与逐项诊断，便于本地排查
（例如 PostgreSQL 未启动时 `postgres.status=down`）。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | development | development / staging / production |
| `HTTP_ADDR` | `:8080` | 监听地址 |
| `HTTP_WRITE_TIMEOUT` | `0s` | SSE 场景必须为 0 |
| `AI_ENGINE_BASE_URL` | `http://127.0.0.1:8000` | Python 引擎内部地址 |
| `INTERNAL_TOKEN` | dev 默认值 | 内网共享密钥，生产必须替换 |
| `DATABASE_URL` | 本地 workspace 库 | PostgreSQL 连接串 |
| `REDIS_ADDR` | `127.0.0.1:6379` | Redis 地址 |
| `CORS_ORIGINS` | `http://127.0.0.1:5173` | 逗号分隔的前端来源 |

完整列表见 `.env.example`。

## 边界约定

- 租户信息由鉴权中间件写入上下文，调用 AI 引擎时通过 `X-Workspace-Id` /
  `X-Internal-Token` 传递；禁止把 `workspace_id` 交给前端任意指定。
- 网关侧统计的 TTFT 是端到端首字延迟；引擎侧 `timings.ttft_ms` 仅作对照，
  两者都会写入 `request_logs`（Phase 3）。
- SSE 代理必须原样保留 `event:`、`id:` 与 `data:`，仅旁路解析
  `usage` / `done` 事件用于计费与监控，不得改写业务事件内容。
