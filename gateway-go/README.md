# gateway-go · Go + Gin 高并发网关

项目入口与治理层：鉴权、租户上下文、Redis 分布式限流、业务 CRUD、SSE 流式代理、
TTFT / Token 统计与审计。**不包含**任何 RAG、文档解析或 Agent 编排逻辑。

## Phase 1/4 交付范围

- 可直接运行的 Gin 服务骨架：结构化日志、请求 ID、优雅停机；
- 配置加载与 fail-fast 校验（`.env` + 环境变量）；
- PostgreSQL（pgx）与 Redis（go-redis）客户端；
- `/healthz`、`/readyz`、`/version` 健康探针，`/readyz` 并发探测
  PostgreSQL / Redis / AI 引擎，并校验契约版本 `1.0.0`；
- 本地邮箱密码登录、Redis HttpOnly 会话、RBAC（owner/admin/editor/viewer）；
- 用户/角色/重置密码管理，受控管理员不能任命 admin/owner；
- 游客每日检索配额（Redis Lua，原子计数）；
- Redis Lua 分布式令牌桶（workspace + route + user/IP），429 + `Retry-After`；
- `/api/v1/chat/stream` SSE 代理：逐行透传、旁路解析 TTFT/Token/引用/检索诊断，
  流结束后异步写 `messages`、`message_citations`、`retrieval_traces`、`request_logs`；
- `/api/v1/documents` PDF 上传，`/api/v1/admin/agent-types` 数字员工类型；
- `/api/v1/chunks/{id}` 原文预览、`/api/v1/admin/metrics` 监控聚合。

## 目录结构

```
gateway-go/
├── cmd/gateway/main.go           # 启动、依赖装配、优雅停机
├── internal/
│   ├── config/                   # 环境变量解析与校验
│   ├── observability/            # slog 结构化日志
│   ├── httpserver/
│   │   ├── server.go             # http.Server 生命周期
│   │   ├── router.go             # 公共/健康路由注册
│   │   ├── health.go             # 存活/就绪探针
│   │   └── middleware/           # 请求 ID、访问日志
│   ├── chatproxy/                # SSE 透传 + 指标/落库
│   ├── ratelimit/                # Redis Lua 令牌桶
│   ├── client/aiengine/          # 引擎内部 REST/SSE 客户端
│   ├── contract/                 # 内部契约常量与流式消息结构
│   ├── store/                    # pgx 连接池 + Phase 3 仓储
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
curl http://127.0.0.1:8080/api/v1/bootstrap
curl http://127.0.0.1:8080/api/v1/admin/metrics?hours=24
go test ./...
```

> 已在 Go 1.23.4 下验证 `go build` / `go vet` / `go test`。
> `go.mod` 将测试链路上的 `rogpeppe/go-internal` 固定为 v1.14.1，避免
> `go mod tidy` 追最新版本时自动切换到 Go 1.25 工具链。

`/readyz` 在任一依赖不可用时返回 `503` 与逐项诊断，便于本地排查
（例如 PostgreSQL 未启动时 `postgres.status=down`）。

## 公共 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | 邮箱密码登录，建立 HttpOnly 会话 |
| POST | `/api/v1/auth/logout` | 清除会话 |
| GET | `/api/v1/auth/me` / `/auth/quota` | 当前身份 / 游客每日配额 |
| GET | `/api/v1/bootstrap` | 演示租户与推荐问题 |
| POST | `/api/v1/chat/stream` | SSE 对话；RBAC + 游客配额 + 令牌桶 |
| GET | `/api/v1/chunks/{id}` | 文档切片预览（页码/bbox/quote） |
| GET/POST | `/api/v1/documents` | 文档列表 / PDF 上传（owner/admin） |
| GET | `/api/v1/admin/users` | 成员列表；POST/PATCH/DELETE 管理 |
| GET/PUT | `/api/v1/admin/settings`、`/admin/settings/guest-quota` | 配额设置（PUT 仅 owner） |
| GET/PUT | `/api/v1/admin/agent-types` | 数字员工类型 |
| GET | `/api/v1/admin/metrics?hours=24` | 限流/TTFT/Token/命中率 |

开发环境自动种子账号：`admin@demo.local/Admin@12345`（owner）、
`ops@demo.local/Ops@12345`（admin）、`guest@demo.local/Guest@12345`（viewer）。
生产必须设置 `SEED_DEMO_USERS=false`。

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
| `DEV_WORKSPACE_ID` | 演示 workspace | Phase 3/4 本地演示租户 |
| `DEV_KB_ID` | 演示知识库 | 默认知识库 |
| `RATE_LIMIT_CAPACITY` | 20 | 令牌桶容量 |
| `RATE_LIMIT_REFILL_PER_SECOND` | 0.5 | 每秒补充令牌数 |
| `SEED_DEMO_USERS` | development 为 true | 生产必须 false |
| `SESSION_TTL` | 12h | HttpOnly 会话 TTL |
| `SESSION_COOKIE_SECURE` | false | 生产必须 true |
| `DEMO_*_EMAIL/PASSWORD` | 本地演示账号 | 生产必须替换/删除 |
| `GUEST_QUOTA_DEFAULT` | 20 | 游客每日默认配额 |
| `UPLOAD_DIR` | `../.local/uploads` | 与引擎 `INGEST_LOCAL_ROOT` 一致 |
| `UPLOAD_MAX_MB` | 50 | PDF 大小上限 |
| `CORS_ORIGINS` | `http://127.0.0.1:5173` | 逗号分隔的前端来源 |

完整列表见 `.env.example`。

## 边界约定

- 租户信息由鉴权中间件写入上下文，调用 AI 引擎时通过 `X-Workspace-Id` /
  `X-Internal-Token` 传递；禁止把 `workspace_id` 交给前端任意指定。
- 网关侧统计的 TTFT 是端到端首字延迟；引擎侧 `timings.ttft_ms` 仅作对照，
  两者都会写入 `request_logs`（Phase 3）。
- SSE 代理必须原样保留 `event:`、`id:` 与 `data:`，仅旁路解析
  `usage` / `done` 事件用于计费与监控，不得改写业务事件内容。
