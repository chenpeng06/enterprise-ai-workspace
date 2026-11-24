package store

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/enterprise-ai-workspace/gateway-go/internal/ratelimit"
)

// CitationRecord 是 message_citations 的写入模型。
type CitationRecord struct {
	Index         int
	ChunkID       string
	ParentChunkID string
	DocumentID    string
	DocumentTitle string
	PageNo        int
	BBox          json.RawMessage
	Quote         string
	RerankScore   *float64
}

// MessageUpdate 是流结束后的 assistant 消息更新。
type MessageUpdate struct {
	MessageID        string
	WorkspaceID      string
	Content          string
	Status           string
	FinishReason     string
	Model            string
	PromptTokens     int
	CompletionTokens int
	EstimatedCostCNY float64
	TTFTMS           *int
	TotalMS          *int
	RetrievalTraceID string
	ErrorCode        string
}

// RetrievalTraceRecord 是检索透视快照。
type RetrievalTraceRecord struct {
	WorkspaceID       string
	MessageID         string
	ConversationID    string
	TraceID           string
	Source            string
	QueryOriginal     string
	QueryRewritten    string
	Strategy          json.RawMessage
	Config            json.RawMessage
	Diagnostics       json.RawMessage
	VectorCandidates  int
	LexicalCandidates int
	FusedCandidates   int
	RerankCandidates  int
	SelectedCount     int
	TotalLatencyMS    int
}

// RequestLogRecord 是 request_logs 写入模型。
type RequestLogRecord struct {
	WorkspaceID      string
	UserID           string
	RequestID        string
	TraceID          string
	Route            string
	Method           string
	StatusCode       int
	LatencyMS        int
	TTFTMS           *int
	Model            string
	PromptTokens     int
	CompletionTokens int
	EstimatedCostCNY float64
	RateLimited      bool
	ClientIP         string
	UserAgent        string
	ErrorCode        string
}

// ChunkPreview 是右侧原文预览所需数据。
type ChunkPreview struct {
	ChunkID       string          `json:"chunk_id"`
	ParentChunkID string          `json:"parent_chunk_id,omitempty"`
	DocumentID    string          `json:"document_id"`
	DocumentTitle string          `json:"document_title"`
	FileName      string          `json:"file_name"`
	Content       string          `json:"content"`
	ParentContent string          `json:"parent_content,omitempty"`
	PageNo        int             `json:"page_no,omitempty"`
	BBox          json.RawMessage `json:"bbox,omitempty"`
	CharStart     int             `json:"char_start,omitempty"`
	CharEnd       int             `json:"char_end,omitempty"`
	SectionPath   []string        `json:"section_path"`
	ChunkType     string          `json:"chunk_type"`
	PageCount     int             `json:"page_count"`
	TokenCount    int             `json:"token_count"`
}

type MetricsTotals struct {
	Requests     int     `json:"requests"`
	ChatRequests int     `json:"chat_requests"`
	RateLimited  int     `json:"rate_limited"`
	AvgTTFTMS    float64 `json:"avg_ttft_ms"`
	P95TTFTMS    float64 `json:"p95_ttft_ms"`
	TotalTokens  int64   `json:"total_tokens"`
}

type TrendPoint struct {
	Bucket    time.Time `json:"bucket"`
	AvgTTFTMS float64   `json:"avg_ttft_ms,omitempty"`
	Count     int       `json:"count"`
}

type RateLimitRecord struct {
	Route        string    `json:"route"`
	Scope        string    `json:"scope"`
	LimitValue   int       `json:"limit_value"`
	Observed     int       `json:"observed"`
	RetryAfterMS int       `json:"retry_after_ms"`
	ClientIP     string    `json:"client_ip,omitempty"`
	CreatedAt    time.Time `json:"created_at"`
}

type KnowledgeBaseMetrics struct {
	Queries int     `json:"queries"`
	Hits    int     `json:"hits"`
	HitRate float64 `json:"hit_rate"`
}

type MetricsOverview struct {
	Hours            int                  `json:"hours"`
	Totals           MetricsTotals        `json:"totals"`
	TTFTTrend        []TrendPoint         `json:"ttft_trend"`
	RateLimitTrend   []TrendPoint         `json:"rate_limit_trend"`
	KnowledgeBase    KnowledgeBaseMetrics `json:"knowledge_base"`
	RecentRateLimits []RateLimitRecord    `json:"recent_rate_limits"`
}

func (p *Postgres) EnsureConversation(
	ctx context.Context,
	conversationID, workspaceID, knowledgeBaseID, title, mode string,
) error {
	if p == nil || p.Pool == nil {
		return fmt.Errorf("PostgreSQL 连接池未初始化")
	}
	_, err := p.Pool.Exec(ctx, `
		INSERT INTO conversations (id, workspace_id, knowledge_base_id, title, mode)
		VALUES ($1::uuid, $2::uuid, NULLIF($3, '')::uuid, $4, $5::chat_mode)
		ON CONFLICT (id) DO NOTHING
	`, conversationID, workspaceID, knowledgeBaseID, title, mode)
	if err != nil {
		return fmt.Errorf("创建会话失败: %w", err)
	}
	var actualWorkspace string
	if err := p.Pool.QueryRow(ctx,
		`SELECT workspace_id::text FROM conversations WHERE id = $1::uuid`,
		conversationID,
	).Scan(&actualWorkspace); err != nil {
		return fmt.Errorf("查询会话失败: %w", err)
	}
	if actualWorkspace != workspaceID {
		return fmt.Errorf("会话不属于当前 workspace")
	}
	return nil
}

func (p *Postgres) CreateMessage(
	ctx context.Context,
	messageID, workspaceID, conversationID, role, content, status string,
) error {
	_, err := p.Pool.Exec(ctx, `
		INSERT INTO messages (id, workspace_id, conversation_id, role, content, status)
		VALUES ($1::uuid, $2::uuid, $3::uuid, $4::message_role, $5, $6::message_status)
	`, messageID, workspaceID, conversationID, role, content, status)
	if err != nil {
		return fmt.Errorf("创建消息失败: %w", err)
	}
	return nil
}

func (p *Postgres) UpdateAssistantMessage(ctx context.Context, u MessageUpdate) error {
	_, err := p.Pool.Exec(ctx, `
		UPDATE messages SET
			content = $1,
			status = $2::message_status,
			finish_reason = NULLIF($3, '')::finish_reason,
			model = NULLIF($4, ''),
			prompt_tokens = $5,
			completion_tokens = $6,
			estimated_cost_cny = $7,
			ttft_ms = $8,
			total_ms = $9,
			retrieval_trace_id = NULLIF($10, '')::uuid,
			error_code = NULLIF($11, ''),
			updated_at = now()
		WHERE id = $12::uuid AND workspace_id = $13::uuid
	`, u.Content, u.Status, u.FinishReason, u.Model, u.PromptTokens,
		u.CompletionTokens, u.EstimatedCostCNY, u.TTFTMS, u.TotalMS,
		u.RetrievalTraceID, u.ErrorCode, u.MessageID, u.WorkspaceID)
	if err != nil {
		return fmt.Errorf("更新 assistant 消息失败: %w", err)
	}
	return nil
}

func (p *Postgres) InsertCitations(
	ctx context.Context,
	workspaceID, messageID string,
	citations []CitationRecord,
) error {
	if len(citations) == 0 {
		return nil
	}
	batch := &pgx.Batch{}
	for _, citation := range citations {
		batch.Queue(`
			INSERT INTO message_citations (
				workspace_id, message_id, citation_index, chunk_id, document_id,
				document_title, page_no, bbox, quote, rerank_score
			) VALUES (
				$1::uuid, $2::uuid, $3, NULLIF($4, '')::uuid, NULLIF($5, '')::uuid,
				$6, $7, NULLIF($8, '')::jsonb, $9, $10
			)
			ON CONFLICT (message_id, citation_index) DO NOTHING
		`, workspaceID, messageID, citation.Index, citation.ChunkID,
			citation.DocumentID, citation.DocumentTitle, nullableInt(citation.PageNo),
			string(citation.BBox), citation.Quote, citation.RerankScore)
	}
	results := p.Pool.SendBatch(ctx, batch)
	defer func() { _ = results.Close() }()
	for range citations {
		if _, err := results.Exec(); err != nil {
			return fmt.Errorf("写入引用失败: %w", err)
		}
	}
	return nil
}

func (p *Postgres) InsertRetrievalTrace(ctx context.Context, t RetrievalTraceRecord) error {
	_, err := p.Pool.Exec(ctx, `
		INSERT INTO retrieval_traces (
			workspace_id, message_id, conversation_id, trace_id, source,
			query_original, query_rewritten, strategy, config, diagnostics,
			vector_candidates, lexical_candidates, fused_candidates,
			rerank_candidates, selected_count, total_latency_ms
		) VALUES (
			$1::uuid, $2::uuid, $3::uuid, $4::uuid, $5,
			$6, $7, COALESCE(NULLIF($8, '')::jsonb, '{}'::jsonb),
			COALESCE(NULLIF($9, '')::jsonb, '{}'::jsonb),
			COALESCE(NULLIF($10, '')::jsonb, '{}'::jsonb),
			$11, $12, $13, $14, $15, $16
		)
		ON CONFLICT (trace_id) DO NOTHING
	`, t.WorkspaceID, t.MessageID, t.ConversationID, t.TraceID, t.Source,
		t.QueryOriginal, t.QueryRewritten, string(t.Strategy), string(t.Config),
		string(t.Diagnostics), t.VectorCandidates, t.LexicalCandidates,
		t.FusedCandidates, t.RerankCandidates, t.SelectedCount, t.TotalLatencyMS)
	if err != nil {
		return fmt.Errorf("写入检索留痕失败: %w", err)
	}
	return nil
}

func (p *Postgres) InsertRequestLog(ctx context.Context, l RequestLogRecord) error {
	_, err := p.Pool.Exec(ctx, `
		INSERT INTO request_logs (
			workspace_id, user_id, request_id, trace_id, route, method,
			status_code, latency_ms, ttft_ms, model, prompt_tokens,
			completion_tokens, estimated_cost_cny, rate_limited, client_ip,
			user_agent, error_code
		) VALUES (
			NULLIF($1, '')::uuid, NULLIF($2, '')::uuid, NULLIF($3, '')::uuid,
			NULLIF($4, '')::uuid, $5, $6, $7, $8, $9, NULLIF($10, ''),
			$11, $12, $13, $14, NULLIF($15, '')::inet, NULLIF($16, ''), NULLIF($17, '')
		)
	`, l.WorkspaceID, l.UserID, l.RequestID, l.TraceID, l.Route, l.Method,
		l.StatusCode, l.LatencyMS, l.TTFTMS, l.Model, l.PromptTokens,
		l.CompletionTokens, l.EstimatedCostCNY, l.RateLimited, l.ClientIP,
		l.UserAgent, l.ErrorCode)
	if err != nil {
		return fmt.Errorf("写入请求日志失败: %w", err)
	}
	return nil
}

func (p *Postgres) LogRateLimit(ctx context.Context, e ratelimit.AuditEvent) error {
	_, err := p.Pool.Exec(ctx, `
		INSERT INTO rate_limit_events (
			workspace_id, user_id, route, scope, limit_value, observed,
			retry_after_ms, client_ip
		) VALUES (
			NULLIF($1, '')::uuid, NULLIF($2, '')::uuid, $3, $4::rate_limit_scope,
			$5, $6, $7, NULLIF($8, '')::inet
		)
	`, e.WorkspaceID, e.UserID, e.Route, e.Scope, e.LimitValue, e.Observed,
		e.RetryAfterMS, e.ClientIP)
	if err != nil {
		return fmt.Errorf("写入限流日志失败: %w", err)
	}
	return nil
}

func (p *Postgres) GetChunkPreview(
	ctx context.Context,
	workspaceID, chunkID string,
) (*ChunkPreview, error) {
	row := p.Pool.QueryRow(ctx, `
		SELECT
			c.id::text,
			COALESCE(c.parent_chunk_id::text, ''),
			c.document_id::text,
			d.title,
			d.file_name,
			c.content,
			COALESCE(p.content, ''),
			COALESCE(c.page_no, 0),
			COALESCE(c.bbox, '{}'::jsonb),
			COALESCE(c.char_start, 0),
			COALESCE(c.char_end, 0),
			COALESCE(c.section_path, ARRAY[]::text[]),
			c.chunk_type::text,
			COALESCE(d.page_count, 0),
			COALESCE(c.token_count, 0)
		FROM document_chunks c
		JOIN documents d
		  ON d.id = c.document_id
		 AND d.workspace_id = c.workspace_id
		LEFT JOIN document_parent_chunks p ON p.id = c.parent_chunk_id
		WHERE c.id = $1::uuid
		  AND c.workspace_id = $2::uuid
		  AND d.deleted_at IS NULL
	`, chunkID, workspaceID)

	var preview ChunkPreview
	var bbox []byte
	if err := row.Scan(
		&preview.ChunkID, &preview.ParentChunkID, &preview.DocumentID,
		&preview.DocumentTitle, &preview.FileName, &preview.Content,
		&preview.ParentContent, &preview.PageNo, &bbox, &preview.CharStart,
		&preview.CharEnd, &preview.SectionPath, &preview.ChunkType,
		&preview.PageCount, &preview.TokenCount,
	); err != nil {
		if err == pgx.ErrNoRows {
			return nil, fmt.Errorf("切片不存在")
		}
		return nil, fmt.Errorf("查询切片失败: %w", err)
	}
	if len(bbox) > 0 && string(bbox) != "{}" {
		preview.BBox = json.RawMessage(bbox)
	}
	return &preview, nil
}

func (p *Postgres) MetricsOverview(
	ctx context.Context,
	workspaceID string,
	since time.Time,
	hours int,
) (*MetricsOverview, error) {
	overview := &MetricsOverview{
		Hours:            hours,
		TTFTTrend:        []TrendPoint{},
		RateLimitTrend:   []TrendPoint{},
		RecentRateLimits: []RateLimitRecord{},
	}

	if err := p.Pool.QueryRow(ctx, `
		SELECT
			COUNT(*)::int,
			COUNT(*) FILTER (WHERE route LIKE '%/chat/stream')::int,
			COALESCE(AVG(ttft_ms), 0)::float8,
			COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY ttft_ms), 0)::float8,
			COALESCE(SUM(prompt_tokens + completion_tokens), 0)::bigint
		FROM request_logs
		WHERE workspace_id = $1::uuid AND created_at >= $2
	`, workspaceID, since).Scan(
		&overview.Totals.Requests,
		&overview.Totals.ChatRequests,
		&overview.Totals.AvgTTFTMS,
		&overview.Totals.P95TTFTMS,
		&overview.Totals.TotalTokens,
	); err != nil {
		return nil, fmt.Errorf("聚合请求指标失败: %w", err)
	}

	if err := p.Pool.QueryRow(ctx, `
		SELECT COUNT(*)::int
		FROM rate_limit_events
		WHERE workspace_id = $1::uuid AND created_at >= $2
	`, workspaceID, since).Scan(&overview.Totals.RateLimited); err != nil {
		return nil, fmt.Errorf("聚合限流指标失败: %w", err)
	}

	ttftRows, err := p.Pool.Query(ctx, `
		SELECT date_trunc('hour', created_at) AS bucket,
		       AVG(ttft_ms)::float8 AS avg_ttft_ms,
		       COUNT(*)::int AS count
		FROM request_logs
		WHERE workspace_id = $1::uuid
		  AND created_at >= $2
		  AND ttft_ms IS NOT NULL
		GROUP BY 1
		ORDER BY 1
	`, workspaceID, since)
	if err != nil {
		return nil, fmt.Errorf("查询 TTFT 趋势失败: %w", err)
	}
	defer ttftRows.Close()
	for ttftRows.Next() {
		var point TrendPoint
		if err := ttftRows.Scan(&point.Bucket, &point.AvgTTFTMS, &point.Count); err != nil {
			return nil, fmt.Errorf("读取 TTFT 趋势失败: %w", err)
		}
		overview.TTFTTrend = append(overview.TTFTTrend, point)
	}
	if err := ttftRows.Err(); err != nil {
		return nil, fmt.Errorf("遍历 TTFT 趋势失败: %w", err)
	}

	rateRows, err := p.Pool.Query(ctx, `
		SELECT date_trunc('hour', created_at) AS bucket, COUNT(*)::int AS count
		FROM rate_limit_events
		WHERE workspace_id = $1::uuid AND created_at >= $2
		GROUP BY 1
		ORDER BY 1
	`, workspaceID, since)
	if err != nil {
		return nil, fmt.Errorf("查询限流趋势失败: %w", err)
	}
	defer rateRows.Close()
	for rateRows.Next() {
		var point TrendPoint
		if err := rateRows.Scan(&point.Bucket, &point.Count); err != nil {
			return nil, fmt.Errorf("读取限流趋势失败: %w", err)
		}
		overview.RateLimitTrend = append(overview.RateLimitTrend, point)
	}

	if err := p.Pool.QueryRow(ctx, `
		SELECT
			COUNT(*)::int,
			COUNT(*) FILTER (WHERE selected_count > 0)::int
		FROM retrieval_traces
		WHERE workspace_id = $1::uuid AND created_at >= $2
	`, workspaceID, since).Scan(
		&overview.KnowledgeBase.Queries,
		&overview.KnowledgeBase.Hits,
	); err != nil {
		return nil, fmt.Errorf("聚合知识库命中率失败: %w", err)
	}
	if overview.KnowledgeBase.Queries > 0 {
		overview.KnowledgeBase.HitRate = float64(overview.KnowledgeBase.Hits) / float64(overview.KnowledgeBase.Queries)
	}

	limitRows, err := p.Pool.Query(ctx, `
		SELECT route, scope::text, limit_value, observed, retry_after_ms,
		       COALESCE(client_ip::text, ''), created_at
		FROM rate_limit_events
		WHERE workspace_id = $1::uuid AND created_at >= $2
		ORDER BY created_at DESC
		LIMIT 10
	`, workspaceID, since)
	if err != nil {
		return nil, fmt.Errorf("查询最近限流记录失败: %w", err)
	}
	defer limitRows.Close()
	for limitRows.Next() {
		var record RateLimitRecord
		if err := limitRows.Scan(
			&record.Route, &record.Scope, &record.LimitValue,
			&record.Observed, &record.RetryAfterMS, &record.ClientIP,
			&record.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("读取最近限流记录失败: %w", err)
		}
		overview.RecentRateLimits = append(overview.RecentRateLimits, record)
	}
	return overview, nil
}

func nullableInt(value int) any {
	if value <= 0 {
		return nil
	}
	return value
}
