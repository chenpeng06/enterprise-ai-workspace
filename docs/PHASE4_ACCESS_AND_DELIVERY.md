# Phase 4 权限、内容运营与交付方案

> 状态：**权限/RBAC、游客配额、数字员工类型、PDF 摄取已实现并完成本机验收**；
> CI/CD 与阿里云部署在本阶段**只做方案记录**，待功能验收后再执行。

## 0. 已实现清单

| 能力 | 状态 | 入口 |
| --- | --- | --- |
| 本地邮箱密码登录 + HttpOnly 会话 | ✅ | `POST /api/v1/auth/login` |
| 三角色 RBAC | ✅ | `gateway-go/internal/auth` |
| 用户创建/角色变更/移除/重置密码 | ✅ | `/api/v1/admin/users` |
| 游客每日配额 | ✅ | `/api/v1/auth/quota`、`PUT /api/v1/admin/settings/guest-quota` |
| 数字员工类型 CRUD | ✅ | `/api/v1/admin/agent-types` |
| PDF 上传 + 解析/切片/Embedding | ✅ | `POST /api/v1/documents` |
| 管理后台页面 | ✅ | `/admin/users`、`/admin/agents`、`/admin/documents`、`/admin/settings` |
| CI/CD + 阿里云部署 | 📝 仅记录 | 本文第 6 节 |

本地演示账号（仅 `APP_ENV=development` 且 `SEED_DEMO_USERS=true`）：

| 邮箱 | 密码 | 角色 |
| --- | --- | --- |
| `admin@demo.local` | `Admin@12345` | 超级管理员 |
| `ops@demo.local` | `Ops@12345` | 受控管理员 |
| `guest@demo.local` | `Guest@12345` | 游客 |

生产环境必须关闭种子账号、替换默认密码，并启用 `SESSION_COOKIE_SECURE=true`。

## 1. 角色与权限矩阵

复用现有 `users`、`workspace_members.role`（`owner/admin/editor/viewer`），
对外映射为：

| 产品角色 | DB 角色 | 权限 |
| --- | --- | --- |
| 超级管理员 | `owner` | 全部；任命/撤销受控管理员；修改游客配额；管理数字员工类型；上传 PDF；用户管理 |
| 受控管理员 | `admin` | 管理 guest/editor 用户、上传文档、维护数字员工类型、查看看板；**不能**任命管理员、不能修改游客配额 |
| 运营人员（预留） | `editor` | 只读知识库 + 使用数字员工；可由受控管理员设置 |
| 游客 | `viewer` | 只读使用；仅能对话/检索，受每日配额限制；不能上传、配置或管理用户 |

后端以 `workspace_members.role` 为唯一授权来源，角色变更立即生效；
禁止仅靠前端隐藏按钮做权限控制。

不变量：

- 不允许删除/降级最后一个 `owner`；
- `admin` 不能创建/修改 `owner`、`admin`，也不能修改自己的角色；
- 只有 `owner` 能修改 `guest_daily_query_quota`；
- 所有后台写操作必须记录操作者 `invited_by` / `created_by`。

## 2. 身份认证

- 本地邮箱 + 密码，密码使用 bcrypt 哈希；
- 登录成功生成 256-bit 随机会话 token，写入 Redis `session:<token>`，TTL 12h；
- 浏览器 Cookie：`HttpOnly; SameSite=Lax; Path=/`，生产开启 `Secure`；
- 每次请求从 Redis 取 session，再查 `users + workspace_members`，保证角色变更立即生效；
- `POST /api/v1/auth/login`、`POST /api/v1/auth/logout`、`GET /api/v1/bootstrap`
  公开；其余 `/api/v1/*` 必须登录；
- 受控管理员/超管接口在 Handler 层再次做权限断言，不能只依赖路由中间件。

认证/管理接口：

| 方法 | 路径 | 权限 |
| --- | --- | --- |
| `POST` | `/api/v1/auth/login` | 公开 |
| `POST` | `/api/v1/auth/logout` | 公开（清 Cookie） |
| `GET` | `/api/v1/auth/me` | 登录 |
| `GET` | `/api/v1/auth/quota` | 登录（游客返回每日用量） |
| `GET` | `/api/v1/admin/users` | owner/admin |
| `POST` | `/api/v1/admin/users` | owner/admin（admin 只能创建 editor/viewer） |
| `PATCH` | `/api/v1/admin/users/{id}/role` | owner/admin（admin 只能改 editor/viewer） |
| `DELETE` | `/api/v1/admin/users/{id}` | owner/admin（admin 只能移除 editor/viewer） |
| `POST` | `/api/v1/admin/users/{id}/reset-password` | owner/admin（同上） |
| `GET` | `/api/v1/admin/settings` | owner/admin |
| `PUT` | `/api/v1/admin/settings/guest-quota` | 仅 owner |
| `GET/PUT` | `/api/v1/admin/agent-types` | owner/admin |
| `GET` | `/api/v1/agent-types` | 登录用户（仅启用类型，隐藏 prompt） |
| `POST` | `/api/v1/documents` | owner/admin |
| `GET` | `/api/v1/documents` | 登录用户 |

开发环境自动创建三个演示账号（可通过环境变量覆盖，不提交真实密码）：

| 账号 | 角色 |
| --- | --- |
| `admin@demo.local` | 超级管理员 |
| `ops@demo.local` | 受控管理员 |
| `guest@demo.local` | 游客 |

生产环境 `SEED_DEMO_USERS=false`，首次超管通过部署脚本创建。

## 3. 游客每日检索配额

- 配置存于 `workspaces.settings.guest_daily_query_quota`，默认 `20`；
- 仅对 `viewer` 生效；每个游客账号独立计数；
- Redis key：`guestquota:<workspace>:<user>:<YYYYMMDD>`，按
  `Asia/Shanghai` 自然日重置，TTL 到次日 00:05；
- Lua 原子执行“读取-判断-递增”，避免并发绕过；
- 超管在后台修改后立即生效；
- 配额耗尽返回 `429` + `guest_quota_exceeded` + `Retry-After`；
- 配额在请求进入 LLM 之前扣减，避免失败重试造成无限成本。

## 4. 数字员工类型

为了不破坏已冻结的内部契约 v1.0.0，类型配置存于
`workspaces.settings.agent_types`，通过请求的 `metadata.agent_profile` 传给引擎：

```json
{
  "id": "0192f0e0-3000-7c2d-8e3f-0a1b2c3d4e5f",
  "name": "合同审查助手",
  "description": "面向合同条款的审查与风险提示",
  "mode": "agent",
  "system_prompt": "你是企业合同审查助手……",
  "allowed_tools": ["search_knowledge_base"],
  "enabled": true
}
```

- `owner/admin` 可创建、编辑、停用类型；
- 前端对话页选择类型后，网关校验并注入 `metadata.agent_profile`；
- 引擎 Writer/Planner 使用该 system prompt，不允许前端直接传任意 prompt；
- 默认类型为现有 `ops_assistant`，历史会话不受影响。

## 5. PDF 上传与摄取

本地演示走共享文件目录，生产切换 OSS：

1. `POST /api/v1/documents`（owner/admin）接收 PDF，校验 `application/pdf`、
   文件大小 ≤ 50MB、SHA-256 去重；
2. 网关保存到共享 `UPLOAD_DIR`，创建 `ingest_tasks`（queued）并调用引擎
   `POST /internal/v1/ingest/tasks`（契约已存在，`source.type=local`）；
3. 引擎后台执行：pypdf 提取文本 → 父子切片 → 百炼 Embedding（1024 维）→
   写 `documents/document_parent_chunks/document_chunks`；
4. 更新 `documents.status=ready`、`knowledge_bases.chunk_count` 与
   `ingest_tasks` 的 stage/progress/counters；
5. 管理后台展示上传任务与文档状态；检索立即可见新切片；
6. 失败时 `documents.status=failed` 并记录 `error_code/error_message`，可重试。

生产替换：`UPLOAD_DIR` → OSS，`source.type=oss`，网关签发临时下载 URL。

## 6. CI/CD 与阿里云部署（记录，暂不执行）

### 6.1 本地开发流水线

```
make fmt / make lint
  ├─ frontend: npm ci && npm run lint && npm run typecheck && npm run build
  ├─ gateway-go: gofmt -l && go vet ./... && go test ./...
  └─ ai-engine-py: ruff check . && pytest -q
scripts/validate_contracts.py
scripts/sync_architecture.py --check
```

### 6.2 GitHub Actions

- PR：路径过滤 + 三端并行 lint/test/build；契约校验；失败阻断合并；
- main：构建并推送三个镜像到阿里云 ACR（tag = git sha + semver）；
- 部署：先 staging（Compose/SAE），冒烟 `/readyz` + 一条真实 SSE；
- 生产：手动 approval + 数据库迁移 Job + 滚动发布 + 自动回滚。

### 6.3 阿里云拓扑（≤1000 元/月目标）

| 组件 | 选型 | 说明 |
| --- | --- | --- |
| 前端/网关 | ECS 2C4G 或 SAE | 同 VPC；网关保留 SSE 长连接 |
| AI 引擎 | ECS 2C4G 或 SAE | 解析/Embedding 任务异步化 |
| PostgreSQL | RDS PG 16 + pgvector | 生产必须启用 zhparser |
| Redis | 云 Redis 1G 主从 | 会话/令牌桶/游客配额 |
| 对象存储 | OSS | PDF 与抽取文本 |
| 镜像 | ACR 个人版 | CI 推送 |
| 密钥 | KMS/环境变量 | 禁止写入镜像 |
| 监控 | SLS + ARMS | 请求日志、TTFT、错误率 |

### 6.4 上线顺序

1. 数据库迁移与回滚脚本演练；
2. 部署 Redis/RDS/OSS，验证网络与 RLS；
3. 部署引擎 → 网关 → 前端；
4. 冒烟：登录、游客配额、上传 PDF、检索、SSE、看板；
5. 观察 24h 后再开放公网。

## 7. 验收标准

- 三种角色登录后，菜单/按钮/API 权限一致；受控管理员无法任命管理员或改配额；
- 游客第 N+1 次检索被 429 拒绝，次日自动恢复；
- 超管新增数字员工类型后，对话页可选择并使用自定义 system prompt；
- 超管上传 PDF 后，文档状态从 queued → ready，新内容可被检索与引用；
- 非 PDF、超大文件、重复文件、错误密码、越权请求均返回明确错误；
- Go/Python/前端测试与契约校验全部通过。

## 8. 本机验收结果

- `admin@demo.local` / `ops@demo.local` / `guest@demo.local` 登录成功；
- owner 把游客配额设为 2 后，guest 第 3 次请求返回
  `429 guest_quota_exceeded`，配额恢复为 20；
- admin 修改配额、创建 admin 均返回 403，创建 editor 成功；
- 游客访问 `/admin/users` 返回 403；
- 2 页中文 PDF 上传后 `documents.status=ready`、`ingest_tasks=succeeded`，
  新切片可被检索；
- 自定义“合同审查助手”通过 `/api/v1/agent-types` 创建，对话 `meta.agent_name`
  正确，并成功完成一次 SSE 回答；
- 截图见 `docs/assets/phase4-*.png`。

> 安全说明：演示密码只用于本地开发；生产必须关闭种子账号、替换密码、
> 启用 Secure Cookie，并为登录接口增加独立防爆破限流。
