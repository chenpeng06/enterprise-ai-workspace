// Package chatproxy 实现网关的公共对话入口与 SSE 透传/指标采集。
package chatproxy

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"

	"github.com/enterprise-ai-workspace/gateway-go/internal/client/aiengine"
	"github.com/enterprise-ai-workspace/gateway-go/internal/config"
	"github.com/enterprise-ai-workspace/gateway-go/internal/store"
)

const maxUpstreamErrorBytes = 1 << 20

type Handler struct {
	cfg    *config.Config
	logger *slog.Logger
	store  *store.Postgres
	engine *aiengine.Client
}

func New(
	cfg *config.Config,
	logger *slog.Logger,
	store *store.Postgres,
	engine *aiengine.Client,
) *Handler {
	return &Handler{cfg: cfg, logger: logger, store: store, engine: engine}
}

type publicChatRequest struct {
	ConversationID string          `json:"conversation_id"`
	Query          string          `json:"query"`
	KBIDs          []string        `json:"kb_ids"`
	Mode           string          `json:"mode"`
	Agent          json.RawMessage `json:"agent"`
	Retrieval      json.RawMessage `json:"retrieval"`
	Generation     json.RawMessage `json:"generation"`
	History        json.RawMessage `json:"history"`
}

type streamRecord struct {
	workspaceID    string
	userID         string
	conversationID string
	messageID      string
	requestID      string
	traceID        string
	route          string
	query          string
	model          string
	clientIP       string
	userAgent      string
	answer         strings.Builder
	citations      []store.CitationRecord
	citationSeen   map[int]struct{}
	diagnostics    json.RawMessage
	traceRecord    *retrievalCounts
	usage          usagePayload
	finishReason   string
	errorCode      string
	clientGone     bool
	firstTokenAt   time.Time
	startedAt      time.Time
}

type retrievalCounts struct {
	traceID        string
	queryOriginal  string
	queryRewritten string
	config         json.RawMessage
	vector         int
	lexical        int
	fused          int
	rerank         int
	selected       int
	totalLatencyMS int
}

type usagePayload struct {
	PromptTokens     int     `json:"prompt_tokens"`
	CompletionTokens int     `json:"completion_tokens"`
	TotalTokens      int     `json:"total_tokens"`
	Model            string  `json:"model"`
	EstimatedCostCNY float64 `json:"estimated_cost_cny"`
}

type citationPayload struct {
	Index         int             `json:"index"`
	ChunkID       string          `json:"chunk_id"`
	ParentChunkID *string         `json:"parent_chunk_id"`
	DocumentID    string          `json:"document_id"`
	DocumentTitle string          `json:"document_title"`
	PageNo        *int            `json:"page_no"`
	BBox          json.RawMessage `json:"bbox"`
	CharStart     *int            `json:"char_start"`
	CharEnd       *int            `json:"char_end"`
	Quote         string          `json:"quote"`
	RerankScore   *float64        `json:"rerank_score"`
}

type eventData struct {
	MessageID    string            `json:"message_id"`
	Model        string            `json:"model"`
	Delta        string            `json:"delta"`
	Usage        *usagePayload     `json:"usage"`
	Citation     *citationPayload  `json:"citation"`
	Citations    []citationPayload `json:"citations"`
	Diagnostics  json.RawMessage   `json:"diagnostics"`
	FinishReason string            `json:"finish_reason"`
	Error        *eventError       `json:"error"`
}

type eventError struct {
	Code      string `json:"code"`
	Message   string `json:"message"`
	Retryable bool   `json:"retryable"`
}

func (h *Handler) Bootstrap(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"workspace_id": h.cfg.DevWorkspaceID,
		"kb_id":        h.cfg.DevKBID,
		"suggestions": []string{
			"灰度发布错误率超过阈值时应该怎么处理？",
			"自动回滚的判定条件是什么？",
			"分析 order-api 最近的错误日志并给出处置建议",
		},
	})
}

func (h *Handler) Chunk(c *gin.Context) {
	workspaceID, ok := h.workspace(c)
	if !ok {
		return
	}
	chunkID := c.Param("chunk_id")
	if _, err := uuid.Parse(chunkID); err != nil {
		h.writeError(c, http.StatusBadRequest, "invalid_request", "chunk_id 不是合法 UUID", false)
		return
	}
	preview, err := h.store.GetChunkPreview(c.Request.Context(), workspaceID, chunkID)
	if err != nil {
		if strings.Contains(err.Error(), "不存在") {
			h.writeError(c, http.StatusNotFound, "not_found", "切片不存在", false)
			return
		}
		h.logger.Warn("查询切片预览失败", "error", err)
		h.writeError(c, http.StatusInternalServerError, "internal_error", "查询切片预览失败", true)
		return
	}
	c.JSON(http.StatusOK, preview)
}

func (h *Handler) Metrics(c *gin.Context) {
	workspaceID, ok := h.workspace(c)
	if !ok {
		return
	}
	hours := 24
	if raw := c.Query("hours"); raw != "" {
		if parsed, err := time.ParseDuration(raw + "h"); err == nil {
			hours = int(parsed.Hours())
		}
	}
	if hours < 1 {
		hours = 1
	}
	if hours > 168 {
		hours = 168
	}
	overview, err := h.store.MetricsOverview(
		c.Request.Context(),
		workspaceID,
		time.Now().Add(-time.Duration(hours)*time.Hour),
		hours,
	)
	if err != nil {
		h.logger.Warn("聚合监控指标失败", "error", err)
		h.writeError(c, http.StatusInternalServerError, "internal_error", "聚合监控指标失败", true)
		return
	}
	c.JSON(http.StatusOK, overview)
}

// Stream 透传引擎 SSE，同时旁路解析 TTFT、Token、引用与检索诊断。
func (h *Handler) Stream(c *gin.Context) {
	var request publicChatRequest
	if err := c.ShouldBindJSON(&request); err != nil {
		h.writeError(c, http.StatusBadRequest, "invalid_request", "请求体不是合法 JSON", false)
		return
	}
	request.Query = strings.TrimSpace(request.Query)
	if request.Query == "" || len(request.Query) > 4000 {
		h.writeError(c, http.StatusBadRequest, "invalid_request", "query 长度必须在 1-4000 字符", false)
		return
	}
	mode := request.Mode
	if mode == "" {
		mode = "rag"
	}
	if mode != "rag" && mode != "agent" {
		h.writeError(c, http.StatusBadRequest, "invalid_request", "mode 必须是 rag 或 agent", false)
		return
	}
	workspaceID, ok := h.workspace(c)
	if !ok {
		return
	}
	userID := strings.TrimSpace(c.GetHeader("X-User-Id"))
	if _, err := uuid.Parse(userID); err != nil {
		userID = uuid.NewString()
	}
	conversationID := strings.TrimSpace(request.ConversationID)
	if conversationID == "" {
		conversationID = uuid.NewString()
	} else if _, err := uuid.Parse(conversationID); err != nil {
		h.writeError(c, http.StatusBadRequest, "invalid_request", "conversation_id 不是合法 UUID", false)
		return
	}
	kbIDs := request.KBIDs
	if len(kbIDs) == 0 {
		kbIDs = []string{h.cfg.DevKBID}
	}
	if len(kbIDs) > 10 {
		h.writeError(c, http.StatusBadRequest, "invalid_request", "kb_ids 最多 10 个", false)
		return
	}
	for _, kbID := range kbIDs {
		if _, err := uuid.Parse(kbID); err != nil {
			h.writeError(c, http.StatusBadRequest, "invalid_request", "kb_ids 包含非法 UUID", false)
			return
		}
	}

	traceID := strings.TrimSpace(c.GetHeader("X-Trace-Id"))
	if _, err := uuid.Parse(traceID); err != nil {
		traceID = uuid.NewString()
	}
	requestID := c.GetString("request_id")
	messageID := uuid.NewString()
	userMessageID := uuid.NewString()
	title := truncate(request.Query, 60)
	if err := h.store.EnsureConversation(
		c.Request.Context(), conversationID, workspaceID, kbIDs[0], title, mode,
	); err != nil {
		h.logger.Warn("创建会话失败", "error", err)
		h.writeError(c, http.StatusInternalServerError, "internal_error", "创建会话失败", true)
		return
	}
	if err := h.store.CreateMessage(
		c.Request.Context(), userMessageID, workspaceID, conversationID,
		"user", request.Query, "completed",
	); err != nil {
		h.logger.Warn("创建用户消息失败", "error", err)
		h.writeError(c, http.StatusInternalServerError, "internal_error", "创建消息失败", true)
		return
	}
	if err := h.store.CreateMessage(
		c.Request.Context(), messageID, workspaceID, conversationID,
		"assistant", "", "streaming",
	); err != nil {
		h.logger.Warn("创建 assistant 消息失败", "error", err)
		h.writeError(c, http.StatusInternalServerError, "internal_error", "创建消息失败", true)
		return
	}

	payload := map[string]any{
		"workspace_id":    workspaceID,
		"conversation_id": conversationID,
		"message_id":      messageID,
		"user_id":         userID,
		"query":           request.Query,
		"kb_ids":          kbIDs,
		"mode":            mode,
	}
	addRaw(payload, "agent", request.Agent)
	addRaw(payload, "retrieval", request.Retrieval)
	addRaw(payload, "generation", request.Generation)
	addRaw(payload, "history", request.History)
	body, err := json.Marshal(payload)
	if err != nil {
		h.writeError(c, http.StatusInternalServerError, "internal_error", "构造引擎请求失败", true)
		return
	}

	startedAt := time.Now()
	upstream, err := h.engine.OpenChatStream(c.Request.Context(), body, map[string]string{
		"X-Request-Id":       requestID,
		"X-Trace-Id":         traceID,
		"X-Workspace-Id":     workspaceID,
		"X-User-Id":          userID,
		"X-Contract-Version": "1.0.0",
	})
	if err != nil {
		latency := int(time.Since(startedAt).Milliseconds())
		h.failMessage(c, workspaceID, messageID, "dependency_unavailable", "连接 AI 引擎失败")
		h.recordRequestLog(workspaceID, userID, requestID, traceID, http.StatusBadGateway, latency, nil, "", 0, 0, "dependency_unavailable", c.ClientIP(), c.Request.UserAgent())
		h.writeError(c, http.StatusBadGateway, "dependency_unavailable", "连接 AI 引擎失败", true)
		return
	}
	defer func() { _ = upstream.Body.Close() }()

	if upstream.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(io.LimitReader(upstream.Body, maxUpstreamErrorBytes))
		latency := int(time.Since(startedAt).Milliseconds())
		h.failMessage(c, workspaceID, messageID, "engine_error", "AI 引擎返回错误")
		h.recordRequestLog(workspaceID, userID, requestID, traceID, upstream.StatusCode, latency, nil, "", 0, 0, "engine_error", c.ClientIP(), c.Request.UserAgent())
		contentType := upstream.Header.Get("Content-Type")
		if contentType == "" {
			contentType = "application/json; charset=utf-8"
		}
		c.Data(upstream.StatusCode, contentType, raw)
		return
	}

	record := &streamRecord{
		workspaceID:    workspaceID,
		userID:         userID,
		conversationID: conversationID,
		messageID:      messageID,
		requestID:      requestID,
		traceID:        traceID,
		route:          c.FullPath(),
		query:          request.Query,
		clientIP:       c.ClientIP(),
		userAgent:      c.Request.UserAgent(),
		citationSeen:   make(map[int]struct{}),
		startedAt:      startedAt,
	}
	record.model = ""

	c.Header("Content-Type", "text/event-stream; charset=utf-8")
	c.Header("Cache-Control", "no-cache, no-transform")
	c.Header("X-Accel-Buffering", "no")
	c.Header("Connection", "keep-alive")
	c.Status(http.StatusOK)
	c.Writer.Flush()

	reader := bufio.NewReaderSize(upstream.Body, 32*1024)
	var eventName string
	var dataLines []string

	for {
		line, readErr := reader.ReadString('\n')
		if line != "" {
			if _, writeErr := c.Writer.Write([]byte(line)); writeErr != nil {
				record.clientGone = true
				break
			}
			c.Writer.Flush()
			trimmed := strings.TrimRight(line, "\r\n")
			switch {
			case strings.HasPrefix(trimmed, "event:"):
				eventName = strings.TrimSpace(strings.TrimPrefix(trimmed, "event:"))
			case strings.HasPrefix(trimmed, "data:"):
				dataLines = append(dataLines, strings.TrimPrefix(strings.TrimPrefix(trimmed, "data:"), " "))
			case trimmed == "":
				if eventName != "" && len(dataLines) > 0 {
					h.handleEvent(record, eventName, strings.Join(dataLines, "\n"))
				}
				eventName = ""
				dataLines = nil
			}
		}
		if readErr != nil {
			break
		}
	}
	if eventName != "" && len(dataLines) > 0 {
		h.handleEvent(record, eventName, strings.Join(dataLines, "\n"))
	}

	if record.finishReason == "" && record.errorCode == "" {
		record.errorCode = "stream_canceled"
	}
	if record.clientGone {
		record.errorCode = "stream_canceled"
	}
	h.persist(record, record.finishReason, upstream.StatusCode)
}

func (h *Handler) handleEvent(record *streamRecord, name, raw string) {
	var data eventData
	if err := json.Unmarshal([]byte(raw), &data); err != nil {
		h.logger.Debug("忽略无法解析的 SSE data", "event", name, "error", err)
		return
	}
	switch name {
	case "meta":
		if record.model == "" {
			record.model = data.Model
		}
	case "generating":
		if data.Delta != "" {
			if record.firstTokenAt.IsZero() {
				record.firstTokenAt = time.Now()
			}
			record.answer.WriteString(data.Delta)
		}
	case "citation":
		if data.Citation != nil {
			h.addCitation(record, *data.Citation)
		}
	case "usage":
		if data.Usage != nil {
			record.usage = *data.Usage
			if data.Usage.Model != "" {
				record.model = data.Usage.Model
			}
		}
	case "retrieval":
		record.diagnostics = append(json.RawMessage(nil), data.Diagnostics...)
		record.traceRecord = parseRetrievalCounts(data.Diagnostics, record.traceID)
		if record.traceID == "" && record.traceRecord != nil {
			record.traceID = record.traceRecord.traceID
		}
	case "done":
		record.finishReason = data.FinishReason
		if data.Usage != nil {
			record.usage = *data.Usage
			if data.Usage.Model != "" {
				record.model = data.Usage.Model
			}
		}
		for _, citation := range data.Citations {
			h.addCitation(record, citation)
		}
	case "error":
		if data.Error != nil {
			record.errorCode = data.Error.Code
		} else {
			record.errorCode = "internal_error"
		}
	}
}

func (h *Handler) addCitation(record *streamRecord, payload citationPayload) {
	if payload.Index <= 0 {
		return
	}
	if _, exists := record.citationSeen[payload.Index]; exists {
		return
	}
	record.citationSeen[payload.Index] = struct{}{}
	pageNo := 0
	if payload.PageNo != nil {
		pageNo = *payload.PageNo
	}
	bbox := payload.BBox
	if len(bbox) == 0 {
		bbox = json.RawMessage(`{}`)
	}
	record.citations = append(record.citations, store.CitationRecord{
		Index:         payload.Index,
		ChunkID:       payload.ChunkID,
		DocumentID:    payload.DocumentID,
		DocumentTitle: payload.DocumentTitle,
		PageNo:        pageNo,
		BBox:          bbox,
		Quote:         payload.Quote,
		RerankScore:   payload.RerankScore,
	})
}

func (h *Handler) persist(record *streamRecord, finishReason string, statusCode int) {
	totalMS := int(time.Since(record.startedAt).Milliseconds())
	var ttftMS *int
	if !record.firstTokenAt.IsZero() {
		value := int(record.firstTokenAt.Sub(record.startedAt).Milliseconds())
		ttftMS = &value
	}
	if record.model == "" {
		record.model = record.usage.Model
	}
	status := "completed"
	finish := finishReason
	if record.errorCode != "" {
		if record.errorCode == "stream_canceled" {
			status = "canceled"
			statusCode = 499
		} else {
			status = "failed"
			finish = ""
		}
	}
	workspaceID := record.workspaceID
	messageID := record.messageID
	citations := append([]store.CitationRecord(nil), record.citations...)
	diagnostics := append(json.RawMessage(nil), record.diagnostics...)
	trace := record.traceRecord
	usage := record.usage
	model := record.model
	errorCode := record.errorCode
	answer := record.answer.String()

	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if err := h.store.UpdateAssistantMessage(ctx, store.MessageUpdate{
			MessageID:        messageID,
			WorkspaceID:      workspaceID,
			Content:          answer,
			Status:           status,
			FinishReason:     finish,
			Model:            model,
			PromptTokens:     usage.PromptTokens,
			CompletionTokens: usage.CompletionTokens,
			EstimatedCostCNY: usage.EstimatedCostCNY,
			TTFTMS:           ttftMS,
			TotalMS:          &totalMS,
			RetrievalTraceID: record.traceID,
			ErrorCode:        errorCode,
		}); err != nil {
			h.logger.Warn("更新 assistant 消息失败", "error", err)
		}
		if err := h.store.InsertCitations(ctx, workspaceID, messageID, citations); err != nil {
			h.logger.Warn("写入引用失败", "error", err)
		}
		if trace != nil && len(diagnostics) > 0 {
			if err := h.store.InsertRetrievalTrace(ctx, store.RetrievalTraceRecord{
				WorkspaceID:       workspaceID,
				MessageID:         messageID,
				ConversationID:    record.conversationID,
				TraceID:           record.traceID,
				Source:            "chat",
				QueryOriginal:     trace.queryOriginal,
				QueryRewritten:    trace.queryRewritten,
				Strategy:          json.RawMessage(`{"mode":"hybrid"}`),
				Config:            trace.config,
				Diagnostics:       diagnostics,
				VectorCandidates:  trace.vector,
				LexicalCandidates: trace.lexical,
				FusedCandidates:   trace.fused,
				RerankCandidates:  trace.rerank,
				SelectedCount:     trace.selected,
				TotalLatencyMS:    trace.totalLatencyMS,
			}); err != nil {
				h.logger.Warn("写入检索留痕失败", "error", err)
			}
		}
		h.recordRequestLog(
			workspaceID, record.userID, record.requestID, record.traceID,
			statusCode, totalMS, ttftMS, model, usage.PromptTokens,
			usage.CompletionTokens, errorCode, record.clientIP, record.userAgent,
		)
	}()
}

func (h *Handler) recordRequestLog(
	workspaceID, userID, requestID, traceID string,
	statusCode, latencyMS int,
	ttftMS *int,
	model string,
	promptTokens, completionTokens int,
	errorCode, clientIP, userAgent string,
) {
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := h.store.InsertRequestLog(ctx, store.RequestLogRecord{
			WorkspaceID:      workspaceID,
			UserID:           userID,
			RequestID:        requestID,
			TraceID:          traceID,
			Route:            "/api/v1/chat/stream",
			Method:           http.MethodPost,
			StatusCode:       statusCode,
			LatencyMS:        latencyMS,
			TTFTMS:           ttftMS,
			Model:            model,
			PromptTokens:     promptTokens,
			CompletionTokens: completionTokens,
			ClientIP:         clientIP,
			UserAgent:        userAgent,
			ErrorCode:        errorCode,
		}); err != nil {
			h.logger.Warn("写入请求日志失败", "error", err)
		}
	}()
}

func (h *Handler) failMessage(c *gin.Context, workspaceID, messageID, code, message string) {
	_ = h.store.UpdateAssistantMessage(c.Request.Context(), store.MessageUpdate{
		MessageID:   messageID,
		WorkspaceID: workspaceID,
		Status:      "failed",
		ErrorCode:   code,
		Content:     message,
	})
}

func (h *Handler) workspace(c *gin.Context) (string, bool) {
	workspaceID := strings.TrimSpace(c.GetHeader("X-Workspace-Id"))
	if workspaceID == "" {
		workspaceID = h.cfg.DevWorkspaceID
	}
	if _, err := uuid.Parse(workspaceID); err != nil {
		h.writeError(c, http.StatusBadRequest, "invalid_request", "X-Workspace-Id 不是合法 UUID", false)
		return "", false
	}
	return workspaceID, true
}

func (h *Handler) writeError(c *gin.Context, status int, code, message string, retryable bool) {
	requestID := c.GetString("request_id")
	c.JSON(status, gin.H{
		"error": gin.H{
			"code":       code,
			"message":    message,
			"retryable":  retryable,
			"request_id": requestID,
		},
	})
}

func addRaw(payload map[string]any, key string, raw json.RawMessage) {
	if len(raw) == 0 || string(raw) == "null" {
		return
	}
	payload[key] = raw
}

func truncate(value string, limit int) string {
	runes := []rune(value)
	if len(runes) <= limit {
		return value
	}
	return string(runes[:limit])
}

func parseRetrievalCounts(raw json.RawMessage, fallbackTraceID string) *retrievalCounts {
	if len(raw) == 0 {
		return nil
	}
	var payload struct {
		TraceID string `json:"trace_id"`
		Query   struct {
			Original  string `json:"original"`
			Rewritten string `json:"rewritten"`
		} `json:"query"`
		Config json.RawMessage `json:"config"`
		Stages struct {
			Vector struct {
				Candidates int `json:"candidates"`
			} `json:"vector"`
			Lexical struct {
				Candidates int `json:"candidates"`
			} `json:"lexical"`
			Fusion struct {
				Candidates int `json:"candidates"`
			} `json:"fusion"`
			Rerank struct {
				Candidates int `json:"candidates"`
			} `json:"rerank"`
		} `json:"stages"`
		SelectedCount  int     `json:"selected_count"`
		TotalLatencyMS float64 `json:"total_latency_ms"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil
	}
	traceID := payload.TraceID
	if traceID == "" {
		traceID = fallbackTraceID
	}
	return &retrievalCounts{
		traceID:        traceID,
		queryOriginal:  payload.Query.Original,
		queryRewritten: payload.Query.Rewritten,
		config:         payload.Config,
		vector:         payload.Stages.Vector.Candidates,
		lexical:        payload.Stages.Lexical.Candidates,
		fused:          payload.Stages.Fusion.Candidates,
		rerank:         payload.Stages.Rerank.Candidates,
		selected:       payload.SelectedCount,
		totalLatencyMS: int(payload.TotalLatencyMS),
	}
}
