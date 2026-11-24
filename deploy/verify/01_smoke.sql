-- =============================================================================
-- Phase 1 数据库冒烟测试（可重复执行，事务内 ROLLBACK，不污染数据）
--
-- 用法（仓库根目录）:
--   Get-Content deploy\verify\01_smoke.sql -Raw |
--     docker compose -f deploy/docker-compose.yml exec -T postgres `
--       psql -v ON_ERROR_STOP=1 -U workspace -d workspace
-- =============================================================================
\set ON_ERROR_STOP on

BEGIN;
SET LOCAL app.workspace_id = '0192f0c0-0001-7c2d-8e3f-0a1b2c3d4e5f';

DO $$
DECLARE
    missing_extensions text;
    table_count integer;
    policy_count integer;
BEGIN
    SELECT string_agg(expected, ',') INTO missing_extensions
    FROM (VALUES ('vector'), ('pg_trgm')) AS required(expected)
    WHERE NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = required.expected);

    IF missing_extensions IS NOT NULL THEN
        RAISE EXCEPTION '缺少扩展: %', missing_extensions;
    END IF;

    SELECT count(*) INTO table_count
    FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
    IF table_count < 18 THEN
        RAISE EXCEPTION '表数量异常: %（预期 >= 18）', table_count;
    END IF;

    IF to_regclass('public.document_chunks') IS NULL
       OR to_regclass('public.document_parent_chunks') IS NULL
       OR to_regclass('public.retrieval_traces') IS NULL
       OR to_regclass('public.request_logs') IS NULL THEN
        RAISE EXCEPTION '核心表缺失';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_chunks_embedding_hnsw') THEN
        RAISE EXCEPTION 'HNSW 向量索引缺失';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_chunks_content_fts') THEN
        RAISE EXCEPTION '全文 GIN 索引缺失';
    END IF;

    SELECT count(*) INTO policy_count FROM pg_policies WHERE schemaname = 'public';
    IF policy_count < 10 THEN
        RAISE EXCEPTION 'RLS 策略数量异常: %', policy_count;
    END IF;
END
$$;

SELECT app.fts_config() AS fts_config,
       app.bm25_score(3, 100, 200, 2, 1000) AS bm25_score;

INSERT INTO workspaces (id, slug, name)
VALUES ('0192f0c0-0001-7c2d-8e3f-0a1b2c3d4e5f', 'phase1-smoke', 'Phase 1 Smoke');

INSERT INTO knowledge_bases (id, workspace_id, name)
VALUES ('0192f0c0-0002-7c2d-8e3f-0a1b2c3d4e5f',
        '0192f0c0-0001-7c2d-8e3f-0a1b2c3d4e5f', 'Smoke KB');

INSERT INTO documents (
    id, workspace_id, knowledge_base_id, title, file_name, mime_type,
    size_bytes, checksum_sha256, status
) VALUES (
    '0192f0c0-0003-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0001-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0002-7c2d-8e3f-0a1b2c3d4e5f',
    'Phase 1 Smoke 文档', 'smoke.pdf', 'application/pdf',
    1024, repeat('b', 64), 'ready'
);

INSERT INTO document_parent_chunks (
    id, workspace_id, knowledge_base_id, document_id,
    chunk_index, content, token_count, page_from, page_to
) VALUES (
    '0192f0c0-0004-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0001-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0002-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0003-7c2d-8e3f-0a1b2c3d4e5f',
    0, '父切片：灰度回滚规范。', 12, 18, 18
);

INSERT INTO document_chunks (
    id, workspace_id, knowledge_base_id, document_id, parent_chunk_id,
    chunk_index, content, token_count, page_no, bbox, embedding
) VALUES (
    '0192f0c0-0005-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0001-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0002-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0003-7c2d-8e3f-0a1b2c3d4e5f',
    '0192f0c0-0004-7c2d-8e3f-0a1b2c3d4e5f',
    0, '灰度批次内新版本错误率连续 5 分钟超过 1% 时自动回滚。',
    20, 18, '{"x0":0.1,"y0":0.2,"x1":0.9,"y1":0.3}'::jsonb,
    array_fill(0.1::real, ARRAY[1024])::vector
);

SELECT content_tsv IS NOT NULL AS tsv_filled,
       embedding <=> array_fill(0.1::real, ARRAY[1024])::vector AS cosine_distance
FROM document_chunks
WHERE document_id = '0192f0c0-0003-7c2d-8e3f-0a1b2c3d4e5f';

SELECT 'PHASE1_DB_SMOKE_OK' AS result;
ROLLBACK;
