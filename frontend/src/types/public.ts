import type {
  BoundingBox,
  Citation,
  RetrievalConfig,
  UUID,
} from "@/types/contract";

export interface BootstrapResponse {
  workspace_id: UUID;
  kb_id: UUID;
  suggestions: string[];
}

export interface PublicChatHistoryItem {
  role: "user" | "assistant";
  content: string;
}

export interface PublicChatRequest {
  conversation_id?: UUID;
  query: string;
  kb_ids?: UUID[];
  mode?: "rag" | "agent";
  retrieval?: RetrievalConfig;
  history?: PublicChatHistoryItem[];
}

export interface ChunkPreview {
  chunk_id: UUID;
  parent_chunk_id?: UUID;
  document_id: UUID;
  document_title: string;
  file_name: string;
  content: string;
  parent_content?: string;
  page_no?: number;
  bbox?: BoundingBox | null;
  char_start?: number;
  char_end?: number;
  section_path: string[];
  chunk_type: string;
  page_count: number;
  token_count: number;
}

export interface MetricsTotals {
  requests: number;
  chat_requests: number;
  rate_limited: number;
  avg_ttft_ms: number;
  p95_ttft_ms: number;
  total_tokens: number;
}

export interface TrendPoint {
  bucket: string;
  avg_ttft_ms?: number;
  count: number;
}

export interface RateLimitRecord {
  route: string;
  scope: string;
  limit_value: number;
  observed: number;
  retry_after_ms: number;
  client_ip?: string;
  created_at: string;
}

export interface KnowledgeBaseMetrics {
  queries: number;
  hits: number;
  hit_rate: number;
}

export interface MetricsOverview {
  hours: number;
  totals: MetricsTotals;
  ttft_trend: TrendPoint[];
  rate_limit_trend: TrendPoint[];
  knowledge_base: KnowledgeBaseMetrics;
  recent_rate_limits: RateLimitRecord[];
}

export interface CitationTarget {
  citation: Citation;
  messageId: string;
}
