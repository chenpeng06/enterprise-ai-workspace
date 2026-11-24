// Package contract 定义 gateway-go 与 ai-engine-py 的契约常量与流式消息结构。
// 权威定义：docs/contracts/ai-engine-internal-v1.schema.json（v1.0.0）。
package contract

import "encoding/json"

const (
	Version = "1.0.0"

	EventMeta        = "meta"
	EventThinking    = "thinking"
	EventToolCalling = "tool_calling"
	EventReranking   = "reranking"
	EventRetrieval   = "retrieval"
	EventGenerating  = "generating"
	EventCitation    = "citation"
	EventUsage       = "usage"
	EventError       = "error"
	EventDone        = "done"
)

// SSEEnvelope 是 SSE data: 行的统一外层结构；Data 保持原始字节以便无损透传。
type SSEEnvelope struct {
	Event string          `json:"event"`
	ID    *int64          `json:"id,omitempty"`
	Data  json.RawMessage `json:"data"`
}

type Usage struct {
	PromptTokens     int      `json:"prompt_tokens"`
	CompletionTokens int      `json:"completion_tokens"`
	TotalTokens      int      `json:"total_tokens"`
	Model            string   `json:"model"`
	EstimatedCostCNY *float64 `json:"estimated_cost_cny,omitempty"`
}

type Timings struct {
	TTFTMS       float64 `json:"ttft_ms"`
	RetrievalMS  float64 `json:"retrieval_ms"`
	RerankMS     float64 `json:"rerank_ms"`
	GenerationMS float64 `json:"generation_ms"`
	TotalMS      float64 `json:"total_ms"`
}

type Citation struct {
	Index         int      `json:"index"`
	ChunkID       string   `json:"chunk_id"`
	ParentChunkID *string  `json:"parent_chunk_id,omitempty"`
	DocumentID    string   `json:"document_id"`
	DocumentTitle string   `json:"document_title"`
	PageNo        *int     `json:"page_no,omitempty"`
	CharStart     *int     `json:"char_start,omitempty"`
	CharEnd       *int     `json:"char_end,omitempty"`
	Quote         string   `json:"quote"`
	RerankScore   *float64 `json:"rerank_score,omitempty"`
}

type DoneData struct {
	MessageID    string     `json:"message_id"`
	TraceID      string     `json:"trace_id,omitempty"`
	FinishReason string     `json:"finish_reason"`
	Usage        Usage      `json:"usage"`
	Timings      Timings    `json:"timings"`
	Citations    []Citation `json:"citations"`
	Model        string     `json:"model,omitempty"`
}

// RetrievalMetrics 是网关侧只需要消费的检索漏斗统计字段，
// 完整诊断数据由前端直接从 retrieval 事件读取。
type RetrievalMetrics struct {
	TraceID        string  `json:"trace_id"`
	SelectedCount  int     `json:"selected_count"`
	TotalLatencyMS float64 `json:"total_latency_ms"`
}
