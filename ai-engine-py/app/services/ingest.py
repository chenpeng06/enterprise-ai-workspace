"""PDF 摄取：解析 → 父子切片 → Embedding → pgvector 写入。

只处理网关已经鉴权并保存到共享目录的 local PDF；生产 OSS/HTTP 源在 Phase 4 扩展。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.session import get_session_factory
from app.rag.embeddings import OpenAICompatibleEmbeddingClient

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


class IngestError(RuntimeError):
    pass


@dataclass
class ChildDraft:
    content: str
    page_no: int
    char_start: int
    char_end: int
    token_count: int


@dataclass
class ParentDraft:
    content: str
    page_from: int
    page_to: int
    token_count: int
    children: list[ChildDraft]


class IngestService:
    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        embedding_client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory or get_session_factory(self.settings)
        self.embedding = embedding_client or OpenAICompatibleEmbeddingClient(self.settings)

    async def create(self, payload: dict[str, Any], path: Path) -> dict[str, Any]:
        document = payload["document"]
        chunking = payload["chunking"]
        task_id = uuid4()
        document_id = UUID(str(payload["document_id"]))
        workspace_id = UUID(str(payload["workspace_id"]))
        kb_id = UUID(str(payload["knowledge_base_id"]))
        requested_by = UUID(str(payload["requested_by"]))
        now = datetime.now(UTC)

        async with self.session_factory() as session:
            await _set_workspace(session, workspace_id)
            try:
                await session.execute(
                    text(
                        """
                        INSERT INTO documents (
                            id, workspace_id, knowledge_base_id, title, file_name,
                            mime_type, size_bytes, checksum_sha256, source_type,
                            source_uri, status, page_count, created_by
                        ) VALUES (
                            :id, :ws, :kb, :title, :file_name, :mime, :size,
                            :checksum, 'upload', :uri, 'queued', 0, :requested_by
                        )
                        """
                    ),
                    {
                        "id": document_id,
                        "ws": workspace_id,
                        "kb": kb_id,
                        "title": document["title"][:300],
                        "file_name": document["file_name"][:300],
                        "mime": document["mime_type"],
                        "size": document["size_bytes"],
                        "checksum": document["sha256"],
                        "uri": str(path),
                        "requested_by": requested_by,
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO ingest_tasks (
                            id, workspace_id, knowledge_base_id, document_id,
                            status, stage, progress, idempotency_key, requested_by,
                            embedding_model, counters
                        ) VALUES (
                            :id, :ws, :kb, :document, 'queued', 'queued', 0,
                            :idempotency, :requested_by, :model,
                            CAST(:counters AS jsonb)
                        )
                        """
                    ),
                    {
                        "id": task_id,
                        "ws": workspace_id,
                        "kb": kb_id,
                        "document": document_id,
                        "idempotency": payload["idempotency_key"],
                        "requested_by": requested_by,
                        "model": payload["embedding"]["model"],
                        "counters": json.dumps(
                            {
                                "pages": 0,
                                "ocr_pages": 0,
                                "child_chunks": 0,
                                "parent_chunks": 0,
                                "embedding_tokens": 0,
                            }
                        ),
                    },
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                raise IngestError(f"创建摄取记录失败: {type(exc).__name__}") from exc

        task = asyncio.create_task(
            self._process(
                task_id=task_id,
                document_id=document_id,
                workspace_id=workspace_id,
                kb_id=kb_id,
                path=path,
                chunking=chunking,
                parse_options=payload.get("parse") or {},
                embedding_config=payload["embedding"],
            )
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

        return {
            "task_id": str(task_id),
            "document_id": str(document_id),
            "status": "queued",
            "accepted_at": now.isoformat(),
            "deduplicated": False,
            "estimated_pages": None,
        }

    async def _process(
        self,
        *,
        task_id: UUID,
        document_id: UUID,
        workspace_id: UUID,
        kb_id: UUID,
        path: Path,
        chunking: dict[str, Any],
        parse_options: dict[str, Any],
        embedding_config: dict[str, Any],
    ) -> None:
        stage = "fetching"
        try:
            async with self.session_factory() as session:
                await _set_workspace(session, workspace_id)
                await self._update_task(
                    session,
                    workspace_id,
                    task_id,
                    status="running",
                    stage="fetching",
                    progress=5,
                    started=True,
                )
                await self._update_document(session, workspace_id, document_id, "parsing")
                await session.commit()

            pages, total_pages = await asyncio.to_thread(
                _parse_pdf,
                path,
                int(parse_options.get("max_pages") or 500),
            )
            stage = "parsing"
            if not pages:
                raise IngestError("PDF 未提取到可用文字（可能是扫描件，当前未启用 OCR）")

            async with self.session_factory() as session:
                await _set_workspace(session, workspace_id)
                await self._update_task(
                    session,
                    workspace_id,
                    task_id,
                    status="running",
                    stage="parsing",
                    progress=20,
                )
                await self._update_document(session, workspace_id, document_id, "chunking")
                await session.commit()

            parents = _chunk_pages(
                pages,
                parent_size=int(chunking["parent_chunk_size"]),
                child_size=int(chunking["child_chunk_size"]),
                overlap=int(chunking.get("child_overlap", 50)),
                min_size=int(chunking.get("min_chunk_size", 60)),
            )
            stage = "chunking"
            children = [child for parent in parents for child in parent.children]
            if not children:
                raise IngestError("PDF 切片结果为空")

            async with self.session_factory() as session:
                await _set_workspace(session, workspace_id)
                await self._update_task(
                    session,
                    workspace_id,
                    task_id,
                    status="running",
                    stage="chunking",
                    progress=35,
                )
                await self._update_document(session, workspace_id, document_id, "embedding")
                await session.commit()

            stage = "embedding"
            vectors = await self.embedding.embed_texts([child.content for child in children])
            if len(vectors) != len(children):
                raise IngestError("Embedding 数量与切片数量不一致")
            async with self.session_factory() as session:
                await _set_workspace(session, workspace_id)
                await self._update_task(
                    session,
                    workspace_id,
                    task_id,
                    status="running",
                    stage="embedding",
                    progress=70,
                )
                await self._update_document(session, workspace_id, document_id, "indexing")
                await session.commit()

            async with self.session_factory() as session:
                await _set_workspace(session, workspace_id)
                parent_count, child_count = await self._insert_chunks(
                    session,
                    workspace_id=workspace_id,
                    kb_id=kb_id,
                    document_id=document_id,
                    parents=parents,
                    vectors=vectors,
                    embedding_model=str(embedding_config["model"]),
                )
                await session.execute(
                    text(
                        """
                        UPDATE documents
                        SET status = 'ready', page_count = :pages,
                            parent_chunk_count = :parents, chunk_count = :children,
                            ready_at = now(), error_code = NULL, error_message = NULL,
                            updated_at = now()
                        WHERE id = :id AND workspace_id = :ws
                        """
                    ),
                    {
                        "pages": total_pages,
                        "parents": parent_count,
                        "children": child_count,
                        "id": document_id,
                        "ws": workspace_id,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE knowledge_bases kb
                        SET chunk_count = stats.chunk_count,
                            avg_chunk_tokens = stats.avg_tokens,
                            last_ingested_at = now(),
                            updated_at = now()
                        FROM (
                            SELECT COUNT(*)::bigint AS chunk_count,
                                   COALESCE(AVG(token_count), 0)::numeric(10,2) AS avg_tokens
                            FROM document_chunks
                            WHERE workspace_id = :ws AND knowledge_base_id = :kb
                        ) stats
                        WHERE kb.id = :kb AND kb.workspace_id = :ws
                        """
                    ),
                    {"ws": workspace_id, "kb": kb_id},
                )
                await self._update_task(
                    session,
                    workspace_id,
                    task_id,
                    status="succeeded",
                    stage="completed",
                    progress=100,
                    counters={
                        "pages": total_pages,
                        "ocr_pages": 0,
                        "parent_chunks": parent_count,
                        "child_chunks": child_count,
                        "embedding_tokens": sum(len(c.content) // 4 for c in children),
                    },
                    finished=True,
                )
                await session.commit()
        except Exception as exc:
            logger.warning("PDF 摄取失败 task=%s: %s", task_id, exc)
            await self._mark_failed(
                task_id,
                document_id,
                workspace_id,
                stage,
                str(exc)[:1000],
            )

    async def _insert_chunks(
        self,
        session: AsyncSession,
        *,
        workspace_id: UUID,
        kb_id: UUID,
        document_id: UUID,
        parents: list[ParentDraft],
        vectors: list[list[float]],
        embedding_model: str,
    ) -> tuple[int, int]:
        parent_ids: list[UUID] = []
        for index, parent in enumerate(parents):
            parent_id = uuid4()
            parent_ids.append(parent_id)
            await session.execute(
                text(
                    """
                    INSERT INTO document_parent_chunks (
                        id, workspace_id, knowledge_base_id, document_id,
                        chunk_index, content, token_count, page_from, page_to
                    ) VALUES (
                        :id, :ws, :kb, :doc, :idx, :content, :tokens, :page_from, :page_to
                    )
                    """
                ),
                {
                    "id": parent_id,
                    "ws": workspace_id,
                    "kb": kb_id,
                    "doc": document_id,
                    "idx": index,
                    "content": parent.content,
                    "tokens": parent.token_count,
                    "page_from": parent.page_from,
                    "page_to": parent.page_to,
                },
            )

        child_index = 0
        vector_offset = 0
        for parent_id, parent in zip(parent_ids, parents, strict=False):
            for child in parent.children:
                vector = vectors[vector_offset]
                vector_offset += 1
                vector_literal = "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
                await session.execute(
                    text(
                        """
                        INSERT INTO document_chunks (
                            id, workspace_id, knowledge_base_id, document_id,
                            parent_chunk_id, chunk_index, chunk_type, content,
                            token_count, page_no, char_start, char_end,
                            section_path, embedding, embedding_model, embedded_at
                        ) VALUES (
                            :id, :ws, :kb, :doc, :parent, :idx, 'text', :content,
                            :tokens, :page_no, :char_start, :char_end,
                            ARRAY[]::text[], CAST(:vec AS vector), :model, now()
                        )
                        """
                    ),
                    {
                        "id": uuid4(),
                        "ws": workspace_id,
                        "kb": kb_id,
                        "doc": document_id,
                        "parent": parent_id,
                        "idx": child_index,
                        "content": child.content,
                        "tokens": child.token_count,
                        "page_no": child.page_no or None,
                        "char_start": child.char_start,
                        "char_end": child.char_end,
                        "vec": vector_literal,
                        "model": embedding_model,
                    },
                )
                child_index += 1
        return len(parents), child_index

    async def _mark_failed(
        self,
        task_id: UUID,
        document_id: UUID,
        workspace_id: UUID,
        stage: str,
        message: str,
    ) -> None:
        try:
            async with self.session_factory() as session:
                await _set_workspace(session, workspace_id)
                await session.execute(
                    text(
                        """
                        UPDATE ingest_tasks
                        SET status = 'failed', stage = 'failed', error = CAST(:error AS jsonb),
                            finished_at = now(), updated_at = now()
                        WHERE id = :id AND workspace_id = :ws
                        """
                    ),
                    {
                        "id": task_id,
                        "ws": workspace_id,
                        "error": json.dumps(
                            {
                                "code": "parse_failed"
                                if stage in {"fetching", "parsing"}
                                else "index_failed",
                                "message": message,
                                "retryable": False,
                                "stage": "ingest",
                            },
                            ensure_ascii=False,
                        ),
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE documents
                        SET status = 'failed', error_code = 'ingest_failed',
                            error_message = :message, updated_at = now()
                        WHERE id = :id AND workspace_id = :ws
                        """
                    ),
                    {"id": document_id, "ws": workspace_id, "message": message[:1000]},
                )
                await session.commit()
        except Exception:
            logger.exception("更新摄取失败状态失败 task=%s", task_id)

    async def _update_task(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        task_id: UUID,
        *,
        status: str,
        stage: str,
        progress: int,
        counters: dict[str, Any] | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE ingest_tasks SET
                    status = CAST(:status AS ingest_status),
                    stage = CAST(:stage AS ingest_stage),
                    progress = :progress,
                    counters = COALESCE(CAST(:counters AS jsonb), counters),
                    started_at = CASE
                        WHEN :started THEN COALESCE(started_at, now())
                        ELSE started_at
                    END,
                    finished_at = CASE
                        WHEN :finished THEN now()
                        ELSE finished_at
                    END,
                    updated_at = now()
                WHERE id = :id AND workspace_id = :ws
                """
            ),
            {
                "status": status,
                "stage": stage,
                "progress": progress,
                "counters": json.dumps(counters) if counters is not None else None,
                "started": started,
                "finished": finished,
                "id": task_id,
                "ws": workspace_id,
            },
        )

    async def _update_document(
        self,
        session: AsyncSession,
        workspace_id: UUID,
        document_id: UUID,
        status: str,
    ) -> None:
        await session.execute(
            text(
                """
                UPDATE documents
                SET status = CAST(:status AS document_status), updated_at = now()
                WHERE id = :id AND workspace_id = :ws
                """
            ),
            {"status": status, "id": document_id, "ws": workspace_id},
        )


async def _set_workspace(session: AsyncSession, workspace_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.workspace_id', :ws, true)"),
        {"ws": str(workspace_id)},
    )


def _parse_pdf(path: Path, max_pages: int) -> tuple[list[tuple[int, str]], int]:
    reader = PdfReader(str(path))
    total_pages = len(reader.pages)
    pages: list[tuple[int, str]] = []
    for index, page in enumerate(reader.pages):
        if index >= max_pages:
            break
        try:
            content = page.extract_text() or ""
        except Exception:
            content = ""
        if content.strip():
            pages.append((index + 1, re.sub(r"[ \t]+", " ", content).strip()))
    return pages, total_pages


def _chunk_pages(
    pages: list[tuple[int, str]],
    *,
    parent_size: int,
    child_size: int,
    overlap: int,
    min_size: int,
) -> list[ParentDraft]:
    if not pages:
        return []
    groups: list[tuple[int, int, str]] = []
    buffer: list[str] = []
    page_start = pages[0][0]
    page_end = pages[0][0]
    for page_no, content in pages:
        candidate = "\n".join([*buffer, content])
        if buffer and len(candidate) > parent_size:
            groups.append((page_start, page_end, "\n".join(buffer)))
            buffer = [content]
            page_start = page_no
            page_end = page_no
        else:
            buffer.append(content)
            page_end = page_no
    if buffer:
        groups.append((page_start, page_end, "\n".join(buffer)))

    parents: list[ParentDraft] = []
    for page_from, page_to, content in groups:
        children: list[ChildDraft] = []
        start = 0
        while start < len(content):
            end = min(len(content), start + child_size)
            if end < len(content):
                boundary = max(
                    content.rfind("。", start + min_size, end),
                    content.rfind("\n", start + min_size, end),
                    content.rfind(" ", start + min_size, end),
                )
                if boundary > start + min_size // 2:
                    end = boundary + 1
            chunk = content[start:end].strip()
            if len(chunk) >= min_size:
                children.append(
                    ChildDraft(
                        content=chunk,
                        page_no=page_from,
                        char_start=start,
                        char_end=end,
                        token_count=max(1, len(chunk) // 4),
                    )
                )
            if end >= len(content):
                break
            start = max(end - overlap, start + 1)
        if children:
            parents.append(
                ParentDraft(
                    content=content,
                    page_from=page_from,
                    page_to=page_to,
                    token_count=max(1, len(content) // 4),
                    children=children,
                )
            )
    return parents


async def get_task_status(settings: Settings, task_id: UUID) -> dict[str, Any] | None:
    factory = get_session_factory(settings)
    async with factory() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, document_id, workspace_id, knowledge_base_id,
                           status, stage, progress, attempt, counters, stage_timings,
                           error, created_at, updated_at, started_at, finished_at
                    FROM ingest_tasks WHERE id = :id
                    """
                    ),
                    {"id": task_id},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return None
    return {
        "task_id": str(row["id"]),
        "document_id": str(row["document_id"]),
        "workspace_id": str(row["workspace_id"]),
        "knowledge_base_id": str(row["knowledge_base_id"]),
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "attempt": row["attempt"],
        "counters": row["counters"] or {},
        "stage_timings": row["stage_timings"] or [],
        "error": row["error"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
    }
