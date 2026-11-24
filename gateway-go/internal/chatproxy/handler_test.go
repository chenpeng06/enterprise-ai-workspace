package chatproxy

import (
	"encoding/json"
	"io"
	"log/slog"
	"testing"
	"time"
)

func testHandler() *Handler {
	return &Handler{
		logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
}

func TestHandleEventStreamsAnswerAndCitations(t *testing.T) {
	handler := testHandler()
	record := &streamRecord{citationSeen: make(map[int]struct{})}

	handler.handleEvent(record, "generating", `{"message_id":"m1","delta":"第一段","index":0}`)
	handler.handleEvent(record, "generating", `{"message_id":"m1","delta":"第二段","index":1}`)
	handler.handleEvent(record, "citation", `{
		"message_id":"m1",
		"citation":{
			"index":1,
			"chunk_id":"0192f0e0-0020-7c2d-8e3f-0a1b2c3d4e5f",
			"document_id":"0192f0e0-0003-7c2d-8e3f-0a1b2c3d4e5f",
			"document_title":"研发运维规范",
			"page_no":18,
			"bbox":{"x0":0.1,"y0":0.2,"x1":0.9,"y1":0.3},
			"quote":"自动回滚",
			"rerank_score":0.91
		}
	}`)
	handler.handleEvent(record, "citation", `{
		"message_id":"m1",
		"citation":{
			"index":1,
			"chunk_id":"0192f0e0-0020-7c2d-8e3f-0a1b2c3d4e5f",
			"document_id":"0192f0e0-0003-7c2d-8e3f-0a1b2c3d4e5f",
			"document_title":"研发运维规范",
			"quote":"重复引用"
		}
	}`)
	handler.handleEvent(record, "usage", `{
		"message_id":"m1",
		"usage":{"prompt_tokens":10,"completion_tokens":20,"total_tokens":30,"model":"deepseek-flash"}
	}`)
	handler.handleEvent(record, "done", `{
		"message_id":"m1",
		"finish_reason":"stop",
		"usage":{"prompt_tokens":10,"completion_tokens":20,"total_tokens":30,"model":"deepseek-flash"},
		"timings":{"ttft_ms":1,"retrieval_ms":1,"rerank_ms":0,"generation_ms":1,"total_ms":2},
		"citations":[]
	}`)

	if got := record.answer.String(); got != "第一段第二段" {
		t.Fatalf("answer 透传错误: %q", got)
	}
	if record.firstTokenAt.IsZero() {
		t.Fatal("首个 generating 事件后应记录首字时间")
	}
	if time.Since(record.firstTokenAt) > time.Minute {
		t.Fatal("首字时间异常")
	}
	if len(record.citations) != 1 {
		t.Fatalf("引用应去重为 1 条，实际 %d", len(record.citations))
	}
	if record.citations[0].PageNo != 18 || record.citations[0].RerankScore == nil {
		t.Fatalf("引用字段解析错误: %+v", record.citations[0])
	}
	if record.usage.TotalTokens != 30 || record.model != "deepseek-flash" {
		t.Fatalf("usage 解析错误: %+v model=%q", record.usage, record.model)
	}
	if record.finishReason != "stop" {
		t.Fatalf("finish_reason 解析错误: %q", record.finishReason)
	}
}

func TestParseRetrievalCounts(t *testing.T) {
	raw := json.RawMessage(`{
		"trace_id":"0192f0e0-0004-7c2d-8e3f-0a1b2c3d4e5f",
		"query":{"original":"灰度","rewritten":"灰度 rollback"},
		"config":{"top_k":3},
		"stages":{
			"vector":{"candidates":12},
			"lexical":{"candidates":7},
			"fusion":{"candidates":15},
			"rerank":{"candidates":15}
		},
		"selected_count":3,
		"total_latency_ms":42.6
	}`)
	counts := parseRetrievalCounts(raw, "fallback")
	if counts == nil {
		t.Fatal("应解析出检索计数")
	}
	if counts.traceID == "" || counts.queryRewritten != "灰度 rollback" {
		t.Fatalf("trace/query 解析错误: %+v", counts)
	}
	if counts.vector != 12 || counts.lexical != 7 || counts.fused != 15 || counts.rerank != 15 {
		t.Fatalf("候选数解析错误: %+v", counts)
	}
	if counts.selected != 3 || counts.totalLatencyMS != 42 {
		t.Fatalf("选中数/耗时解析错误: %+v", counts)
	}
	if string(counts.config) != `{"top_k":3}` {
		t.Fatalf("config 透传错误: %s", counts.config)
	}
}

func TestParseRetrievalCountsFallbackTrace(t *testing.T) {
	counts := parseRetrievalCounts(
		json.RawMessage(`{"selected_count":0}`),
		"0192f0e0-0005-7c2d-8e3f-0a1b2c3d4e5f",
	)
	if counts == nil || counts.traceID != "0192f0e0-0005-7c2d-8e3f-0a1b2c3d4e5f" {
		t.Fatalf("应回退到请求 trace_id: %+v", counts)
	}
}
