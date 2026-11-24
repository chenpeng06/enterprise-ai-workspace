import type {
  Citation,
  RetrievalDiagnostics,
  Timings,
  Usage,
} from "@/types/contract";
import type { CitationTarget } from "@/types/public";

export type ChatMessageStatus =
  | "streaming"
  | "completed"
  | "refused"
  | "failed"
  | "canceled";

export type ProgressStatus = "started" | "succeeded" | "failed" | "skipped";

export interface ProgressItem {
  id: string;
  label: string;
  detail?: string;
  status: ProgressStatus;
  kind: "plan" | "tool" | "rerank" | "review" | "write" | "retrieval";
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  status: ChatMessageStatus;
  usage?: Usage;
  timings?: Timings;
  error?: string;
  progress: ProgressItem[];
}

export interface ChatSession {
  messages: ChatMessage[];
  diagnostics: RetrievalDiagnostics | null;
  streaming: boolean;
  conversationId: string;
  error: string | null;
  activeCitation: CitationTarget | null;
}
