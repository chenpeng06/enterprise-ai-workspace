"""Phase 2 内部 API 请求模型。

与 docs/contracts/ai-engine-internal-v1.schema.json 保持一致；
进入领域逻辑前还会做一次 JSON Schema 校验。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FusionConfig(StrictModel):
    algorithm: Literal["rrf"] = "rrf"
    rrf_k: int = Field(default=60, ge=1, le=1000)


class RewriteConfig(StrictModel):
    enabled: bool = True
    model: str = Field(default="qwen-turbo", min_length=1, max_length=100)
    max_variants: int = Field(default=1, ge=1, le=3)


class RetrievalFilters(StrictModel):
    document_ids: list[UUID] = Field(default_factory=list, max_length=100)
    chunk_types: list[Literal["text", "table", "image_caption", "code", "heading"]] = Field(
        default_factory=list, max_length=5
    )
    created_after: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalConfig(StrictModel):
    top_k: int = Field(default=8, ge=1, le=50)
    vector_top_k: int = Field(default=40, ge=1, le=200)
    lexical_top_k: int = Field(default=40, ge=1, le=200)
    vector_weight: float = Field(default=0.65, ge=0, le=1)
    lexical_weight: float = Field(default=0.35, ge=0, le=1)
    min_vector_score: float = 0.0
    min_rerank_score: float = 0.2
    enable_rerank: bool = True
    rerank_model: str = Field(default="bge-reranker-v2-m3", min_length=1, max_length=100)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    rewrite: RewriteConfig = Field(default_factory=RewriteConfig)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class ReviewerConfig(StrictModel):
    enabled: bool = True
    min_context_score: float = 0.25
    max_unsupported_claims: int = Field(default=0, ge=0, le=10)
    refusal_message: str = Field(
        default="当前知识库中没有足够可靠的依据回答该问题，请补充相关文档或联系知识库管理员。",
        max_length=500,
    )


class PlannerConfig(StrictModel):
    enabled: bool = True
    max_plan_steps: int = Field(default=6, ge=1, le=10)


class AgentConfig(StrictModel):
    name: Literal["ops_assistant"] = "ops_assistant"
    max_steps: int = Field(default=12, ge=1, le=30)
    enable_tools: bool = True
    allowed_tools: list[str] = Field(
        default_factory=lambda: [
            "search_knowledge_base",
            "analyze_service_logs",
            "query_service_status",
        ],
        max_length=16,
    )
    reviewer: ReviewerConfig = Field(default_factory=ReviewerConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)


class GenerationConfig(StrictModel):
    model: str = Field(default="qwen-plus", min_length=1, max_length=100)
    temperature: float = Field(default=0.2, ge=0, le=2)
    top_p: float = Field(default=0.8, ge=0, le=1)
    max_tokens: int = Field(default=2048, ge=64, le=8192)
    stop: list[str] = Field(default_factory=list, max_length=4)
    citation_style: Literal["numeric", "footnote"] = "numeric"
    response_format: Literal["markdown", "text"] = "markdown"


class ChatHistoryItem(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatStreamRequest(StrictModel):
    workspace_id: UUID
    conversation_id: UUID
    message_id: UUID
    user_id: UUID
    query: str = Field(min_length=1, max_length=4000)
    kb_ids: list[UUID] = Field(min_length=1, max_length=10)
    mode: Literal["rag", "agent"] = "rag"
    agent: AgentConfig | None = None
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    history: list[ChatHistoryItem] = Field(default_factory=list, max_length=20)
    locale: str = Field(default="zh-CN", min_length=2, max_length=16)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def resolved_agent(self) -> AgentConfig:
        return self.agent or AgentConfig()


class RetrievalSearchRequest(StrictModel):
    workspace_id: UUID
    kb_ids: list[UUID] = Field(min_length=1, max_length=10)
    query: str = Field(min_length=1, max_length=4000)
    retrieval: RetrievalConfig
    request_id: UUID | None = None
