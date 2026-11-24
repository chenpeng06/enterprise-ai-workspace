"""HybridRetriever 集成测试：真实 PostgreSQL + 假 Embedding/Reranker。

不调用外部模型，验证：
- 向量召回与 PostgreSQL 全文召回；
- BM25 计算、加权 RRF 排名；
- Rerank 精排、阈值筛选与排名变化；
- 页码/bbox/字符偏移等溯源元数据；
- 输出符合内部契约 RetrievalSearchResponse。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.contract import validate_instance
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.rag.retriever import HybridRetriever
from app.schemas.requests import RetrievalConfig, RewriteConfig


def _vector(axis: int) -> str:
    values = [0.0] * 1024
    values[axis] = 1.0
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


class FakeEmbeddingClient:
    async def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 1023


class FakeReranker:
    configured = True
    model = "fake-rerank"

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.1 if "rollback" in document else 0.9 for document in documents]


async def _cleanup(workspace_id: uuid.UUID) -> None:
    factory = get_session_factory(get_settings())
    async with factory() as session:
        await session.execute(
            text("SELECT set_config('app.workspace_id', :ws, true)"),
            {"ws": str(workspace_id)},
        )
        await session.execute(
            text("DELETE FROM workspaces WHERE id = :id"),
            {"id": workspace_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_hybrid_retrieval_funnel_and_contract() -> None:
    workspace_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    document_id = uuid.uuid4()
    parent_id = uuid.uuid4()
    chunk_a = uuid.uuid4()
    chunk_b = uuid.uuid4()
    factory = get_session_factory(get_settings())

    try:
        async with factory() as session:
            await session.execute(
                text("SELECT set_config('app.workspace_id', :ws, true)"),
                {"ws": str(workspace_id)},
            )
            await session.execute(
                text("INSERT INTO workspaces (id, slug, name) VALUES (:id, :slug, 'Phase2 Test')"),
                {"id": workspace_id, "slug": f"phase2-{workspace_id.hex[:12]}"},
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_bases "
                    "(id, workspace_id, name, chunk_count, avg_chunk_tokens) "
                    "VALUES (:id, :ws, 'Phase2 KB', 2, 20)"
                ),
                {"id": kb_id, "ws": workspace_id},
            )
            await session.execute(
                text(
                    "INSERT INTO documents "
                    "(id, workspace_id, knowledge_base_id, title, file_name, mime_type, "
                    "size_bytes, checksum_sha256, status) "
                    "VALUES (:id, :ws, :kb, '灰度发布规范', 'release.pdf', "
                    "'application/pdf', 1024, :checksum, 'ready')"
                ),
                {
                    "id": document_id,
                    "ws": workspace_id,
                    "kb": kb_id,
                    "checksum": "e" * 64,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO document_parent_chunks "
                    "(id, workspace_id, knowledge_base_id, document_id, chunk_index, content) "
                    "VALUES (:id, :ws, :kb, :doc, 0, '父切片')"
                ),
                {"id": parent_id, "ws": workspace_id, "kb": kb_id, "doc": document_id},
            )

            chunks = [
                (
                    chunk_a,
                    "灰度发布错误率超过阈值时自动回滚 rollback error rate threshold",
                    0,
                    0,
                ),
                (chunk_b, "季度故障演练计划 quarterly drill schedule", 1, 1),
            ]
            for chunk_id, content, axis, chunk_index in chunks:
                await session.execute(
                    text(
                        "INSERT INTO document_chunks "
                        "(id, workspace_id, knowledge_base_id, document_id, parent_chunk_id, "
                        "chunk_index, content, token_count, page_no, bbox, embedding) "
                        "VALUES (:id, :ws, :kb, :doc, :parent, :idx, :content, 20, 18, "
                        "CAST(:bbox AS jsonb), CAST(:vec AS vector))"
                    ),
                    {
                        "id": chunk_id,
                        "ws": workspace_id,
                        "kb": kb_id,
                        "doc": document_id,
                        "parent": parent_id,
                        "idx": chunk_index,
                        "content": content,
                        "bbox": '{"x0":0.1,"y0":0.2,"x1":0.9,"y1":0.3}',
                        "vec": _vector(axis),
                    },
                )
            await session.commit()

        retriever = HybridRetriever(embedding_client=FakeEmbeddingClient())
        config = RetrievalConfig(
            top_k=2,
            vector_top_k=5,
            lexical_top_k=5,
            enable_rerank=False,
            rewrite=RewriteConfig(enabled=False),
        )
        result = await retriever.retrieve(
            workspace_id=workspace_id,
            kb_ids=[kb_id],
            query="rollback error",
            config=config,
        )

        validate_instance(
            {"trace_id": result.trace_id, "diagnostics": result.diagnostics},
            "RetrievalSearchResponse",
        )
        assert result.selected
        assert result.selected[0].chunk_id == str(chunk_a)
        assert result.selected[0].citation_index == 1
        assert result.selected[0].bbox == {
            "x0": 0.1,
            "y0": 0.2,
            "x1": 0.9,
            "y1": 0.3,
        }
        assert result.selected[0].page_no == 18

        candidate_a = next(
            item for item in result.diagnostics["candidates"] if item["chunk_id"] == str(chunk_a)
        )
        assert candidate_a["vector_score"] > 0.99
        assert candidate_a["vector_rank"] == 1
        assert candidate_a["bm25_score"] is not None
        assert candidate_a["bm25_score"] > 0
        assert candidate_a["rrf_score"] is not None
        assert candidate_a["fused_rank"] is not None
        assert candidate_a["selected"] is True
        assert result.diagnostics["stages"]["lexical"]["scorer"] == "bm25"
        assert result.diagnostics["stages"]["rerank"]["enabled"] is False

        rerank_config = RetrievalConfig(
            top_k=1,
            vector_top_k=5,
            lexical_top_k=5,
            enable_rerank=True,
            min_rerank_score=0.5,
            rewrite=RewriteConfig(enabled=False),
        )
        reranked = await HybridRetriever(
            embedding_client=FakeEmbeddingClient(),
            reranker=FakeReranker(),
        ).retrieve(
            workspace_id=workspace_id,
            kb_ids=[kb_id],
            query="rollback error",
            config=rerank_config,
        )
        validate_instance(
            {"trace_id": reranked.trace_id, "diagnostics": reranked.diagnostics},
            "RetrievalSearchResponse",
        )
        assert reranked.diagnostics["stages"]["rerank"]["enabled"] is True
        assert reranked.diagnostics["stages"]["rerank"]["model"] == "fake-rerank"
        assert reranked.diagnostics["stages"]["rerank"]["passed"] == 1
        assert reranked.selected[0].chunk_id == str(chunk_b)
        assert reranked.selected[0].rerank_score == 0.9
        assert reranked.selected[0].citation_index == 1
        assert reranked.selected[0].rank_delta is not None
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL 不可用，跳过集成测试: {type(exc).__name__}")
    finally:
        try:
            await _cleanup(workspace_id)
        except SQLAlchemyError:
            pass
