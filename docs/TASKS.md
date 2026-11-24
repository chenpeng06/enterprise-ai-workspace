# 开发路线图与阶段执行规范 (Roadmap)

## Phase 1：项目脚手架、目录结构与跨语言接口契约
1. 在工作目录创建 `frontend/` (React+TS)、`gateway-go/` (Go+Gin)、`ai-engine-py/` (Python+FastAPI+LangGraph)、`deploy/` (Docker Compose 与阿里云部署配置) 的完整目录结构与基础依赖配置文件。
2. 明确定义 `gateway-go` 与 `ai-engine-py` 之间的内部 REST 与 SSE 流式通信接口契约（JSON Schema），需包含：
   - 异步文档解析与向量化任务触发接口；
   - 带检索透视元数据（改写后 Query、向量得分、BM25 得分、Rerank 得分、原文页码/坐标）的流式问答协议；
   - 多智能体执行步骤状态推送事件格式（如 `thinking`、`tool_calling`、`reranking`、`generating`）。
3. 给出 `PostgreSQL (pgvector)` 的完整建表 SQL（包含多租户隔离字段 `workspace_id`、父子文档切片表、全文检索索引与向量索引）。
4. **阶段交付物**：将上述目录说明、JSON Schema 契约与建表 SQL 完整写入 `docs/ARCHITECTURE.md`。

## Phase 2：Python AI 引擎 (`ai-engine-py`)
1. **混合检索与重排模块 (`rag/retriever.py`)**：
   - 使用异步 SQLAlchemy/Asyncpg 连接 `pgvector`，实现同一查询下的**向量相似度检索**与 **PostgreSQL 全文检索**；
   - 使用倒数排序融合（RRF）合并结果，并接入 Rerank 模型接口进行精排；
   - 返回结果必须附带完整的“检索漏斗诊断数据”（各阶段得分与排名变化）以及用于前端高亮的原文定位元数据。
2. **数字员工多智能体工作流 (`agents/ops_assistant.py`)**：
   - 使用 **LangGraph** 构建“企业研发运维数字员工”状态机；
   - 包含 `Planner（任务拆解）` -> `Tools（调用上述 RAG 检索规范 + 模拟日志分析工具）` -> `Reviewer（防幻觉核查，若检索分低于阈值触发拒答）` -> `Writer（生成带角标 [1][2] 的结构化报告）`；
   - 支持将每个节点的执行进度实时 yield 为标准 SSE 事件流。

## Phase 3：Go 高并发网关 (`gateway-go`) 与前端工作台 (`frontend`)
1. **Go 网关核心中间件与代理 (`gateway-go`)**：
   - 基于 Redis 实现分布式**令牌桶限流中间件**，并在触发限流时记录拦截日志供后台看板查询；
   - 实现反向代理与 **SSE 流式透传 Handler**：在转发 Python AI 引擎流式响应的同时，无侵入地解析并统计本次对话的 **首字延迟（TTFT）**、总耗时与 Token 消耗，异步写入 PostgreSQL 监控表。
2. **React + TypeScript 核心交互组件 (`frontend`)**：
   - 编写 **对话与原文高亮联动组件**：点击回答中的角标 `[1]` 时，右侧预览区自动定位并高亮对应文档片段；
   - 编写可折叠的 **“检索过程透视抽屉（Retrieval Inspector）”**，可视化展示向量得分、BM25 得分与 Rerank 重排前后对比；
   - 编写 **管理后台监控看板组件**，展示 Go 网关限流拦截次数、平均 TTFT 延迟趋势与知识库命中率。

## Phase 4：容器化与阿里云低成本部署 (`deploy`)
1. 编写各服务的标准 `Dockerfile` 与本地一键启动 `docker-compose.yml`。
2. 编写阿里云落地部署指南（ECS/SAE + RDS PostgreSQL + Redis + OSS + 函数计算 FC 事件驱动触发配置），确保月度预算控制在 1000 元以内。