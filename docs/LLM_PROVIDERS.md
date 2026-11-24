# 模型供应商选型（DeepSeek / DashScope / 本地）

本文说明 `ai-engine-py` 的三类模型凭证如何组合。结论先给出：

- **DeepSeek 可以替换对话、Query 改写、Planner、Writer 等生成类调用**；
- **DeepSeek 官方 API 当前不提供 Embedding 与 Rerank**，这两类仍需
  DashScope（百炼）或本地模型；
- 因此三组配置必须独立：`LLM_*`、`EMBEDDING_*`、`RERANK_*`。

## 1. 能力矩阵

| 能力 | DeepSeek 官方 API | 阿里云百炼 | 本地部署 |
| --- | --- | --- | --- |
| Chat / 推理 / 结构化输出 | ✅ `deepseek-flash`、`deepseek-v4-pro` | ✅ qwen 系列 | 视模型而定 |
| Tool Calls（LangGraph 工具） | ✅（思考模式对 `tool_choice=required` 有限制） | ✅ | 视模型而定 |
| Streaming SSE | ✅ `stream=true` | ✅ | 视服务而定 |
| JSON Output | ✅ | ✅ | 视模型而定 |
| Embedding | ❌ 官方 API 无此端点 | ✅ `text-embedding-v3`（1024 维） | ✅ BGE-M3（1024 维） |
| Rerank | ❌ 官方 API 无此端点 | ✅ gte-rerank | ✅ bge-reranker-v2-m3 |

> 以上基于 DeepSeek 官方文档（Chat Completions 与 Models & Pricing）当前列出的
> 能力；供应商可能更新，接入前请复核最新 API Reference。

## 2. 推荐组合

### A. DeepSeek 对话 + 百炼 Embedding/Rerank（推荐的 API 组合）

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=sk-<deepseek-key>
CHAT_MODEL=deepseek-flash

EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_API_KEY=sk-<dashscope-key>
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIMENSIONS=1024

RERANK_BASE_URL=<百炼-rerank-endpoint>
RERANK_API_KEY=sk-<dashscope-key>
RERANK_MODEL=gte-rerank-v2
```

优点：生成成本低、上下文长；Embedding/Rerank 与现有 `vector(1024)` 完全兼容。

### B. DeepSeek 对话 + 本地 BGE（只需一个 API Key）

- Embedding：`BAAI/bge-m3`（1024 维）+ `sentence-transformers` / FlagEmbedding；
- Rerank：`BAAI/bge-reranker-v2-m3`；
- 优点：不依赖第二家 API；缺点：CPU 推理慢，需要额外内存/GPU。适合演示与离线环境。

### C. 只使用百炼（当前默认）

Phase 1 `.env.example` 默认即为百炼兼容模式；不配置 DeepSeek 也能运行，
只是没有 Key 时引擎健康状态为 `degraded`。

## 3. DeepSeek 接入要点

1. **Base URL**：OpenAI 兼容地址为 `https://api.deepseek.com`；若使用 OpenAI SDK，
   按其文档设置 `base_url`，不要重复拼接 `/v1/chat/completions`。
2. **模型名**：当前文档列出的对话模型为 `deepseek-flash` 与 `deepseek-v4-pro`。
   Phase 2 接入时通过 `GET /models` 或官方文档确认，不硬编码旧模型名。
3. **思考模式**：DeepSeek 默认可能开启 thinking；LangGraph 的工具调用建议关闭
   thinking（或在 `tool_choice` 上避免 `required`），以保证稳定的 JSON/工具参数。
   `choices[].message.reasoning_content` 可映射为契约里的
   `GeneratingData.reasoning_delta`。
4. **采样参数**：thinking 模式下 `temperature`/`top_p` 可能被忽略；Phase 2 的
   `GenerationConfig` 仍可传，但不要依赖其产生确定性输出。
5. **Token 计量**：使用 `usage` 字段（含缓存命中 token），网关按契约写入
   `request_logs`；Phase 2 的 Provider 适配层必须统一不同厂商的 usage 结构。
6. **内容与合规**：生产环境按数据合规要求选择供应商；不要把内部日志原文发送给
   未获批的外部模型。

## 4. 代码侧边界

Phase 1 已把 `Settings` 拆为：

```
LLM_BASE_URL / LLM_API_KEY / CHAT_MODEL
EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL / EMBEDDING_DIMENSIONS
RERANK_BASE_URL / RERANK_API_KEY / RERANK_MODEL
```

健康探针分别检查 `LLM_API_KEY` 与 `EMBEDDING_API_KEY`，不会再出现
"只配 DeepSeek Key 却误报 Embedding 可用"的情况。

Phase 2 实现模型客户端时，建议用统一的 Provider 接口：

```python
class ChatProvider(Protocol):
    async def stream(self, messages, tools=None) -> AsyncIterator[ChatChunk]: ...

class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class RerankProvider(Protocol):
    async def rerank(self, query: str, documents: list[str]) -> list[float]: ...
```

这样 DeepSeek/百炼/本地模型只是不同实现，RAG 与 LangGraph 层不感知厂商差异。

## 5. 官方文档

- DeepSeek Chat Completions：<https://api-docs.deepseek.com/api/create-chat-completion/>
- DeepSeek Models & Pricing：<https://api-docs.deepseek.com/quick_start/pricing/>
- DeepSeek List Models：<https://api-docs.deepseek.com/api/list-models/>
- 阿里云百炼：<https://help.aliyun.com/zh/model-studio/>
