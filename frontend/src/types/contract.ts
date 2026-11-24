/**
 * gateway-go ↔ ai-engine-py 内部契约 v1.0.0 的前端类型镜像。
 *
 * 权威定义：docs/contracts/ai-engine-internal-v1.schema.json
 * 契约文档：docs/ARCHITECTURE.md
 *
 * 只镜像前端实际消费的消息；新增字段时必须先更新 JSON Schema，再同步此文件。
 */

export type UUID = string;
export type ISODateTime = string;
export type JsonObject = Record<string, unknown>;

export const CONTRACT_VERSION = "1.0.0" as const;

export type ErrorCode =
  | "invalid_request"
  | "unauthorized"
  | "forbidden"
  | "workspace_mismatch"
  | "not_found"
  | "conflict"
  | "idempotency_conflict"
  | "unsupported_media_type"
  | "payload_too_large"
  | "parse_failed"
  | "embedding_failed"
  | "index_failed"
  | "retrieval_failed"
  | "rerank_failed"
  | "llm_rate_limited"
  | "llm_timeout"
  | "llm_unavailable"
  | "content_filtered"
  | "refused"
  | "stream_canceled"
  | "dependency_unavailable"
  | "internal_error";

export interface ErrorDetail {
  code: ErrorCode;
  message: string;
  retryable: boolean;
  trace_id?: UUID | null;
  stage?: string | null;
  details?: JsonObject | null;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

export interface BoundingBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export type ChunkType = "text" | "table" | "image_caption" | "code" | "heading";

export interface RetrievalConfig {
  top_k?: number;
  vector_top_k?: number;
  lexical_top_k?: number;
  vector_weight?: number;
  lexical_weight?: number;
  min_vector_score?: number;
  min_rerank_score?: number;
  enable_rerank?: boolean;
  rerank_model?: string;
  fusion?: { algorithm: "rrf"; rrf_k?: number };
  rewrite?: { enabled?: boolean; model?: string; max_variants?: number };
  filters?: {
    document_ids?: UUID[];
    chunk_types?: ChunkType[];
    created_after?: ISODateTime;
    metadata?: JsonObject;
  };
}

export interface SearchCandidate {
  chunk_id: UUID;
  parent_chunk_id?: UUID | null;
  document_id: UUID;
  document_title: string;
  file_name?: string;
  chunk_index?: number;
  chunk_type?: ChunkType;
  section_path?: string[];
  page_no?: number | null;
  page_span?: [number, number] | null;
  bbox?: BoundingBox | null;
  char_start?: number | null;
  char_end?: number | null;
  content_preview: string;
  token_count?: number | null;
  vector_score?: number | null;
  vector_rank?: number | null;
  bm25_score?: number | null;
  bm25_rank?: number | null;
  rrf_score?: number | null;
  fused_rank?: number | null;
  rerank_score?: number | null;
  rerank_rank?: number | null;
  rank_delta?: number | null;
  selected: boolean;
  citation_index?: number | null;
}

export interface RetrievalStageStats {
  vector: {
    model: string;
    dimensions: number;
    metric: "cosine" | "l2" | "inner_product";
    top_k: number;
    candidates: number;
    latency_ms: number;
  };
  lexical: {
    scorer: "bm25" | "ts_rank_cd";
    config?: string;
    top_k: number;
    candidates: number;
    latency_ms: number;
  };
  fusion: {
    algorithm: "rrf";
    rrf_k: number;
    candidates: number;
    latency_ms: number;
  };
  rerank: {
    enabled: boolean;
    model?: string | null;
    top_k?: number;
    score_threshold?: number;
    candidates: number;
    passed: number;
    latency_ms: number;
  };
}

export interface RetrievalDiagnostics {
  trace_id: UUID;
  query: {
    original: string;
    rewritten: string;
    rewrite_model?: string | null;
    rewrite_latency_ms?: number | null;
    language?: string;
  };
  config: RetrievalConfig;
  stages: RetrievalStageStats;
  candidates: SearchCandidate[];
  selected_count: number;
  total_latency_ms: number;
}

export interface AgentConfig {
  name: "ops_assistant";
  max_steps?: number;
  enable_tools?: boolean;
  allowed_tools?: string[];
  reviewer?: {
    enabled?: boolean;
    min_context_score?: number;
    max_unsupported_claims?: number;
    refusal_message?: string;
  };
  planner?: { enabled?: boolean; max_plan_steps?: number };
}

export interface GenerationConfig {
  model?: string;
  temperature?: number;
  top_p?: number;
  max_tokens?: number;
  stop?: string[];
  citation_style?: "numeric" | "footnote";
  response_format?: "markdown" | "text";
}

export interface ChatStreamRequest {
  workspace_id: UUID;
  conversation_id: UUID;
  message_id: UUID;
  user_id: UUID;
  query: string;
  kb_ids: UUID[];
  mode?: "rag" | "agent";
  agent?: AgentConfig;
  retrieval?: RetrievalConfig;
  generation?: GenerationConfig;
  history?: Array<{ role: "user" | "assistant"; content: string }>;
  locale?: string;
  metadata?: JsonObject;
}

export interface Citation {
  index: number;
  chunk_id: UUID;
  parent_chunk_id?: UUID | null;
  document_id: UUID;
  document_title: string;
  page_no?: number | null;
  bbox?: BoundingBox | null;
  char_start?: number | null;
  char_end?: number | null;
  quote: string;
  rerank_score?: number | null;
}

export interface Usage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  model: string;
  estimated_cost_cny?: number | null;
}

export interface Timings {
  ttft_ms: number;
  retrieval_ms: number;
  rerank_ms: number;
  generation_ms: number;
  total_ms: number;
}

export interface AgentStepSummary {
  step_index: number;
  node: "planner" | "rag_retrieve" | "tools" | "reviewer" | "writer" | "system";
  status: "started" | "succeeded" | "failed" | "skipped";
  title?: string;
  tool_name?: string | null;
  latency_ms?: number | null;
}

export interface MetaData {
  message_id: UUID;
  conversation_id: UUID;
  trace_id: UUID;
  workspace_id: UUID;
  mode: "rag" | "agent";
  agent_name?: string | null;
  model: string;
  contract_version: typeof CONTRACT_VERSION;
  server_time: ISODateTime;
}

export interface PlanStep {
  step_index: number;
  action: "retrieve" | "tool" | "review" | "answer";
  description: string;
  tool_name?: string | null;
}

export interface ThinkingData {
  node: "planner" | "rag_retrieve" | "tools" | "reviewer" | "writer" | "system";
  step_index: number;
  step_id?: string;
  status: "started" | "succeeded" | "failed" | "skipped";
  title: string;
  detail?: string | null;
  started_at?: ISODateTime;
  latency_ms?: number | null;
  plan?: PlanStep[] | null;
  attributes?: JsonObject | null;
}

export interface ToolCallingData {
  call_id: string;
  node?: "tools" | "rag_retrieve";
  tool_name: string;
  arguments: JsonObject;
  status: "started" | "succeeded" | "failed";
  result_summary?: string | null;
  result?: JsonObject | null;
  latency_ms?: number | null;
  error?: ErrorDetail | null;
}

export interface RerankingData {
  node?: "rag_retrieve" | "tools";
  status: "started" | "succeeded" | "failed" | "skipped";
  model?: string | null;
  candidate_count: number;
  top_n: number;
  score_threshold?: number;
  passed_count?: number | null;
  latency_ms?: number | null;
  error?: ErrorDetail | null;
}

export interface RetrievalData {
  message_id: UUID;
  diagnostics: RetrievalDiagnostics;
}

export interface GeneratingData {
  message_id: UUID;
  delta: string;
  reasoning_delta?: string | null;
  index: number;
  tokens_so_far?: number;
}

export interface CitationData {
  message_id: UUID;
  citation: Citation;
}

export interface UsageData {
  message_id: UUID;
  usage: Usage;
}

export interface ErrorData {
  message_id?: UUID | null;
  error: ErrorDetail;
}

export interface DoneData {
  message_id: UUID;
  trace_id?: UUID;
  finish_reason: "stop" | "length" | "refused" | "error" | "canceled";
  usage: Usage;
  timings: Timings;
  citations: Citation[];
  steps?: AgentStepSummary[];
  model?: string;
}

export interface SSEEnvelope<TEvent extends string, TData> {
  event: TEvent;
  id?: number;
  data: TData;
}

export type SSEEvent =
  | SSEEnvelope<"meta", MetaData>
  | SSEEnvelope<"thinking", ThinkingData>
  | SSEEnvelope<"tool_calling", ToolCallingData>
  | SSEEnvelope<"reranking", RerankingData>
  | SSEEnvelope<"retrieval", RetrievalData>
  | SSEEnvelope<"generating", GeneratingData>
  | SSEEnvelope<"citation", CitationData>
  | SSEEnvelope<"usage", UsageData>
  | SSEEnvelope<"error", ErrorData>
  | SSEEnvelope<"done", DoneData>;

export const SSE_EVENT_NAMES = [
  "meta",
  "thinking",
  "tool_calling",
  "reranking",
  "retrieval",
  "generating",
  "citation",
  "usage",
  "error",
  "done",
] as const;

export type SseEventName = (typeof SSE_EVENT_NAMES)[number];

export interface IngestCreateResponse {
  task_id: UUID;
  document_id: UUID;
  status: "queued";
  accepted_at: ISODateTime;
  deduplicated?: boolean;
  estimated_pages?: number | null;
}

export interface IngestTaskStatus {
  task_id: UUID;
  document_id: UUID;
  workspace_id: UUID;
  knowledge_base_id: UUID;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  stage:
    | "queued"
    | "fetching"
    | "parsing"
    | "chunking"
    | "embedding"
    | "indexing"
    | "completed"
    | "failed"
    | "canceled";
  progress: number;
  attempt?: number;
  counters?: {
    pages?: number;
    parent_chunks?: number;
    child_chunks?: number;
    embedding_tokens?: number;
    ocr_pages?: number;
  };
  stage_timings?: Array<{
    stage: string;
    started_at?: ISODateTime;
    finished_at?: ISODateTime;
    latency_ms: number;
  }>;
  error?: ErrorDetail | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  started_at?: ISODateTime | null;
  finished_at?: ISODateTime | null;
}
