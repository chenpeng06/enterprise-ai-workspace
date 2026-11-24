-- =============================================================================
-- Enterprise AI Workspace · PostgreSQL 16 + pgvector 完整建表脚本
-- 契约版本: 1.0.0
-- 适用范围: 本地 Docker Compose 初始化 / 阿里云 RDS PostgreSQL 15+ 首次部署
--
-- 设计要点:
--   1. 多租户：所有业务表带 workspace_id，复合索引以 workspace_id 为前导列，
--      并启用行级安全（RLS），通过 app.workspace_id 会话变量做隔离。
--   2. 父子切片：document_parent_chunks 保存喂给 LLM 的完整上下文；
--      document_chunks 保存可检索子切片、向量、全文索引与溯源坐标。
--   3. 混合检索：HNSW 向量索引（余弦）+ GIN 全文索引 + pg_trgm 模糊索引；
--      app.bm25_score() 提供标准 BM25 打分公式。
--   4. 全链路可观测：检索漏斗（retrieval_traces）、Agent 步骤（agent_run_steps）、
--      网关 TTFT/Token/限流日志（request_logs / rate_limit_events）均可回溯。
--
-- 执行身份: 数据库 owner（或具备 CREATE EXTENSION 权限的角色）。
-- 执行方式: psql -v ON_ERROR_STOP=1 -f 01_schema.sql
-- =============================================================================

BEGIN;

SET client_min_messages = warning;

CREATE SCHEMA IF NOT EXISTS app;
COMMENT ON SCHEMA app IS '跨服务共享的辅助函数、视图与 BM25 打分函数；业务表位于 public。';

-- -----------------------------------------------------------------------------
-- 0. 扩展与全文检索配置
-- -----------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS zhparser;
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'zh') THEN
        CREATE TEXT SEARCH CONFIGURATION zh (PARSER = zhparser);
        ALTER TEXT SEARCH CONFIGURATION zh ADD MAPPING FOR n, v, a, i, e, l WITH simple;
    END IF;
    RAISE NOTICE 'zhparser 已启用：全文检索使用 zh 配置。';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'zhparser 不可用，回退到 simple 配置（中文建议在生产环境启用 zhparser）：%', SQLERRM;
END
$$;

CREATE OR REPLACE FUNCTION app.fts_config()
RETURNS regconfig
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    SELECT COALESCE(
        (SELECT oid::regconfig FROM pg_ts_config WHERE cfgname = 'zh' LIMIT 1),
        'simple'::regconfig
    );
$$;
COMMENT ON FUNCTION app.fts_config() IS
    '返回当前可用的全文检索配置：存在 zhparser 的 zh 配置时用 zh，否则回退 simple。';

CREATE OR REPLACE FUNCTION app.current_workspace_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.workspace_id', true), '')::uuid;
$$;
COMMENT ON FUNCTION app.current_workspace_id() IS
    '读取事务级租户上下文：应用连接后执行 SET LOCAL app.workspace_id = ''<uuid>''；未设置时返回 NULL，RLS 拒绝访问。';

CREATE OR REPLACE FUNCTION app.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
COMMENT ON FUNCTION app.touch_updated_at() IS '通用 updated_at 自动维护触发器。';

CREATE OR REPLACE FUNCTION app.set_content_tsv()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.content_tsv := to_tsvector(app.fts_config(), COALESCE(NEW.content, ''));
    RETURN NEW;
END;
$$;
COMMENT ON FUNCTION app.set_content_tsv() IS
    '写入/更新切片正文时维护全文向量；使用 app.fts_config()，避免生成列无法感知 zhparser 是否安装的问题。';

-- 标准 BM25（k1=1.2, b=0.75）。Phase 2 检索器用 GIN 索引计算 df、用 knowledge_bases 统计量计算 N 与 avgdl。
CREATE OR REPLACE FUNCTION app.bm25_score(
    tf integer,
    doc_len integer,
    avgdl numeric,
    df bigint,
    n_docs bigint,
    k1 numeric DEFAULT 1.2,
    b numeric DEFAULT 0.75
)
RETURNS double precision
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT CASE
        WHEN tf IS NULL OR tf <= 0
          OR doc_len IS NULL OR doc_len <= 0
          OR avgdl IS NULL OR avgdl <= 0
          OR df IS NULL OR df <= 0
          OR df > n_docs
          OR n_docs IS NULL OR n_docs <= 1
        THEN 0::double precision
        ELSE (
            (tf::double precision * (k1::double precision + 1.0))
            / (
                tf::double precision
                + k1::double precision * (
                    1.0 - b::double precision
                    + b::double precision * doc_len::double precision / avgdl::double precision
                )
            )
            * ln(
                (
                    (n_docs::double precision - df::double precision + 0.5)
                    / (df::double precision + 0.5)
                ) + 1.0
            )
        )
    END;
$$;
COMMENT ON FUNCTION app.bm25_score(integer, integer, numeric, bigint, bigint, numeric, numeric) IS
    'BM25 打分：tf=词频，doc_len/avgdl=切片长度与平均长度，df=包含该词的切片数，n_docs=知识库切片总数。';

-- -----------------------------------------------------------------------------
-- 1. 枚举类型（幂等创建）
-- -----------------------------------------------------------------------------

DO $$ BEGIN CREATE TYPE workspace_role AS ENUM ('owner', 'admin', 'editor', 'viewer');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE document_source AS ENUM ('upload', 'oss', 'url', 'api');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE document_status AS ENUM ('pending', 'queued', 'parsing', 'chunking', 'embedding', 'indexing', 'ready', 'failed', 'archived');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE ingest_status AS ENUM ('queued', 'running', 'succeeded', 'failed', 'canceled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE ingest_stage AS ENUM ('queued', 'fetching', 'parsing', 'chunking', 'embedding', 'indexing', 'completed', 'failed', 'canceled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE chunk_type AS ENUM ('text', 'table', 'image_caption', 'code', 'heading');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE chat_mode AS ENUM ('rag', 'agent');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE message_role AS ENUM ('system', 'user', 'assistant', 'tool');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE message_status AS ENUM ('pending', 'streaming', 'completed', 'failed', 'canceled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE finish_reason AS ENUM ('stop', 'length', 'refused', 'error', 'canceled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE agent_run_status AS ENUM ('running', 'succeeded', 'refused', 'failed', 'canceled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE agent_event_type AS ENUM ('thinking', 'tool_calling', 'reranking', 'retrieval', 'generating', 'citation', 'usage', 'error');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE rate_limit_scope AS ENUM ('ip', 'user', 'workspace', 'api_key', 'route', 'global');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE bad_case_category AS ENUM ('retrieval_miss', 'wrong_citation', 'hallucination', 'irrelevant_answer', 'format_error', 'other');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN CREATE TYPE bad_case_status AS ENUM ('open', 'triaged', 'resolved');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- -----------------------------------------------------------------------------
-- 2. 租户与身份
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS workspaces (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL,
    name        text NOT NULL,
    plan        text NOT NULL DEFAULT 'team' CHECK (plan IN ('free', 'team', 'enterprise')),
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
    settings    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_slug
    ON workspaces (lower(slug)) WHERE deleted_at IS NULL;

COMMENT ON TABLE workspaces IS '租户根实体；workspace_id 是多租户隔离的唯一依据。';

CREATE TABLE IF NOT EXISTS users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email          text NOT NULL,
    display_name   text NOT NULL,
    password_hash  text,
    avatar_url     text,
    locale         text NOT NULL DEFAULT 'zh-CN',
    is_active      boolean NOT NULL DEFAULT true,
    last_login_at  timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (lower(email));
COMMENT ON TABLE users IS '全局用户表（身份数据，不作租户隔离；跨租户查询仅允许网关鉴权服务执行）。';

CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role         workspace_role NOT NULL DEFAULT 'viewer',
    invited_by   uuid REFERENCES users (id) ON DELETE SET NULL,
    joined_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_members_user ON workspace_members (user_id, workspace_id);
COMMENT ON TABLE workspace_members IS '用户-租户成员关系与 RBAC 角色。';

CREATE TABLE IF NOT EXISTS api_keys (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    name         text NOT NULL,
    key_prefix   text NOT NULL,
    key_hash     text NOT NULL,
    scopes       text[] NOT NULL DEFAULT ARRAY['chat:write', 'kb:read']::text[],
    last_used_at timestamptz,
    expires_at   timestamptz,
    revoked_at   timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_hash ON api_keys (key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_workspace ON api_keys (workspace_id, created_at DESC) WHERE revoked_at IS NULL;
COMMENT ON TABLE api_keys IS '网关鉴权用 API Key；只存哈希，key_prefix 仅供界面展示。';

-- -----------------------------------------------------------------------------
-- 3. 知识库、文档与异步摄取任务
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    name                 text NOT NULL,
    description          text NOT NULL DEFAULT '',
    embedding_model      text NOT NULL DEFAULT 'text-embedding-v3',
    embedding_dimensions smallint NOT NULL DEFAULT 1024 CHECK (embedding_dimensions = 1024),
    rerank_model         text NOT NULL DEFAULT 'bge-reranker-v2-m3',
    retrieval_config     jsonb NOT NULL DEFAULT '{}'::jsonb,
    chunk_config         jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_default           boolean NOT NULL DEFAULT false,
    chunk_count          bigint NOT NULL DEFAULT 0,
    avg_chunk_tokens     numeric(10, 2) NOT NULL DEFAULT 0,
    last_ingested_at     timestamptz,
    created_by           uuid REFERENCES users (id) ON DELETE SET NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    deleted_at           timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_workspace_name
    ON knowledge_bases (workspace_id, lower(name)) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_kb_workspace ON knowledge_bases (workspace_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_default_per_workspace
    ON knowledge_bases (workspace_id) WHERE is_default AND deleted_at IS NULL;

COMMENT ON TABLE knowledge_bases IS '知识库配置与统计；chunk_count / avg_chunk_tokens 是 BM25 的 N 与 avgdl 数据源，由摄取任务原子更新。';

CREATE TABLE IF NOT EXISTS documents (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id      uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    knowledge_base_id uuid NOT NULL REFERENCES knowledge_bases (id) ON DELETE CASCADE,
    title             text NOT NULL,
    file_name         text NOT NULL,
    mime_type         text NOT NULL,
    size_bytes        bigint NOT NULL CHECK (size_bytes > 0),
    checksum_sha256   char(64) NOT NULL,
    source_type       document_source NOT NULL DEFAULT 'upload',
    source_uri        text,
    status            document_status NOT NULL DEFAULT 'pending',
    version           integer NOT NULL DEFAULT 1 CHECK (version > 0),
    page_count        integer NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    parent_chunk_count integer NOT NULL DEFAULT 0 CHECK (parent_chunk_count >= 0),
    chunk_count       integer NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
    extracted_text_uri text,
    metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code        text,
    error_message     text,
    created_by        uuid REFERENCES users (id) ON DELETE SET NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    ready_at          timestamptz,
    deleted_at        timestamptz,
    CONSTRAINT chk_documents_checksum CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_checksum
    ON documents (workspace_id, knowledge_base_id, checksum_sha256)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_documents_kb
    ON documents (workspace_id, knowledge_base_id, status, created_at DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (workspace_id, status, updated_at DESC)
    WHERE deleted_at IS NULL;

COMMENT ON TABLE documents IS '文档主表；同一知识库内 checksum 唯一，重复上传直接复用已有文档（幂等）。';
COMMENT ON COLUMN documents.checksum_sha256 IS '文件内容的 SHA-256 小写十六进制，用于秒传与幂等去重。';

CREATE TABLE IF NOT EXISTS ingest_tasks (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id         uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    knowledge_base_id    uuid NOT NULL REFERENCES knowledge_bases (id) ON DELETE CASCADE,
    document_id          uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    status               ingest_status NOT NULL DEFAULT 'queued',
    stage                ingest_stage NOT NULL DEFAULT 'queued',
    progress             smallint NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    attempt              smallint NOT NULL DEFAULT 1 CHECK (attempt BETWEEN 1 AND 10),
    max_attempts         smallint NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    idempotency_key      text NOT NULL,
    requested_by         uuid REFERENCES users (id) ON DELETE SET NULL,
    counters             jsonb NOT NULL DEFAULT '{"pages":0,"parent_chunks":0,"child_chunks":0,"embedding_tokens":0,"ocr_pages":0}'::jsonb,
    stage_timings        jsonb NOT NULL DEFAULT '[]'::jsonb,
    embedding_model      text NOT NULL DEFAULT 'text-embedding-v3',
    error                jsonb,
    locked_by            text,
    heartbeat_at         timestamptz,
    lease_expires_at     timestamptz,
    callback_url         text,
    callback_delivered_at timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    started_at           timestamptz,
    finished_at          timestamptz,
    CONSTRAINT chk_ingest_error CHECK (error IS NULL OR jsonb_typeof(error) = 'object'),
    CONSTRAINT chk_ingest_stage_timings CHECK (jsonb_typeof(stage_timings) = 'array')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ingest_tasks_idempotency
    ON ingest_tasks (workspace_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_ingest_tasks_poll
    ON ingest_tasks (workspace_id, document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_tasks_queue
    ON ingest_tasks (status, created_at)
    WHERE status IN ('queued', 'running');

COMMENT ON TABLE ingest_tasks IS '异步解析/切片/向量化任务；锁租约字段支持多副本 worker 抢占与心跳续约。';
COMMENT ON COLUMN ingest_tasks.idempotency_key IS '网关生成的幂等键，重复触发返回原任务。';

-- -----------------------------------------------------------------------------
-- 4. 父子切片与检索数据
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS document_parent_chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    knowledge_base_id uuid NOT NULL REFERENCES knowledge_bases (id) ON DELETE CASCADE,
    document_id  uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index  integer NOT NULL CHECK (chunk_index >= 0),
    content      text NOT NULL,
    token_count  integer NOT NULL DEFAULT 0 CHECK (token_count >= 0),
    page_from    integer CHECK (page_from IS NULL OR page_from >= 1),
    page_to      integer CHECK (page_to IS NULL OR page_to >= 1),
    metadata     jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_parent_page_span CHECK (
        page_from IS NULL OR page_to IS NULL OR page_to >= page_from
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_parent_chunks_index
    ON document_parent_chunks (document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_parent_chunks_doc
    ON document_parent_chunks (workspace_id, knowledge_base_id, document_id);

COMMENT ON TABLE document_parent_chunks IS '父切片：完整段落/小节，作为 LLM 上下文；不参与向量检索。';

CREATE TABLE IF NOT EXISTS document_chunks (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id      uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    knowledge_base_id uuid NOT NULL REFERENCES knowledge_bases (id) ON DELETE CASCADE,
    document_id       uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    parent_chunk_id   uuid REFERENCES document_parent_chunks (id) ON DELETE CASCADE,
    chunk_index       integer NOT NULL CHECK (chunk_index >= 0),
    chunk_type        chunk_type NOT NULL DEFAULT 'text',
    content           text NOT NULL,
    content_tsv       tsvector,
    token_count       integer NOT NULL DEFAULT 0 CHECK (token_count >= 0),
    page_no           integer CHECK (page_no IS NULL OR page_no >= 1),
    bbox              jsonb,
    char_start        integer CHECK (char_start IS NULL OR char_start >= 0),
    char_end          integer CHECK (char_end IS NULL OR char_end >= 0),
    section_path      text[] NOT NULL DEFAULT ARRAY[]::text[],
    embedding         vector(1024),
    embedding_model   text,
    embedded_at       timestamptz,
    metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_chunk_bbox CHECK (
        bbox IS NULL OR (
            jsonb_typeof(bbox) = 'object'
            AND bbox ? 'x0' AND bbox ? 'y0' AND bbox ? 'x1' AND bbox ? 'y1'
            AND jsonb_typeof(bbox->'x0') = 'number'
            AND jsonb_typeof(bbox->'y0') = 'number'
            AND jsonb_typeof(bbox->'x1') = 'number'
            AND jsonb_typeof(bbox->'y1') = 'number'
            AND (bbox->>'x0')::numeric BETWEEN 0 AND 1
            AND (bbox->>'y0')::numeric BETWEEN 0 AND 1
            AND (bbox->>'x1')::numeric BETWEEN 0 AND 1
            AND (bbox->>'y1')::numeric BETWEEN 0 AND 1
            AND (bbox->>'x1')::numeric >= (bbox->>'x0')::numeric
            AND (bbox->>'y1')::numeric >= (bbox->>'y0')::numeric
        )
    ),
    CONSTRAINT chk_chunk_char_span CHECK (
        char_start IS NULL OR char_end IS NULL OR char_end >= char_start
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chunks_document_index
    ON document_chunks (document_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_chunks_scope
    ON document_chunks (workspace_id, knowledge_base_id, document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_parent
    ON document_chunks (parent_chunk_id) WHERE parent_chunk_id IS NOT NULL;

-- 向量索引：HNSW + 余弦距离；写入端已做 L2 归一化，余弦等价于内积。
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 全文索引：GIN(tsvector)；中文生产环境由 zhparser 的 zh 配置切词。
CREATE INDEX IF NOT EXISTS idx_chunks_content_fts
    ON document_chunks USING gin (content_tsv);

-- 模糊/子串兜底索引：处理未登录词、专有名词与中文短查询。
CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm
    ON document_chunks USING gin (content gin_trgm_ops);

COMMENT ON TABLE document_chunks IS '子切片：检索、Rerank、角标溯源的最小单元；embedding 固定 1024 维。';
COMMENT ON COLUMN document_chunks.content_tsv IS '触发器维护的全文向量，索引 idx_chunks_content_fts。';
COMMENT ON COLUMN document_chunks.char_start IS '在所属页解析文本中的字符偏移，用于在预览区精确高亮。';
COMMENT ON COLUMN document_chunks.page_no IS 'PDF/Office 页码，从 1 开始；与 bbox 组成原文定位坐标。';

DROP TRIGGER IF EXISTS trg_chunks_content_tsv ON document_chunks;
CREATE TRIGGER trg_chunks_content_tsv
    BEFORE INSERT OR UPDATE OF content ON document_chunks
    FOR EACH ROW EXECUTE FUNCTION app.set_content_tsv();

-- -----------------------------------------------------------------------------
-- 5. 对话、消息与检索溯源
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS conversations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    knowledge_base_id uuid REFERENCES knowledge_bases (id) ON DELETE SET NULL,
    user_id         uuid REFERENCES users (id) ON DELETE SET NULL,
    title           text NOT NULL DEFAULT '新对话',
    mode            chat_mode NOT NULL DEFAULT 'rag',
    message_count   integer NOT NULL DEFAULT 0 CHECK (message_count >= 0),
    last_message_at timestamptz,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    deleted_at      timestamptz
);

CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations (workspace_id, user_id, updated_at DESC)
    WHERE deleted_at IS NULL;

COMMENT ON TABLE conversations IS '会话；knowledge_base_id 为空表示多知识库联合问答。';

CREATE TABLE IF NOT EXISTS messages (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    conversation_id     uuid NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    role                message_role NOT NULL,
    content             text NOT NULL DEFAULT '',
    reasoning_content   text,
    status              message_status NOT NULL DEFAULT 'completed',
    model               text,
    prompt_tokens       integer NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
    completion_tokens   integer NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
    estimated_cost_cny  numeric(12, 6) NOT NULL DEFAULT 0,
    ttft_ms             integer CHECK (ttft_ms IS NULL OR ttft_ms >= 0),
    total_ms            integer CHECK (total_ms IS NULL OR total_ms >= 0),
    finish_reason       finish_reason,
    retrieval_trace_id  uuid,
    error_code          text,
    metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_workspace
    ON messages (workspace_id, created_at DESC);

COMMENT ON TABLE messages IS '消息；assistant 消息在流式开始前即落库（status=streaming），网关据此计算幂等与 TTFT。';

CREATE TABLE IF NOT EXISTS message_citations (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id   uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    message_id     uuid NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    citation_index integer NOT NULL CHECK (citation_index BETWEEN 1 AND 99),
    chunk_id       uuid REFERENCES document_chunks (id) ON DELETE SET NULL,
    document_id    uuid REFERENCES documents (id) ON DELETE SET NULL,
    document_title text NOT NULL,
    page_no        integer CHECK (page_no IS NULL OR page_no >= 1),
    bbox           jsonb,
    quote          text NOT NULL,
    rerank_score   double precision,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_citation_bbox CHECK (
        bbox IS NULL OR (
            jsonb_typeof(bbox) = 'object'
            AND bbox ? 'x0' AND bbox ? 'y0' AND bbox ? 'x1' AND bbox ? 'y1'
            AND jsonb_typeof(bbox->'x0') = 'number'
            AND jsonb_typeof(bbox->'y0') = 'number'
            AND jsonb_typeof(bbox->'x1') = 'number'
            AND jsonb_typeof(bbox->'y1') = 'number'
            AND (bbox->>'x0')::numeric BETWEEN 0 AND 1
            AND (bbox->>'y0')::numeric BETWEEN 0 AND 1
            AND (bbox->>'x1')::numeric BETWEEN 0 AND 1
            AND (bbox->>'y1')::numeric BETWEEN 0 AND 1
            AND (bbox->>'x1')::numeric >= (bbox->>'x0')::numeric
            AND (bbox->>'y1')::numeric >= (bbox->>'y0')::numeric
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_citations_message_index
    ON message_citations (message_id, citation_index);

COMMENT ON TABLE message_citations IS '角标 [n] 溯源快照；即使切片后续被删除，标题/原文/坐标仍可用于历史消息展示。';

CREATE TABLE IF NOT EXISTS retrieval_traces (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id      uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    -- 非流式检索调试没有消息上下文，因此 message_id / conversation_id 可空。
    message_id        uuid REFERENCES messages (id) ON DELETE SET NULL,
    conversation_id   uuid REFERENCES conversations (id) ON DELETE SET NULL,
    trace_id          uuid NOT NULL,
    source            text NOT NULL DEFAULT 'chat' CHECK (source IN ('chat', 'search', 'agent')),
    query_original    text NOT NULL,
    query_rewritten   text,
    strategy          jsonb NOT NULL DEFAULT '{}'::jsonb,
    config            jsonb NOT NULL DEFAULT '{}'::jsonb,
    diagnostics       jsonb NOT NULL,
    vector_candidates integer NOT NULL DEFAULT 0,
    lexical_candidates integer NOT NULL DEFAULT 0,
    fused_candidates  integer NOT NULL DEFAULT 0,
    rerank_candidates integer NOT NULL DEFAULT 0,
    selected_count    integer NOT NULL DEFAULT 0,
    total_latency_ms  integer CHECK (total_latency_ms IS NULL OR total_latency_ms >= 0),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_trace_diagnostics CHECK (jsonb_typeof(diagnostics) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_traces_trace_id ON retrieval_traces (trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_message
    ON retrieval_traces (message_id, created_at DESC) WHERE message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_traces_workspace_time ON retrieval_traces (workspace_id, created_at DESC);

COMMENT ON TABLE retrieval_traces IS
    '检索透视快照（完整 JSON），支持演示与 Bad Case 复盘；一条消息可有多轮检索，trace_id 唯一。';

CREATE TABLE IF NOT EXISTS agent_runs (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    message_id   uuid NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    agent_name   text NOT NULL,
    status       agent_run_status NOT NULL DEFAULT 'running',
    plan         jsonb NOT NULL DEFAULT '[]'::jsonb,
    step_count   smallint NOT NULL DEFAULT 0 CHECK (step_count >= 0),
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    latency_ms   integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
    error        jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_runs_message ON agent_runs (message_id);
CREATE INDEX IF NOT EXISTS idx_agent_runs_workspace ON agent_runs (workspace_id, started_at DESC);

COMMENT ON TABLE agent_runs IS '数字员工单次运行（LangGraph 状态机实例）。';

CREATE TABLE IF NOT EXISTS agent_run_steps (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    run_id       uuid NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    step_index   integer NOT NULL CHECK (step_index >= 0),
    node         text NOT NULL,
    event_type   agent_event_type NOT NULL,
    status       text NOT NULL CHECK (status IN ('started', 'succeeded', 'failed', 'skipped')),
    title        text,
    tool_name    text,
    payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
    latency_ms   integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run ON agent_run_steps (run_id, step_index);

COMMENT ON TABLE agent_run_steps IS 'SSE 步骤事件落库（thinking/tool_calling/reranking/generating 等），供回放与管理后台审计。';

-- -----------------------------------------------------------------------------
-- 6. 网关可观测性与运营
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS request_logs (
    id                bigserial,
    workspace_id      uuid,
    user_id           uuid,
    request_id        uuid,
    trace_id          uuid,
    route             text NOT NULL,
    method            text NOT NULL,
    status_code       smallint NOT NULL,
    latency_ms        integer NOT NULL CHECK (latency_ms >= 0),
    ttft_ms           integer CHECK (ttft_ms IS NULL OR ttft_ms >= 0),
    model             text,
    prompt_tokens     integer NOT NULL DEFAULT 0,
    completion_tokens integer NOT NULL DEFAULT 0,
    estimated_cost_cny numeric(12, 6) NOT NULL DEFAULT 0,
    rate_limited      boolean NOT NULL DEFAULT false,
    client_ip         inet,
    user_agent        text,
    error_code        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE IF NOT EXISTS request_logs_default PARTITION OF request_logs DEFAULT;

CREATE INDEX IF NOT EXISTS idx_request_logs_workspace_time
    ON request_logs (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_logs_time
    ON request_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_logs_rate_limited
    ON request_logs (rate_limited, created_at DESC) WHERE rate_limited;

COMMENT ON TABLE request_logs IS
    '网关请求日志（按月范围分区，默认分区兜底）。生产环境每月预建分区，例如：
     CREATE TABLE request_logs_2026_12 PARTITION OF request_logs
       FOR VALUES FROM (''2026-12-01'') TO (''2027-01-01'');';

CREATE TABLE IF NOT EXISTS rate_limit_events (
    id            bigserial PRIMARY KEY,
    workspace_id  uuid,
    user_id       uuid,
    route         text NOT NULL,
    scope         rate_limit_scope NOT NULL,
    limit_value   integer NOT NULL CHECK (limit_value >= 0),
    observed      integer NOT NULL CHECK (observed >= 0),
    retry_after_ms integer NOT NULL DEFAULT 0 CHECK (retry_after_ms >= 0),
    client_ip     inet,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_workspace_time
    ON rate_limit_events (workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rate_limit_time
    ON rate_limit_events (created_at DESC);

COMMENT ON TABLE rate_limit_events IS 'Redis 令牌桶拦截明细，管理后台限流看板数据源。';

CREATE TABLE IF NOT EXISTS bad_cases (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    uuid NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES conversations (id) ON DELETE SET NULL,
    message_id      uuid REFERENCES messages (id) ON DELETE SET NULL,
    category        bad_case_category NOT NULL DEFAULT 'other',
    status          bad_case_status NOT NULL DEFAULT 'open',
    note            text NOT NULL DEFAULT '',
    created_by      uuid REFERENCES users (id) ON DELETE SET NULL,
    resolved_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bad_cases_workspace
    ON bad_cases (workspace_id, status, created_at DESC);

COMMENT ON TABLE bad_cases IS 'Bad Case 收集与闭环状态。';

-- -----------------------------------------------------------------------------
-- 7. updated_at 触发器
-- -----------------------------------------------------------------------------

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'workspaces', 'users', 'knowledge_bases', 'documents', 'ingest_tasks',
        'conversations', 'messages', 'bad_cases'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%1$s_updated_at ON %1$I', t);
        EXECUTE format(
            'CREATE TRIGGER trg_%1$s_updated_at BEFORE UPDATE ON %1$I
             FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at()',
            t
        );
    END LOOP;
END
$$;

-- -----------------------------------------------------------------------------
-- 8. 行级安全（RLS）与多租户隔离
-- -----------------------------------------------------------------------------

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'knowledge_bases', 'documents', 'ingest_tasks',
        'document_parent_chunks', 'document_chunks',
        'conversations', 'messages', 'message_citations', 'retrieval_traces',
        'agent_runs', 'agent_run_steps', 'bad_cases',
        'request_logs', 'rate_limit_events'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);

        IF EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public' AND tablename = t AND policyname = 'tenant_isolation'
        ) THEN
            EXECUTE format('DROP POLICY tenant_isolation ON %I', t);
        END IF;

        IF t = 'request_logs' OR t = 'rate_limit_events' THEN
            -- 观测表允许 null workspace_id（网关内部/健康检查请求），但非空时必须匹配租户。
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I
                 USING (workspace_id IS NULL OR workspace_id = app.current_workspace_id())
                 WITH CHECK (workspace_id IS NULL OR workspace_id = app.current_workspace_id())',
                t
            );
        ELSE
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON %I
                 USING (workspace_id = app.current_workspace_id())
                 WITH CHECK (workspace_id = app.current_workspace_id())',
                t
            );
        END IF;
    END LOOP;
END
$$;

COMMENT ON POLICY tenant_isolation ON knowledge_bases IS
    '租户隔离：应用每个事务执行 SET LOCAL app.workspace_id = ''<uuid>''；未设置则拒绝访问。';

-- -----------------------------------------------------------------------------
-- 9. 检索视图与查询辅助
-- -----------------------------------------------------------------------------

CREATE OR REPLACE VIEW app.v_retrievable_chunks
WITH (security_invoker = true)
AS
SELECT
    c.id                AS chunk_id,
    c.workspace_id,
    c.knowledge_base_id,
    c.document_id,
    d.title             AS document_title,
    d.file_name,
    c.parent_chunk_id,
    p.content           AS parent_content,
    c.chunk_index,
    c.chunk_type,
    c.content,
    c.token_count,
    c.page_no,
    c.bbox,
    c.char_start,
    c.char_end,
    c.section_path,
    c.embedding,
    c.content_tsv,
    c.embedding_model,
    c.metadata
FROM document_chunks c
JOIN documents d
  ON d.id = c.document_id
 AND d.workspace_id = c.workspace_id
LEFT JOIN document_parent_chunks p ON p.id = c.parent_chunk_id
WHERE d.status = 'ready'
  AND d.deleted_at IS NULL;

COMMENT ON VIEW app.v_retrievable_chunks IS
    '检索基础视图：仅暴露已就绪且未删除文档的子切片，携带父切片正文与定位元数据。';

-- -----------------------------------------------------------------------------
-- 10. 生产加固建议（默认不执行，按环境启用）
-- -----------------------------------------------------------------------------
-- 1) 使用非 owner 角色连接应用，并强制 RLS：
--      CREATE ROLE app_rw LOGIN PASSWORD '...';
--      GRANT USAGE ON SCHEMA public, app TO app_rw;
--      GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
--      GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw;
--      ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;  -- 及所有业务表
-- 2) HNSW 索引构建/大批量摄取前：SET maintenance_work_mem = '512MB';
--    查询期按召回要求设置：SET hnsw.ef_search = 100;（默认 40）
-- 3) 生产启用 zhparser 中文分词；否则中文全文检索会退化为 trigram 兜底。
-- 4) request_logs 每月预建分区并保留 90 天；rate_limit_events 保留 30 天。
-- 5) 备份策略：RDS 自动备份 + 每日逻辑备份（pg_dump），向量表可重建但不应视为可丢弃。
-- =============================================================================

COMMIT;
