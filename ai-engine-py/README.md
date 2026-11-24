# ai-engine-py · FastAPI + LangGraph AI 引擎

文档解析、切片、Embedding、混合检索、Rerank 与数字员工多智能体编排。
**不承担**鉴权、限流、计费与业务 CRUD —— 这些属于 `gateway-go`。

## Phase 1 交付范围

- 可启动的 FastAPI 工程骨架（lifespan、异常处理、内部鉴权）；
- 配置与密钥管理（pydantic-settings，生产环境安全校验）；
- 异步 SQLAlchemy + asyncpg 连接池（Phase 2 检索器直接复用）；
- **运行时契约校验器**：直接加载
  `docs/contracts/ai-engine-internal-v1.schema.json`，避免 Python 侧出现
  “第二份手写契约”；
- `/internal/v1/health` 探针：并发探测 PostgreSQL / LLM 配置 / Embedding 配置，
  返回与契约一致的结构与契约版本；
- `app/rag`、`app/agents`、`app/tools` 领域包已就位，Phase 2 填充实现。

## 目录结构

```
ai-engine-py/
├── pyproject.toml                 # 依赖、ruff、pytest 配置
├── .env.example
├── Makefile
├── app/
│   ├── main.py                    # FastAPI 入口、lifespan、异常映射
│   ├── core/                      # 配置与日志
│   ├── contract/                  # JSON Schema 加载与运行时校验
│   ├── db/                        # asyncpg + SQLAlchemy 会话池
│   ├── api/
│   │   ├── deps.py                # X-Internal-Token 守卫
│   │   └── v1/
│   │       ├── router.py
│   │       └── health.py
│   ├── schemas/                   # Pydantic 响应模型
│   ├── rag/                       # Phase 2: retriever.py（混合检索 + RRF + Rerank）
│   ├── agents/                    # Phase 2: ops_assistant.py（LangGraph）
│   ├── tools/                     # Phase 2: 日志分析 / 服务状态工具
│   └── services/                  # 异步摄取与任务编排
└── tests/                         # 契约与健康探针冒烟测试
```

## 本地运行

要求 Python 3.12+（推荐用仓库根目录的 Docker Compose 先启动 PostgreSQL/Redis）。

```bash
cd ai-engine-py
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

验证：

```bash
curl -H "X-Internal-Token: dev-internal-token-change-me" \
     http://127.0.0.1:8000/internal/v1/health
pytest -q
ruff check .
```

健康响应示例（PostgreSQL 未启动时为 `503` + `postgres.status=down`）：

```json
{
  "status": "ok",
  "service": "ai-engine-py",
  "version": "0.1.0",
  "contract_version": "1.0.0",
  "checks": {
    "postgres": {"status": "ok", "latency_ms": 3.2},
    "llm": {"status": "degraded", "message": "未配置 LLM_API_KEY（Phase 1 允许，Phase 2 必需）"},
    "embedding": {"status": "degraded", "message": "未配置 LLM_API_KEY，Embedding 暂不可用"}
  }
}
```

## 契约校验

- v1 契约：`docs/contracts/ai-engine-internal-v1.schema.json`；
- 每个请求/事件在进入领域逻辑前调用
  `app.contract.validate_instance(payload, "$defs 名称")`；
- 契约文件默认向上查找仓库 `docs/contracts/`，容器内通过
  `CONTRACT_SCHEMA_PATH` 显式指定；
- 修改契约后运行：
  `python scripts/validate_contracts.py`（仓库根目录）与本目录 `pytest`。

## 模型供应商

`Settings` 将三类能力拆成独立凭证，避免换模型时误判：

- `LLM_*`：对话、Query 改写、Planner/Writer，可指向 DeepSeek、百炼或任意
  OpenAI 兼容端点；
- `EMBEDDING_*`：必须使用支持 1024 维的 Embedding 服务（百炼 `text-embedding-v3`
  或本地 BGE-M3）；
- `RERANK_*`：百炼 gte-rerank 或本地 `bge-reranker-v2-m3`。

DeepSeek 官方 API 当前不提供 Embedding/Rerank，不能只用一个 DeepSeek Key
替换全部模型。切换示例与能力矩阵见
[`docs/LLM_PROVIDERS.md`](../docs/LLM_PROVIDERS.md)。

## Phase 2 计划（对应 docs/TASKS.md）

1. `app/rag/retriever.py`：向量 + PostgreSQL 全文检索、RRF 融合、Rerank 精排，
   输出完整检索漏斗诊断与页码/坐标定位元数据；
2. `app/agents/ops_assistant.py`：LangGraph 状态机
   `Planner → Tools → Reviewer → Writer`，逐节点 yield 标准 SSE 事件；
3. `app/services/`：异步摄取任务执行器（解析 → 父子切片 → Embedding → 索引）。
