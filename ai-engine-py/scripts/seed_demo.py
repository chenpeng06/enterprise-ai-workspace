"""写入一套可演示的知识库数据（使用真实 Embedding）。

用法（在 ai-engine-py 目录）:
    .\\.venv\\Scripts\\python.exe scripts\\seed_demo.py

会重建固定 ID 的演示 workspace（仅本地开发使用）。
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.rag.embeddings import OpenAICompatibleEmbeddingClient

WORKSPACE_ID = UUID("0192f0e0-0001-7c2d-8e3f-0a1b2c3d4e5f")
KB_ID = UUID("0192f0e0-0002-7c2d-8e3f-0a1b2c3d4e5f")
DOCUMENT_ID = UUID("0192f0e0-0003-7c2d-8e3f-0a1b2c3d4e5f")
PARENT_IDS = [
    UUID("0192f0e0-0010-7c2d-8e3f-0a1b2c3d4e5f"),
    UUID("0192f0e0-0011-7c2d-8e3f-0a1b2c3d4e5f"),
    UUID("0192f0e0-0012-7c2d-8e3f-0a1b2c3d4e5f"),
]
CHUNK_IDS = [
    UUID("0192f0e0-0020-7c2d-8e3f-0a1b2c3d4e5f"),
    UUID("0192f0e0-0021-7c2d-8e3f-0a1b2c3d4e5f"),
    UUID("0192f0e0-0022-7c2d-8e3f-0a1b2c3d4e5f"),
]

CHUNKS = [
    {
        "content": (
            "灰度发布规范：当新版本错误率连续 5 分钟超过 1% 时，发布平台应自动触发回滚 "
            "rollback error rate threshold。回滚后保留现场并通知值班 SRE。"
        ),
        "section": ["3 发布管理", "3.2 灰度发布", "3.2.3 自动回滚"],
        "page": 18,
        "char_start": 320,
        "char_end": 520,
        "bbox": {"x0": 0.128, "y0": 0.412, "x1": 0.871, "y1": 0.567},
        "tokens": 68,
    },
    {
        "content": (
            "回滚处置流程：冻结灰度批次、导出发布单与指标快照，并在 15 分钟内通知 "
            "业务负责人。rollback freeze release batch retain evidence。"
        ),
        "section": ["3 发布管理", "3.2 灰度发布", "3.2.3 自动回滚"],
        "page": 19,
        "char_start": 40,
        "char_end": 230,
        "bbox": {"x0": 0.131, "y0": 0.581, "x1": 0.869, "y1": 0.704},
        "tokens": 62,
    },
    {
        "content": (
            "故障演练要求：每季度至少组织一次全链路故障演练，覆盖回滚、限流、降级与容量突增。"
            "drill rollback limit degrade capacity。"
        ),
        "section": ["7 故障演练", "7.1 演练计划"],
        "page": 52,
        "char_start": 64,
        "char_end": 210,
        "bbox": {"x0": 0.142, "y0": 0.301, "x1": 0.858, "y1": 0.402},
        "tokens": 54,
    },
]


async def main() -> None:
    embedding = OpenAICompatibleEmbeddingClient()
    vectors = await embedding.embed_texts([chunk["content"] for chunk in CHUNKS])
    if len(vectors) != len(CHUNKS):
        raise RuntimeError("Embedding 数量与切片数量不一致")

    factory = get_session_factory(get_settings())
    async with factory() as session:
        await session.execute(
            text("SELECT set_config('app.workspace_id', :ws, true)"),
            {"ws": str(WORKSPACE_ID)},
        )
        await session.execute(
            text("DELETE FROM workspaces WHERE id = :id"),
            {"id": WORKSPACE_ID},
        )
        await session.execute(
            text(
                "INSERT INTO workspaces (id, slug, name, plan) "
                "VALUES (:id, 'demo-ops', '研发运维演示空间', 'team')"
            ),
            {"id": WORKSPACE_ID},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_bases "
                "(id, workspace_id, name, description, embedding_model, "
                "chunk_count, avg_chunk_tokens, is_default) "
                "VALUES (:id, :ws, '研发运维规范库', "
                "'Phase 2 演示知识库', :model, :count, :avg, true)"
            ),
            {
                "id": KB_ID,
                "ws": WORKSPACE_ID,
                "model": get_settings().embedding_model,
                "count": len(CHUNKS),
                "avg": sum(chunk["tokens"] for chunk in CHUNKS) / len(CHUNKS),
            },
        )
        await session.execute(
            text(
                "INSERT INTO documents "
                "(id, workspace_id, knowledge_base_id, title, file_name, mime_type, "
                "size_bytes, checksum_sha256, status, page_count, chunk_count) "
                "VALUES (:id, :ws, :kb, '研发运维规范 v2.3', '研发运维规范_v2.3.pdf', "
                "'application/pdf', 8457216, :checksum, 'ready', 64, :count)"
            ),
            {
                "id": DOCUMENT_ID,
                "ws": WORKSPACE_ID,
                "kb": KB_ID,
                "checksum": "a1b2c3d4" * 8,
                "count": len(CHUNKS),
            },
        )

        for index, (parent_id, chunk_id, chunk, vector) in enumerate(
            zip(PARENT_IDS, CHUNK_IDS, CHUNKS, vectors, strict=True)
        ):
            await session.execute(
                text(
                    "INSERT INTO document_parent_chunks "
                    "(id, workspace_id, knowledge_base_id, document_id, chunk_index, "
                    "content, token_count, page_from, page_to) "
                    "VALUES (:id, :ws, :kb, :doc, :idx, :content, :tokens, :page, :page)"
                ),
                {
                    "id": parent_id,
                    "ws": WORKSPACE_ID,
                    "kb": KB_ID,
                    "doc": DOCUMENT_ID,
                    "idx": index,
                    "content": chunk["content"],
                    "tokens": chunk["tokens"],
                    "page": chunk["page"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO document_chunks "
                    "(id, workspace_id, knowledge_base_id, document_id, parent_chunk_id, "
                    "chunk_index, content, token_count, page_no, bbox, char_start, "
                    "char_end, section_path, embedding) "
                    "VALUES (:id, :ws, :kb, :doc, :parent, :idx, :content, :tokens, "
                    ":page, CAST(:bbox AS jsonb), :char_start, :char_end, "
                    "CAST(:section_path AS text[]), CAST(:vec AS vector))"
                ),
                {
                    "id": chunk_id,
                    "ws": WORKSPACE_ID,
                    "kb": KB_ID,
                    "doc": DOCUMENT_ID,
                    "parent": parent_id,
                    "idx": index,
                    "content": chunk["content"],
                    "tokens": chunk["tokens"],
                    "page": chunk["page"],
                    "bbox": json.dumps(chunk["bbox"]),
                    "char_start": chunk["char_start"],
                    "char_end": chunk["char_end"],
                    "section_path": chunk["section"],
                    "vec": "[" + ",".join(f"{value:.8f}" for value in vector) + "]",
                },
            )
        await session.commit()

    print(f"[ok] workspace_id={WORKSPACE_ID}")
    print(f"[ok] knowledge_base_id={KB_ID}")


if __name__ == "__main__":
    asyncio.run(main())
