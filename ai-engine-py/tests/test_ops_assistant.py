"""数字员工 LangGraph 工作流测试（使用假检索器与假 LLM，不访问外部 API）。"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from app.agents.ops_assistant import OpsAssistant
from app.contract import validate_instance
from app.core.config import Settings
from app.rag.retriever import ChunkCandidate, RetrievalResult
from app.schemas.requests import (
    AgentConfig,
    ChatStreamRequest,
    GenerationConfig,
    RetrievalConfig,
    RewriteConfig,
)
from app.services.llm import StreamDelta


class FakeRetriever:
    def __init__(self, selected: list[ChunkCandidate]) -> None:
        self.reranker = None
        self._selected = selected

    async def retrieve(self, **kwargs: object) -> RetrievalResult:
        selected = self._selected
        trace_id = str(kwargs.get("trace_id") or uuid.uuid4())
        citations = [item.to_contract() for item in selected]
        diagnostics = {
            "trace_id": trace_id,
            "query": {
                "original": "灰度发布错误率过高怎么办？",
                "rewritten": "灰度发布错误率过高回滚",
                "rewrite_model": None,
                "rewrite_latency_ms": 0.0,
                "language": "zh",
            },
            "config": RetrievalConfig(
                top_k=2,
                vector_top_k=5,
                lexical_top_k=5,
                enable_rerank=False,
                rewrite=RewriteConfig(enabled=False),
            ).model_dump(mode="json", exclude_none=True),
            "stages": {
                "vector": {
                    "model": "fake-embedding",
                    "dimensions": 1024,
                    "metric": "cosine",
                    "top_k": 5,
                    "candidates": len(selected),
                    "latency_ms": 1.0,
                },
                "lexical": {
                    "scorer": "bm25",
                    "config": "simple",
                    "top_k": 5,
                    "candidates": len(selected),
                    "latency_ms": 1.0,
                },
                "fusion": {
                    "algorithm": "rrf",
                    "rrf_k": 60,
                    "candidates": len(selected),
                    "latency_ms": 0.5,
                },
                "rerank": {
                    "enabled": False,
                    "model": None,
                    "top_k": 2,
                    "score_threshold": 0.2,
                    "candidates": 0,
                    "passed": 0,
                    "latency_ms": 0.0,
                },
            },
            "candidates": citations,
            "selected_count": len(selected),
            "total_latency_ms": 2.5,
        }
        return RetrievalResult(
            trace_id=trace_id,
            diagnostics=diagnostics,
            selected=selected,
            retrieval_ms=2.0,
            rerank_ms=0.0,
            total_ms=2.5,
        )


class FakeLLM:
    def __init__(self, answer: str = "根据《灰度发布规范》[1]，应先自动回滚并保留现场。") -> None:
        self.answer = answer
        self.model = "fake-chat"
        self.configured = True

    async def chat_json(self, messages, **_kwargs):
        return (
            {
                "steps": [
                    {"step_index": 0, "action": "retrieve", "description": "检索灰度规范"},
                    {
                        "step_index": 1,
                        "action": "tool",
                        "description": "分析错误日志",
                        "tool_name": "analyze_service_logs",
                    },
                    {"step_index": 2, "action": "review", "description": "核查证据"},
                    {"step_index": 3, "action": "answer", "description": "生成报告"},
                ]
            },
            {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "model": self.model,
            },
        )

    async def stream_chat(self, messages, **_kwargs) -> AsyncIterator[StreamDelta]:
        midpoint = max(1, len(self.answer) // 2)
        yield StreamDelta(content=self.answer[:midpoint])
        yield StreamDelta(
            content=self.answer[midpoint:],
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "model": self.model,
            },
        )


def _candidate() -> ChunkCandidate:
    return ChunkCandidate(
        chunk_id=str(uuid.uuid4()),
        parent_chunk_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        document_title="灰度发布规范 v2.3",
        file_name="release.pdf",
        chunk_index=0,
        chunk_type="text",
        section_path=["3 发布管理", "3.2 灰度发布"],
        page_no=18,
        bbox={"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
        char_start=100,
        char_end=220,
        content="灰度批次错误率连续 5 分钟超过 1% 时自动回滚，并保留现场。",
        token_count=48,
        vector_score=0.92,
        vector_rank=1,
        bm25_score=8.5,
        bm25_rank=1,
        rrf_score=0.03,
        fused_rank=1,
        selected=True,
        citation_index=1,
    )


def _request(mode: str = "agent") -> ChatStreamRequest:
    return ChatStreamRequest(
        workspace_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        query="灰度发布错误率过高，order-api 应该怎么处置？",
        kb_ids=[uuid.uuid4()],
        mode=mode,
        agent=AgentConfig(),
        retrieval=RetrievalConfig(
            top_k=2, enable_rerank=False, rewrite=RewriteConfig(enabled=False)
        ),
        generation=GenerationConfig(max_tokens=512),
    )


async def _collect(assistant: OpsAssistant, request: ChatStreamRequest) -> list[dict]:
    return [event async for event in assistant.stream_events(request, trace_id=str(uuid.uuid4()))]


@pytest.mark.asyncio
async def test_agent_streams_ordered_events_and_citations() -> None:
    settings = Settings(_env_file=None, llm_api_key="fake", embedding_api_key="fake")
    assistant = OpsAssistant(
        settings=settings,
        retriever=FakeRetriever([_candidate()]),
        llm_client=FakeLLM(),
    )
    request = _request()
    events = await _collect(assistant, request)
    names = [event["event"] for event in events]

    assert names[0] == "thinking"
    assert "retrieval" in names
    assert "citation" in names
    assert "generating" in names
    assert names[-2:] == ["usage", "done"]
    assert names.index("retrieval") < names.index("citation") < names.index("generating")

    retrieval_events = [item for item in events if item["event"] == "retrieval"]
    validate_instance(
        {
            "message_id": str(request.message_id),
            "diagnostics": retrieval_events[0]["data"]["diagnostics"],
        },
        "RetrievalData",
    )

    done = events[-1]["data"]
    validate_instance(done, "DoneData")
    assert done["finish_reason"] == "stop"
    assert done["citations"][0]["index"] == 1
    assert done["timings"]["ttft_ms"] >= 0
    nodes = {step["node"] for step in done["steps"]}
    assert {"planner", "rag_retrieve", "tools", "reviewer", "writer"} <= nodes


@pytest.mark.asyncio
async def test_agent_refuses_when_no_evidence() -> None:
    settings = Settings(_env_file=None, llm_api_key="fake", embedding_api_key="fake")
    assistant = OpsAssistant(
        settings=settings,
        retriever=FakeRetriever([]),
        llm_client=FakeLLM(),
    )
    request = _request()
    events = await _collect(assistant, request)
    names = [event["event"] for event in events]

    assert "retrieval" in names
    assert "citation" not in names
    done = events[-1]["data"]
    validate_instance(done, "DoneData")
    assert done["finish_reason"] == "refused"
    assert done["citations"] == []
    generating = [item for item in events if item["event"] == "generating"]
    assert generating
    assert "没有足够" in "".join(item["data"]["delta"] for item in generating)


@pytest.mark.asyncio
async def test_rag_mode_skips_planner_and_tools() -> None:
    settings = Settings(_env_file=None, llm_api_key="fake", embedding_api_key="fake")
    assistant = OpsAssistant(
        settings=settings,
        retriever=FakeRetriever([_candidate()]),
        llm_client=FakeLLM(),
    )
    events = await _collect(assistant, _request(mode="rag"))
    done = events[-1]["data"]
    nodes = {step["node"] for step in done["steps"]}
    assert "planner" not in nodes
    assert "tools" not in nodes
    assert "writer" in nodes
