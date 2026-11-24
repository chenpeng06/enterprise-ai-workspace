# ai-engine-py · FastAPI + LangGraph AI 引擎

文档解析、切片、Embedding、混合检索、Rerank 与数字员工多智能体编排。
**不承担**鉴权、限流、计费与业务 CRUD —— 这些属于 `gateway-go`。

## Phase 1/2 交付范围

- 可启动的 FastAPI 工程骨架（lifespan、异常处理、内部鉴权）；
- 配置与密钥管理（pydantic-settings，LLM / Embedding / Rerank 分离凭证）；
- 异步 SQLAlchemy + asyncpg 连接池；
- **运行时契约校验器**：直接加载
  `docs/contracts/ai-engine-internal-v1.schema.json`；
- `/internal/v1/health` 探针（PostgreSQL / LLM / Embedding 配置就绪度）；
- `app/rag/retriever.py`：向量 + PostgreSQL 全文 BM25 + 加权 RRF +
  可选 Rerank，返回完整检索透视与页码/坐标；
- `app/agents/ops_assistant.py`：LangGraph
  `Planner → RAG → Tools → Reviewer → Writer`，逐节点输出 SSE；
- `/internal/v1/retrieval/search` 与 `/internal/v1/chat/stream` 已完成；
- 真实 DeepSeek + 百炼 Embedding 全链路验收通过。

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
│   │   ├── deps.py                # 内部鉴权 + 依赖注入
│   │   ├── guards.py              # workspace / contract 头校验
│   │   └── v1/
│   │       ├── router.py
│   │       ├── health.py
│   │       ├── retrieval.py       # 非流式混合检索
│   │       └── chat.py            # SSE 流式问答
│   ├── schemas/                   # Pydantic 请求/响应模型
│   ├── rag/
│   │   ├── retriever.py           # 向量 + BM25 + RRF + Rerank
│   │   ├── embeddings.py          # OpenAI 兼容 Embedding
│   │   ├── reranker.py            # DashScope gte-rerank 客户端
│   │   └── rewrite.py             # Query 改写
│   ├── agents/ops_assistant.py    # LangGraph 数字员工 + SSE 事件
│   ├── tools/                     # 工具接口预留（当前模拟日志/状态）
│   └── services/llm.py            # DeepSeek / 百炼 OpenAI 兼容客户端
├── scripts/
│   ├── check_models.py            # 不打印 Key 的供应商连通性测试
│   └── seed_demo.py               # 写入演示知识库
└── tests/                         # 契约、检索、Agent、API 测试
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

健康响应示例（已配置 LLM/Embedding Key 时）：

```json
{
  "status": "ok",
  "service": "ai-engine-py",
  "version": "0.1.0",
  "contract_version": "1.0.0",
  "checks": {
    "postgres": {"status": "ok", "latency_ms": 3.2},
    "llm": {"status": "ok", "latency_ms": 0.01},
    "embedding": {"status": "ok", "latency_ms": 0.01}
  }
}
```

> `/health` 只检查配置是否就绪；真实供应商可用性运行
> `python scripts/check_models.py`。

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

## Phase 2 已实现（对应 docs/TASKS.md）

1. `app/rag/retriever.py`：
   - 同一查询下执行 pgvector 余弦召回与 PostgreSQL `content_tsv` 关键词召回；
   - 词项 OR 召回 + BM25（tf 从 tsvector positions 统计，df 走 GIN）；
   - 加权 RRF 融合、百炼 `gte-rerank-v2` 精排（未配置/非法 URL 时显式
     `enabled=false`，不生成伪分数）；
   - 返回各阶段得分/排名、rank_delta、页码、bbox、字符偏移。
2. `app/agents/ops_assistant.py`：
   - LangGraph 状态机：`Planner → RAG Retrieve → Tools → Reviewer → Writer`；
   - `mode=rag` 自动跳过 Planner/Tools；
   - Reviewer 在无证据或最高证据分低于阈值时拒答；
   - 通过异步队列实时 yield `thinking/tool_calling/reranking/retrieval/
     citation/generating/usage/done/error`。
3. API：
   - `POST /internal/v1/retrieval/search`（非流式透视）；
   - `POST /internal/v1/chat/stream`（SSE，15s 心跳，严格终态）。

## Phase 2 本地验收

```powershell
cd ai-engine-py

# 验证 DeepSeek + 百炼 Embedding（不会打印 Key）
.\.venv\Scripts\python.exe scripts\check_models.py

# 写入演示知识库（会调用一次真实 Embedding）
.\.venv\Scripts\python.exe scripts\seed_demo.py

# 运行全部测试
.\.venv\Scripts\python.exe -m pytest -q
```

真实 API 调用示例见仓库根目录 README；SSE 事件与契约逐条校验通过。
