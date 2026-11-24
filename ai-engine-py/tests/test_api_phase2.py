"""Phase 2 API 测试：SSE 元信息/终态、检索接口、租户头校验（全部使用替身）。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_ops_assistant, get_retriever
from app.main import app
from app.rag.retriever import RetrievalResult
from app.schemas.requests import RetrievalConfig

TOKEN = "dev-internal-token-change-me"


class FakeRetriever:
    async def retrieve(self, *, workspace_id, kb_ids, query, config, trace_id=None):
        trace = str(trace_id or uuid.uuid4())
        payload = RetrievalConfig().model_dump(mode="json", exclude_none=True)
        return RetrievalResult(
            trace_id=trace,
            diagnostics={
                "trace_id": trace,
                "query": {
                    "original": query,
                    "rewritten": query,
                    "rewrite_model": None,
                    "rewrite_latency_ms": 0.0,
                    "language": "zh",
                },
                "config": payload,
                "stages": {
                    "vector": {
                        "model": "fake",
                        "dimensions": 1024,
                        "metric": "cosine",
                        "top_k": config.vector_top_k,
                        "candidates": 0,
                        "latency_ms": 0.1,
                    },
                    "lexical": {
                        "scorer": "bm25",
                        "config": "simple",
                        "top_k": config.lexical_top_k,
                        "candidates": 0,
                        "latency_ms": 0.1,
                    },
                    "fusion": {
                        "algorithm": "rrf",
                        "rrf_k": config.fusion.rrf_k,
                        "candidates": 0,
                        "latency_ms": 0.0,
                    },
                    "rerank": {
                        "enabled": False,
                        "model": None,
                        "top_k": config.top_k,
                        "score_threshold": config.min_rerank_score,
                        "candidates": 0,
                        "passed": 0,
                        "latency_ms": 0.0,
                    },
                },
                "candidates": [],
                "selected_count": 0,
                "total_latency_ms": 0.2,
            },
        )


class FakeAssistant:
    async def stream_events(self, request, *, trace_id=None):
        message_id = str(request.message_id)
        yield {
            "event": "thinking",
            "data": {
                "node": "planner",
                "step_index": 0,
                "status": "started",
                "title": "测试",
                "latency_ms": 0.1,
            },
        }
        yield {
            "event": "generating",
            "data": {
                "message_id": message_id,
                "delta": "测试回答",
                "index": 0,
                "tokens_so_far": 4,
            },
        }
        yield {
            "event": "usage",
            "data": {
                "message_id": message_id,
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                    "model": "fake",
                },
            },
        }
        yield {
            "event": "done",
            "data": {
                "message_id": message_id,
                "finish_reason": "stop",
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                    "model": "fake",
                },
                "timings": {
                    "ttft_ms": 1.0,
                    "retrieval_ms": 0.1,
                    "rerank_ms": 0.0,
                    "generation_ms": 1.0,
                    "total_ms": 2.0,
                },
                "citations": [],
            },
        }


@pytest.fixture(autouse=True)
def _override_dependencies():
    app.dependency_overrides[get_retriever] = lambda: FakeRetriever()
    app.dependency_overrides[get_ops_assistant] = lambda: FakeAssistant()
    yield
    app.dependency_overrides.clear()


def _chat_payload() -> dict:
    return {
        "workspace_id": str(uuid.uuid4()),
        "conversation_id": str(uuid.uuid4()),
        "message_id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "query": "灰度发布错误率过高怎么办？",
        "kb_ids": [str(uuid.uuid4())],
        "mode": "rag",
    }


def test_chat_stream_sse_order_and_meta() -> None:
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/internal/v1/chat/stream",
            headers={"X-Internal-Token": TOKEN},
            json=_chat_payload(),
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = "".join(response.iter_text())

    events = [
        line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event: ")
    ]
    assert events == ["meta", "thinking", "generating", "usage", "done"]
    assert "id: 1" in body
    assert ": ping" not in body


def test_retrieval_search_returns_diagnostics() -> None:
    workspace = str(uuid.uuid4())
    payload = {
        "workspace_id": workspace,
        "kb_ids": [str(uuid.uuid4())],
        "query": "灰度回滚",
        "retrieval": {"top_k": 3, "enable_rerank": False},
    }
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/retrieval/search",
            headers={
                "X-Internal-Token": TOKEN,
                "X-Workspace-Id": workspace,
            },
            json=payload,
        )
    assert response.status_code == 200
    body = response.json()
    assert body["diagnostics"]["query"]["original"] == "灰度回滚"
    assert body["diagnostics"]["selected_count"] == 0


def test_chat_rejects_workspace_header_mismatch() -> None:
    payload = _chat_payload()
    with TestClient(app) as client:
        response = client.post(
            "/internal/v1/chat/stream",
            headers={
                "X-Internal-Token": TOKEN,
                "X-Workspace-Id": str(uuid.uuid4()),
            },
            json=payload,
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "workspace_mismatch"
