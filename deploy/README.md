# deploy · 容器化与部署

## Phase 1 交付范围

- `docker-compose.yml`：本地 PostgreSQL（pgvector/pg16）与 Redis 一键启动；
- `initdb/01_schema.sql`：首次启动自动执行的完整建表脚本（与
  `docs/ARCHITECTURE.md` 中 DDL 同源）；
- 阿里云部署目录骨架与生产环境变量模板（`aliyun/`）。

各服务 Dockerfile、完整 stack 编排、阿里云资源编排脚本在 Phase 4 交付。

本机 Docker Desktop 采用 per-user 安装，程序位于 `D:\Docker\DockerDesktop`，
镜像/容器/卷数据盘位于 `D:\Docker\data`，无需管理员权限；完整环境信息见
[`docs/LOCAL_SETUP.md`](../docs/LOCAL_SETUP.md)。

## 目录结构

```
deploy/
├── docker-compose.yml       # 本地基础设施（postgres + redis）
├── .env.example             # 本地基础设施变量
├── initdb/
│   └── 01_schema.sql        # pgvector / 全文索引 / RLS 全量建表
├── verify/
│   └── 01_smoke.sql         # 可重复执行的数据库冒烟测试（事务回滚）
├── aliyun/
│   ├── README.md                 # 目标拓扑、成本约束、选型说明
│   ├── gateway.env.example       # 网关生产环境变量模板
│   └── ai-engine.env.example     # AI 引擎生产环境变量模板
└── README.md
```

## 本地启动

```powershell
cd deploy
Copy-Item .env.example .env
docker compose up -d --wait
docker compose ps
```

首次启动（`eaw-postgres-data` 卷为空）会自动执行 `initdb/01_schema.sql`。
已在 PostgreSQL 16.16 + pgvector 0.8.7 上实际跑通，扩展、19 张表/分区、
HNSW/GIN 索引、BM25 函数与 RLS 均验证通过。

若需要重新初始化（会删除本地数据）：

```powershell
docker compose down -v
docker compose up -d --wait
```

> 修改 DDL 后，已有数据卷不会自动重跑初始化脚本；开发环境可 `down -v` 重建，
> 其他环境应新增增量迁移。

## 连接信息

| 服务 | 地址 | 凭据 |
| --- | --- | --- |
| PostgreSQL | `127.0.0.1:5432` | `workspace / workspace`（见 `.env`） |
| Redis | `127.0.0.1:6379` | 无密码（生产使用 ACL） |

- gateway-go：`postgres://workspace:workspace@127.0.0.1:5432/workspace?sslmode=disable`
- ai-engine-py：`postgresql+asyncpg://workspace:workspace@127.0.0.1:5432/workspace`

## 校验建表结果

```powershell
docker compose exec -T postgres psql -U workspace -d workspace -c "\dt"
docker compose exec -T postgres psql -U workspace -d workspace `
  -c "SELECT extname, extversion FROM pg_extension ORDER BY 1;"
docker compose exec -T postgres psql -U workspace -d workspace `
  -c "SELECT indexname FROM pg_indexes WHERE indexname LIKE '%hnsw%' OR indexname LIKE '%fts%';"
```

预期扩展：`vector`、`pg_trgm`；若镜像/托管实例支持 `zhparser`，脚本会额外创建
`zh` 全文检索配置，否则回退 `simple` 并输出 NOTICE。

## 生产部署

见 `aliyun/README.md`。生产环境必须替换所有默认密码与 `INTERNAL_TOKEN`，
并启用 RLS 的非 owner 应用角色（脚本末尾附加固 SQL）。
