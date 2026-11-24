"""混合检索与重排（Phase 2 核心）。

流程：
    Query 改写 → 向量召回 + PostgreSQL 全文召回 → 加权 RRF → 可选 Rerank
    → 阈值筛选/角标编号 → RetrievalDiagnostics

设计约束：
- 向量与 BM25 在同一 workspace / kb_ids 过滤条件下执行；
- 不使用伪 Rerank 分数：未配置 Rerank 供应商时显式关闭精排；
- 所有候选保留各阶段得分、排名与原文定位元数据，供前端“检索透视抽屉”使用。
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.rag.embeddings import EmbeddingError, OpenAICompatibleEmbeddingClient
from app.rag.reranker import DashScopeReranker, RerankError, RerankNotConfigured
from app.rag.rewrite import QueryRewriter
from app.schemas.requests import RetrievalConfig
from app.services.llm import OpenAICompatibleChatClient

logger = logging.getLogger(__name__)

_TSV_ENTRY = re.compile(r"'((?:[^']|'')*)':([0-9,]+)")
_TOKEN_COUNT = 4
_MAX_DIAGNOSTIC_CANDIDATES = 100
_MAX_RERANK_CANDIDATES = 50
_BM25_K1 = 1.2
_BM25_B = 0.75


class RetrievalError(RuntimeError):
    """检索链路失败（数据库/Embedding/内部错误）。"""


@dataclass(slots=True)
class ChunkCandidate:
    chunk_id: str
    parent_chunk_id: str | None
    document_id: str
    document_title: str
    file_name: str | None
    chunk_index: int
    chunk_type: str
    section_path: list[str]
    page_no: int | None
    bbox: dict[str, float] | None
    char_start: int | None
    char_end: int | None
    content: str
    token_count: int
    vector_score: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    rrf_score: float | None = None
    fused_rank: int | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None
    selected: bool = False
    citation_index: int | None = None

    @property
    def rank_delta(self) -> int | None:
        if self.fused_rank is None or self.rerank_rank is None:
            return None
        return self.fused_rank - self.rerank_rank

    def to_contract(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chunk_id": self.chunk_id,
            "parent_chunk_id": self.parent_chunk_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "chunk_index": self.chunk_index,
            "chunk_type": self.chunk_type,
            "section_path": self.section_path,
            "page_no": self.page_no,
            "page_span": [self.page_no, self.page_no] if self.page_no is not None else None,
            "bbox": self.bbox,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "content_preview": self.content[:800],
            "token_count": self.token_count,
            "vector_score": _round(self.vector_score),
            "vector_rank": self.vector_rank,
            "bm25_score": _round(self.bm25_score),
            "bm25_rank": self.bm25_rank,
            "rrf_score": _round(self.rrf_score, 8),
            "fused_rank": self.fused_rank,
            "rerank_score": _round(self.rerank_score),
            "rerank_rank": self.rerank_rank,
            "rank_delta": self.rank_delta,
            "selected": self.selected,
            "citation_index": self.citation_index,
        }
        if self.file_name:
            payload["file_name"] = self.file_name
        return payload


@dataclass(slots=True)
class RetrievalResult:
    trace_id: str
    diagnostics: dict[str, Any]
    selected: list[ChunkCandidate] = field(default_factory=list)
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    total_ms: float = 0.0
    rerank_error: str | None = None
    rewrite_usage: dict[str, Any] | None = None


class HybridRetriever:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        embedding_client: Any | None = None,
        reranker: Any | None = None,
        rewriter: QueryRewriter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or get_session_factory(self.settings)
        self.embedding_client = embedding_client or OpenAICompatibleEmbeddingClient(self.settings)

        if reranker is None:
            candidate = DashScopeReranker(self.settings)
            self.reranker = candidate if candidate.configured else None
        else:
            self.reranker = reranker

        if rewriter is None:
            llm_client = OpenAICompatibleChatClient(self.settings)
            self.rewriter = QueryRewriter(llm_client) if llm_client.configured else None
        else:
            self.rewriter = rewriter

    async def retrieve(
        self,
        *,
        workspace_id: str | UUID,
        kb_ids: list[str | UUID],
        query: str,
        config: RetrievalConfig | None = None,
        trace_id: str | UUID | None = None,
    ) -> RetrievalResult:
        cfg = config or RetrievalConfig()
        trace = str(trace_id or uuid4())
        started = time.perf_counter()

        rewritten = query
        rewrite_model: str | None = None
        rewrite_ms = 0.0
        rewrite_usage: dict[str, Any] | None = None
        if cfg.rewrite.enabled and self.rewriter is not None:
            try:
                rewritten, rewrite_model, rewrite_ms, rewrite_usage = await self.rewriter.rewrite(
                    query
                )
            except Exception as exc:
                logger.warning("Query 改写异常，使用原始 Query: %s", exc)

        vector_started = time.perf_counter()
        try:
            query_vector = await self.embedding_client.embed_query(rewritten)
        except EmbeddingError as exc:
            raise RetrievalError(f"Embedding 失败: {exc}") from exc
        except Exception as exc:
            raise RetrievalError(f"Embedding 异常: {type(exc).__name__}") from exc
        embedding_ms = (time.perf_counter() - vector_started) * 1000

        try:
            async with self.session_factory() as session:
                await session.execute(
                    text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                    {"workspace_id": str(workspace_id)},
                )
                sql_started = time.perf_counter()
                vector_rows = await self._vector_search(
                    session,
                    workspace_id=workspace_id,
                    kb_ids=kb_ids,
                    query_vector=query_vector,
                    config=cfg,
                )
                vector_sql_ms = (time.perf_counter() - sql_started) * 1000
                lexical_started = time.perf_counter()
                lexical_rows, lexical_config = await self._lexical_search(
                    session,
                    workspace_id=workspace_id,
                    kb_ids=kb_ids,
                    query=rewritten,
                    config=cfg,
                )
                lexical_rows = await self._score_bm25(
                    session,
                    workspace_id=workspace_id,
                    kb_ids=kb_ids,
                    query=rewritten,
                    rows=lexical_rows,
                    config=cfg,
                )
                lexical_ms = (time.perf_counter() - lexical_started) * 1000
        except RetrievalError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("混合检索数据库失败")
            raise RetrievalError(f"检索数据库失败: {type(exc).__name__}") from exc
        except Exception as exc:
            logger.exception("混合检索未知失败")
            raise RetrievalError(f"检索失败: {type(exc).__name__}") from exc
        vector_stage_ms = embedding_ms + vector_sql_ms

        fusion_started = time.perf_counter()
        candidates = self._fuse(
            vector_rows=vector_rows,
            lexical_rows=lexical_rows,
            config=cfg,
        )
        fusion_ms = (time.perf_counter() - fusion_started) * 1000

        rerank_started = time.perf_counter()
        rerank_error: str | None = None
        rerank_enabled = bool(cfg.enable_rerank and self.reranker is not None)
        if rerank_enabled:
            try:
                await self._apply_rerank(
                    candidates,
                    query=rewritten,
                    config=cfg,
                )
            except RerankNotConfigured as exc:
                rerank_enabled = False
                rerank_error = str(exc)
                logger.warning("Rerank 未配置，降级为 RRF 排序: %s", exc)
            except Exception as exc:
                rerank_enabled = False
                rerank_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Rerank 失败，降级为 RRF 排序: %s", exc)
        rerank_ms = (time.perf_counter() - rerank_started) * 1000

        selected = self._select(candidates, config=cfg, rerank_enabled=rerank_enabled)
        ordered = self._diagnostic_order(candidates)
        candidates_for_diagnostics = ordered[:_MAX_DIAGNOSTIC_CANDIDATES]

        total_ms = (time.perf_counter() - started) * 1000
        retrieval_ms = rewrite_ms + vector_stage_ms + lexical_ms + fusion_ms

        diagnostics: dict[str, Any] = {
            "trace_id": trace,
            "query": {
                "original": query,
                "rewritten": rewritten,
                "rewrite_model": rewrite_model,
                "rewrite_latency_ms": _round(rewrite_ms),
                "language": _detect_language(query),
            },
            "config": cfg.model_dump(mode="json", exclude_none=True),
            "stages": {
                "vector": {
                    "model": self.settings.embedding_model,
                    "dimensions": self.settings.embedding_dimensions,
                    "metric": "cosine",
                    "top_k": cfg.vector_top_k,
                    "candidates": len(vector_rows),
                    "latency_ms": _round(vector_stage_ms),
                },
                "lexical": {
                    "scorer": "bm25",
                    "config": lexical_config,
                    "top_k": cfg.lexical_top_k,
                    "candidates": len(lexical_rows),
                    "latency_ms": _round(lexical_ms),
                },
                "fusion": {
                    "algorithm": "rrf",
                    "rrf_k": cfg.fusion.rrf_k,
                    "candidates": len(candidates),
                    "latency_ms": _round(fusion_ms),
                },
                "rerank": {
                    "enabled": rerank_enabled,
                    "model": cfg.rerank_model if rerank_enabled else None,
                    "top_k": cfg.top_k,
                    "score_threshold": cfg.min_rerank_score,
                    "candidates": min(len(candidates), _MAX_RERANK_CANDIDATES),
                    "passed": sum(
                        1
                        for candidate in candidates
                        if candidate.rerank_score is not None
                        and candidate.rerank_score >= cfg.min_rerank_score
                    ),
                    "latency_ms": _round(rerank_ms),
                },
            },
            "candidates": [candidate.to_contract() for candidate in candidates_for_diagnostics],
            "selected_count": len(selected),
            "total_latency_ms": _round(total_ms),
        }

        return RetrievalResult(
            trace_id=trace,
            diagnostics=diagnostics,
            selected=selected,
            retrieval_ms=_round(retrieval_ms),
            rerank_ms=_round(rerank_ms),
            total_ms=_round(total_ms),
            rerank_error=rerank_error,
            rewrite_usage=rewrite_usage,
        )

    async def _vector_search(
        self,
        session: AsyncSession,
        *,
        workspace_id: str | UUID,
        kb_ids: list[str | UUID],
        query_vector: list[float],
        config: RetrievalConfig,
    ) -> list[dict[str, Any]]:
        filter_sql, filter_params = self._filter_sql(config)
        sql = f"""
            SELECT
                c.id::text AS chunk_id,
                c.parent_chunk_id::text AS parent_chunk_id,
                c.document_id::text AS document_id,
                d.title AS document_title,
                d.file_name,
                c.chunk_index,
                c.chunk_type::text AS chunk_type,
                c.content,
                c.token_count,
                c.page_no,
                c.bbox,
                c.char_start,
                c.char_end,
                c.section_path,
                1 - (c.embedding <=> CAST(:query_vec AS vector)) AS vector_score
            FROM document_chunks c
            JOIN documents d
              ON d.id = c.document_id
             AND d.workspace_id = c.workspace_id
            WHERE c.workspace_id = CAST(:workspace_id AS uuid)
              AND c.knowledge_base_id = ANY(CAST(:kb_ids AS uuid[]))
              AND d.status = 'ready'
              AND d.deleted_at IS NULL
              AND c.embedding IS NOT NULL
              {filter_sql}
            ORDER BY c.embedding <=> CAST(:query_vec AS vector)
            LIMIT :vector_limit
        """
        params = {
            "workspace_id": str(workspace_id),
            "kb_ids": _uuid_array(kb_ids),
            "query_vec": _vector_literal(query_vector),
            "vector_limit": config.vector_top_k,
            **filter_params,
        }
        rows = (await session.execute(text(sql), params)).mappings().all()
        result: list[dict[str, Any]] = []
        for rank, row in enumerate(rows, start=1):
            candidate = self._row_to_candidate(row)
            candidate["vector_score"] = float(row["vector_score"] or 0.0)
            candidate["vector_rank"] = rank
            result.append(candidate)
        return result

    async def _lexical_search(
        self,
        session: AsyncSession,
        *,
        workspace_id: str | UUID,
        kb_ids: list[str | UUID],
        query: str,
        config: RetrievalConfig,
    ) -> tuple[list[dict[str, Any]], str]:
        meta = (
            (
                await session.execute(
                    text(
                        """
                    SELECT app.fts_config()::text AS fts_config,
                           tsvector_to_array(to_tsvector(app.fts_config(), :query)) AS terms
                    """
                    ),
                    {"query": query},
                )
            )
            .mappings()
            .first()
        )
        fts_config = str(meta["fts_config"]) if meta else "simple"
        terms = list(meta["terms"] or []) if meta else []
        if not terms:
            return [], fts_config

        # plainto_tsquery 默认 AND；多词查询改用逐词 OR，提升召回。
        # BM25 仍按各词项 tf/df 累加，不改变打分口径。
        terms = [str(term) for term in terms[:20] if str(term)]
        if not terms:
            return [], fts_config
        tsquery_sql = (
            "("
            + " || ".join(
                f"plainto_tsquery(app.fts_config(), :term_{index})" for index, _ in enumerate(terms)
            )
            + ")"
        )
        term_params = {f"term_{index}": term for index, term in enumerate(terms)}

        filter_sql, filter_params = self._filter_sql(config)
        sql = f"""
            SELECT
                c.id::text AS chunk_id,
                c.parent_chunk_id::text AS parent_chunk_id,
                c.document_id::text AS document_id,
                d.title AS document_title,
                d.file_name,
                c.chunk_index,
                c.chunk_type::text AS chunk_type,
                c.content,
                c.token_count,
                c.page_no,
                c.bbox,
                c.char_start,
                c.char_end,
                c.section_path,
                c.content_tsv::text AS tsv_text,
                ts_rank_cd(c.content_tsv, {tsquery_sql}, 32) AS lexical_score
            FROM document_chunks c
            JOIN documents d
              ON d.id = c.document_id
             AND d.workspace_id = c.workspace_id
            WHERE c.workspace_id = CAST(:workspace_id AS uuid)
              AND c.knowledge_base_id = ANY(CAST(:kb_ids AS uuid[]))
              AND d.status = 'ready'
              AND d.deleted_at IS NULL
              AND c.content_tsv @@ {tsquery_sql}
              {filter_sql}
            ORDER BY lexical_score DESC
            LIMIT :lexical_limit
        """
        params = {
            "workspace_id": str(workspace_id),
            "kb_ids": _uuid_array(kb_ids),
            "lexical_limit": config.lexical_top_k,
            **term_params,
            **filter_params,
        }
        rows = (await session.execute(text(sql), params)).mappings().all()
        result = [self._row_to_candidate(row) for row in rows]
        for row, candidate in zip(rows, result, strict=False):
            candidate["tsv_text"] = row["tsv_text"]
            candidate["lexical_score"] = float(row["lexical_score"] or 0.0)
        return result, fts_config

    async def _score_bm25(
        self,
        session: AsyncSession,
        *,
        workspace_id: str | UUID,
        kb_ids: list[str | UUID],
        query: str,
        rows: list[dict[str, Any]],
        config: RetrievalConfig,
    ) -> list[dict[str, Any]]:
        if not rows:
            return rows

        meta = (
            (
                await session.execute(
                    text(
                        """
                    SELECT tsvector_to_array(to_tsvector(app.fts_config(), :query)) AS terms
                    """
                    ),
                    {"query": query},
                )
            )
            .mappings()
            .first()
        )
        terms = list(meta["terms"] or []) if meta else []
        if not terms:
            return rows

        filter_sql, filter_params = self._filter_sql(config)
        stats = (
            (
                await session.execute(
                    text(
                        """
                    SELECT coalesce(sum(chunk_count), 0)::bigint AS n_docs,
                           coalesce(
                               sum(chunk_count * avg_chunk_tokens)
                               / nullif(sum(chunk_count), 0),
                               0
                           ) AS avgdl
                    FROM knowledge_bases
                    WHERE workspace_id = CAST(:workspace_id AS uuid)
                      AND id = ANY(CAST(:kb_ids AS uuid[]))
                    """
                    ),
                    {
                        "workspace_id": str(workspace_id),
                        "kb_ids": _uuid_array(kb_ids),
                    },
                )
            )
            .mappings()
            .first()
        )
        n_docs = int((stats or {}).get("n_docs") or 0)
        avgdl = float((stats or {}).get("avgdl") or 0.0)

        if n_docs <= 1:
            fallback = (
                (
                    await session.execute(
                        text(
                            f"""
                        SELECT count(*)::bigint AS n_docs,
                               coalesce(avg(c.token_count), 0) AS avgdl
                        FROM document_chunks c
                        JOIN documents d
                          ON d.id = c.document_id
                         AND d.workspace_id = c.workspace_id
                        WHERE c.workspace_id = CAST(:workspace_id AS uuid)
                          AND c.knowledge_base_id = ANY(CAST(:kb_ids AS uuid[]))
                          AND d.status = 'ready'
                          AND d.deleted_at IS NULL
                          {filter_sql}
                        """
                        ),
                        {
                            "workspace_id": str(workspace_id),
                            "kb_ids": _uuid_array(kb_ids),
                            **filter_params,
                        },
                    )
                )
                .mappings()
                .first()
            )
            n_docs = int((fallback or {}).get("n_docs") or 0)
            avgdl = float((fallback or {}).get("avgdl") or 0.0)

        if avgdl <= 0:
            avgdl = max(
                1.0,
                sum(
                    max(1, row.get("token_count") or _estimate_tokens(row["content"]))
                    for row in rows
                )
                / len(rows),
            )

        term_stats: list[tuple[str, int]] = []
        for term in terms[:20]:
            df = (
                await session.execute(
                    text(
                        f"""
                        SELECT count(*)::bigint AS df
                        FROM document_chunks c
                        JOIN documents d
                          ON d.id = c.document_id
                         AND d.workspace_id = c.workspace_id
                        WHERE c.workspace_id = CAST(:workspace_id AS uuid)
                          AND c.knowledge_base_id = ANY(CAST(:kb_ids AS uuid[]))
                          AND d.status = 'ready'
                          AND d.deleted_at IS NULL
                          AND c.content_tsv @@ plainto_tsquery(app.fts_config(), :term)
                          {filter_sql}
                        """
                    ),
                    {
                        "workspace_id": str(workspace_id),
                        "kb_ids": _uuid_array(kb_ids),
                        "term": term,
                        **filter_params,
                    },
                )
            ).scalar_one()
            term_stats.append((str(term), int(df)))

        for row in rows:
            tf_map = _term_frequencies(row.get("tsv_text") or "", [term for term, _ in term_stats])
            doc_len = int(row.get("token_count") or _estimate_tokens(row["content"]))
            score = 0.0
            for term, df in term_stats:
                tf = tf_map.get(term, 0)
                if tf <= 0:
                    continue
                score += _bm25(tf, doc_len, avgdl, df, n_docs)
            row["bm25_score"] = score

        rows.sort(key=lambda row: row.get("bm25_score") or 0.0, reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["bm25_rank"] = rank
        return rows

    def _fuse(
        self,
        *,
        vector_rows: list[dict[str, Any]],
        lexical_rows: list[dict[str, Any]],
        config: RetrievalConfig,
    ) -> list[ChunkCandidate]:
        candidates: dict[str, ChunkCandidate] = {}

        for row in vector_rows:
            candidate = self._candidate_from_dict(row)
            candidate.vector_score = row.get("vector_score")
            candidate.vector_rank = row.get("vector_rank")
            candidates[candidate.chunk_id] = candidate

        for row in lexical_rows:
            existing = candidates.get(row["chunk_id"])
            if existing is None:
                existing = self._candidate_from_dict(row)
                candidates[existing.chunk_id] = existing
            existing.bm25_score = row.get("bm25_score")
            existing.bm25_rank = row.get("bm25_rank")

        rrf_k = max(1, config.fusion.rrf_k)
        for candidate in candidates.values():
            score = 0.0
            if candidate.vector_rank is not None:
                score += config.vector_weight / (rrf_k + candidate.vector_rank)
            if candidate.bm25_rank is not None:
                score += config.lexical_weight / (rrf_k + candidate.bm25_rank)
            candidate.rrf_score = score

        ordered = sorted(
            candidates.values(),
            key=lambda item: (
                item.rrf_score or 0.0,
                item.vector_score or 0.0,
                item.bm25_score or 0.0,
            ),
            reverse=True,
        )
        for rank, candidate in enumerate(ordered, start=1):
            candidate.fused_rank = rank
        return ordered

    async def _apply_rerank(
        self,
        candidates: list[ChunkCandidate],
        *,
        query: str,
        config: RetrievalConfig,
    ) -> None:
        if self.reranker is None or not candidates:
            raise RerankNotConfigured("Rerank 未启用")
        subset = candidates[:_MAX_RERANK_CANDIDATES]
        scores = await self.reranker.rerank(query, [item.content for item in subset])
        if len(scores) != len(subset):
            raise RerankError(f"Rerank 分数数量异常: {len(scores)}/{len(subset)}")
        for candidate, score in zip(subset, scores, strict=False):
            candidate.rerank_score = float(score)

        reranked = sorted(
            (candidate for candidate in subset if candidate.rerank_score is not None),
            key=lambda item: item.rerank_score or 0.0,
            reverse=True,
        )
        for rank, candidate in enumerate(reranked, start=1):
            candidate.rerank_rank = rank
        logger.debug("Rerank 完成: candidates=%d", len(subset))

    def _select(
        self,
        candidates: list[ChunkCandidate],
        *,
        config: RetrievalConfig,
        rerank_enabled: bool,
    ) -> list[ChunkCandidate]:
        if rerank_enabled and any(item.rerank_score is not None for item in candidates):
            pool = sorted(
                (item for item in candidates if item.rerank_score is not None),
                key=lambda item: (item.rerank_score or 0.0, item.rrf_score or 0.0),
                reverse=True,
            )
            selected = [
                item for item in pool if (item.rerank_score or 0.0) >= config.min_rerank_score
            ][: config.top_k]
        else:
            pool = [
                item
                for item in candidates
                if item.vector_score is None
                or item.vector_score >= config.min_vector_score
            ]
            selected = sorted(
                pool,
                key=lambda item: item.fused_rank or 10**9,
            )[: config.top_k]

        for index, candidate in enumerate(selected, start=1):
            candidate.selected = True
            candidate.citation_index = index
        return selected

    @staticmethod
    def _diagnostic_order(candidates: list[ChunkCandidate]) -> list[ChunkCandidate]:
        return sorted(
            candidates,
            key=lambda item: (
                item.rerank_rank if item.rerank_rank is not None else 10**6,
                item.fused_rank if item.fused_rank is not None else 10**6,
                item.vector_rank if item.vector_rank is not None else 10**6,
            ),
        )

    @staticmethod
    def _row_to_candidate(row: Any) -> dict[str, Any]:
        return {
            "chunk_id": str(row["chunk_id"]),
            "parent_chunk_id": str(row["parent_chunk_id"]) if row["parent_chunk_id"] else None,
            "document_id": str(row["document_id"]),
            "document_title": str(row["document_title"]),
            "file_name": row["file_name"],
            "chunk_index": int(row["chunk_index"]),
            "chunk_type": str(row["chunk_type"]),
            "content": str(row["content"]),
            "token_count": int(row["token_count"] or 0),
            "page_no": int(row["page_no"]) if row["page_no"] is not None else None,
            "bbox": _json_object(row["bbox"]),
            "char_start": int(row["char_start"]) if row["char_start"] is not None else None,
            "char_end": int(row["char_end"]) if row["char_end"] is not None else None,
            "section_path": list(row["section_path"] or []),
        }

    @classmethod
    def _candidate_from_dict(cls, row: dict[str, Any]) -> ChunkCandidate:
        return ChunkCandidate(
            chunk_id=row["chunk_id"],
            parent_chunk_id=row["parent_chunk_id"],
            document_id=row["document_id"],
            document_title=row["document_title"],
            file_name=row.get("file_name"),
            chunk_index=row["chunk_index"],
            chunk_type=row["chunk_type"],
            section_path=row.get("section_path") or [],
            page_no=row.get("page_no"),
            bbox=row.get("bbox"),
            char_start=row.get("char_start"),
            char_end=row.get("char_end"),
            content=row["content"],
            token_count=row.get("token_count") or 0,
            bm25_score=row.get("bm25_score"),
        )

    @staticmethod
    def _filter_sql(config: RetrievalConfig) -> tuple[str, dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        filters = config.filters
        if filters.document_ids:
            clauses.append("AND c.document_id = ANY(CAST(:filter_document_ids AS uuid[]))")
            params["filter_document_ids"] = _uuid_array(filters.document_ids)
        if filters.chunk_types:
            clauses.append("AND c.chunk_type::text = ANY(CAST(:filter_chunk_types AS text[]))")
            params["filter_chunk_types"] = _text_array(filters.chunk_types)
        if filters.created_after:
            clauses.append("AND d.created_at >= :filter_created_after")
            params["filter_created_after"] = filters.created_after
        if filters.metadata:
            clauses.append("AND d.metadata @> CAST(:filter_metadata AS jsonb)")
            params["filter_metadata"] = json.dumps(filters.metadata, ensure_ascii=False)
        return "\n".join(clauses), params


def _round(value: float | None, digits: int = 6) -> float | None:
    return round(float(value), digits) if value is not None else None


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _uuid_array(ids: list[str | UUID]) -> list[UUID]:
    return [item if isinstance(item, UUID) else UUID(str(item)) for item in ids]


def _text_array(values: list[str]) -> list[str]:
    return list(values)


def _json_object(value: Any) -> dict[str, float] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _estimate_tokens(content: str) -> int:
    return max(1, len(content) // _TOKEN_COUNT)


def _term_frequencies(tsv_text: str, terms: list[str]) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for match in _TSV_ENTRY.finditer(tsv_text):
        term = match.group(1).replace("''", "'")
        positions = [item for item in match.group(2).split(",") if item]
        frequencies[term] = len(positions)
    return {term: frequencies.get(term, 0) for term in terms}


def _bm25(tf: int, doc_len: int, avgdl: float, df: int, n_docs: int) -> float:
    if tf <= 0 or doc_len <= 0 or avgdl <= 0 or df <= 0 or n_docs <= 1 or df > n_docs:
        return 0.0
    idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
    denominator = tf + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * doc_len / avgdl)
    return idf * (tf * (_BM25_K1 + 1.0)) / denominator


def _detect_language(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "en"
