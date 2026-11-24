import { useCallback, useEffect, useRef, useState } from "react";

import { streamChat } from "@/lib/api";
import { SSEHttpError } from "@/lib/sse";
import type {
  Citation,
  RetrievalDiagnostics,
  Usage,
} from "@/types/contract";
import type { CitationTarget, PublicChatHistoryItem } from "@/types/public";

import type {
  ChatMessage,
  ProgressItem,
  ProgressStatus,
} from "./types";

interface UseChatSessionOptions {
  kbIds: string[];
  mode: "rag" | "agent";
}

const NODE_LABELS: Record<string, string> = {
  planner: "任务拆解",
  rag_retrieve: "混合检索",
  tools: "工具调用",
  reviewer: "防幻觉核查",
  writer: "报告生成",
  system: "系统",
};

const NODE_KINDS: Record<string, ProgressItem["kind"]> = {
  planner: "plan",
  rag_retrieve: "retrieval",
  tools: "tool",
  reviewer: "review",
  writer: "write",
  system: "plan",
};

function makeID(): string {
  return crypto.randomUUID();
}

function errorMessage(error: unknown): string {
  if (error instanceof SSEHttpError) {
    if (error.status === 429) {
      return "请求过于频繁，网关已触发 Redis 令牌桶限流，请稍后再试。";
    }
    return `网关请求失败（HTTP ${error.status}）`;
  }
  return error instanceof Error ? error.message : "对话请求失败";
}

export function useChatSession({ kbIds, mode }: UseChatSessionOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [diagnostics, setDiagnostics] = useState<RetrievalDiagnostics | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState(makeID);
  const [activeCitation, setActiveCitation] = useState<CitationTarget | null>(null);

  const conversationIdRef = useRef(conversationId);
  const abortRef = useRef<AbortController | null>(null);
  const streamingRef = useRef(false);
  const assistantIDRef = useRef<string | null>(null);
  const runRef = useRef(0);
  const pendingDeltaRef = useRef("");
  const flushTimerRef = useRef<number | null>(null);

  const flushDelta = useCallback(() => {
    const assistantID = assistantIDRef.current;
    const delta = pendingDeltaRef.current;
    if (!assistantID || !delta) {
      return;
    }
    pendingDeltaRef.current = "";
    setMessages((previous) =>
      previous.map((message) =>
        message.id === assistantID
          ? { ...message, content: message.content + delta }
          : message,
      ),
    );
  }, []);

  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current !== null) {
      return;
    }
    flushTimerRef.current = window.setTimeout(() => {
      flushTimerRef.current = null;
      flushDelta();
    }, 32);
  }, [flushDelta]);

  const clearTimer = useCallback(() => {
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
  }, []);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      clearTimer();
    },
    [clearTimer],
  );

  const patchAssistant = useCallback(
    (assistantID: string, updater: (message: ChatMessage) => ChatMessage) => {
      setMessages((previous) =>
        previous.map((message) => (message.id === assistantID ? updater(message) : message)),
      );
    },
    [],
  );

  const send = useCallback(
    async (rawQuery: string) => {
      const query = rawQuery.trim();
      if (!query || streamingRef.current || kbIds.length === 0) {
        return;
      }

      const history: PublicChatHistoryItem[] = messages
        .filter((message) => message.content.trim().length > 0)
        .slice(-6)
        .map((message) => ({ role: message.role, content: message.content.slice(0, 1500) }));

      const runID = runRef.current + 1;
      runRef.current = runID;
      const assistantID = makeID();
      assistantIDRef.current = assistantID;
      pendingDeltaRef.current = "";

      const userMessage: ChatMessage = {
        id: makeID(),
        role: "user",
        content: query,
        citations: [],
        status: "completed",
        progress: [],
      };
      const assistantMessage: ChatMessage = {
        id: assistantID,
        role: "assistant",
        content: "",
        citations: [],
        status: "streaming",
        progress: [],
      };

      streamingRef.current = true;
      setStreaming(true);
      setError(null);
      setDiagnostics(null);
      setActiveCitation(null);
      setMessages((previous) => [...previous, userMessage, assistantMessage]);

      const controller = new AbortController();
      abortRef.current = controller;

      const patch = (updater: (message: ChatMessage) => ChatMessage) => {
        if (runRef.current !== runID) {
          return;
        }
        patchAssistant(assistantID, updater);
      };

      const upsertProgress = (item: ProgressItem) => {
        patch((message) => {
          const index = message.progress.findIndex((entry) => entry.id === item.id);
          if (index === -1) {
            return { ...message, progress: [...message.progress, item] };
          }
          const progress = [...message.progress];
          progress[index] = { ...progress[index], ...item };
          return { ...message, progress };
        });
      };

      try {
        await streamChat(
          {
            conversation_id: conversationIdRef.current,
            query,
            kb_ids: kbIds,
            mode,
            history,
          },
          {
            onEvent: (event) => {
              if (runRef.current !== runID) {
                return;
              }
              switch (event.event) {
                case "meta":
                  conversationIdRef.current = event.data.conversation_id;
                  setConversationId(event.data.conversation_id);
                  break;
                case "thinking": {
                  const node = event.data.node;
                  upsertProgress({
                    id: event.data.step_id ?? `${node}-${event.data.step_index}`,
                    label: NODE_LABELS[node] ?? event.data.title,
                    detail: event.data.detail ?? undefined,
                    status: event.data.status,
                    kind: NODE_KINDS[node] ?? "plan",
                  });
                  break;
                }
                case "tool_calling": {
                  const isSearch = event.data.tool_name === "search_knowledge_base";
                  upsertProgress({
                    id: event.data.call_id,
                    label: isSearch ? "知识库检索" : event.data.tool_name,
                    detail: event.data.result_summary ?? undefined,
                    status: event.data.status as ProgressStatus,
                    kind: "tool",
                  });
                  break;
                }
                case "reranking":
                  upsertProgress({
                    id: "reranking",
                    label: "Rerank 精排",
                    detail: event.data.status === "skipped"
                      ? "未配置 Rerank，使用 RRF 排名"
                      : `${event.data.candidate_count} 候选 → ${event.data.passed_count ?? 0} 通过`,
                    status: event.data.status,
                    kind: "rerank",
                  });
                  break;
                case "retrieval":
                  setDiagnostics(event.data.diagnostics);
                  upsertProgress({
                    id: "retrieval",
                    label: "检索漏斗",
                    detail: `${event.data.diagnostics.candidates.length} 候选 / ${event.data.diagnostics.selected_count} 入选`,
                    status: "succeeded",
                    kind: "retrieval",
                  });
                  break;
                case "citation": {
                  const citation: Citation = event.data.citation;
                  patch((message) =>
                    message.citations.some((item) => item.index === citation.index)
                      ? message
                      : { ...message, citations: [...message.citations, citation] },
                  );
                  break;
                }
                case "generating":
                  if (event.data.delta) {
                    pendingDeltaRef.current += event.data.delta;
                    scheduleFlush();
                  }
                  break;
                case "usage": {
                  const usage: Usage = event.data.usage;
                  patch((message) => ({ ...message, usage }));
                  break;
                }
                case "done":
                  clearTimer();
                  flushDelta();
                  patch((message) => {
                    const citations =
                      event.data.citations.length > 0 ? event.data.citations : message.citations;
                    return {
                      ...message,
                      content: message.content || "",
                      citations,
                      usage: event.data.usage,
                      timings: event.data.timings,
                      status: event.data.finish_reason === "refused" ? "refused" : "completed",
                      progress: message.progress.map((item) =>
                        item.kind === "write" ? { ...item, status: "succeeded" } : item,
                      ),
                    };
                  });
                  break;
                case "error":
                  clearTimer();
                  flushDelta();
                  setError(event.data.error.message);
                  patch((message) => ({
                    ...message,
                    status: "failed",
                    error: event.data.error.message,
                  }));
                  break;
                default:
                  break;
              }
            },
          },
          controller.signal,
        );
      } catch (caught) {
        if (runRef.current !== runID) {
          return;
        }
        if (controller.signal.aborted) {
          clearTimer();
          flushDelta();
          patch((message) => ({ ...message, status: "canceled" }));
        } else {
          const message = errorMessage(caught);
          setError(message);
          patch((current) => ({ ...current, status: "failed", error: message }));
        }
      } finally {
        if (runRef.current === runID) {
          flushDelta();
          streamingRef.current = false;
          setStreaming(false);
          abortRef.current = null;
        }
      }
    },
    [clearTimer, flushDelta, kbIds, messages, mode, patchAssistant, scheduleFlush],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    runRef.current += 1;
    clearTimer();
    pendingDeltaRef.current = "";
    assistantIDRef.current = null;
    streamingRef.current = false;
    const nextConversationID = makeID();
    conversationIdRef.current = nextConversationID;
    setConversationId(nextConversationID);
    setMessages([]);
    setDiagnostics(null);
    setError(null);
    setStreaming(false);
    setActiveCitation(null);
  }, [clearTimer]);

  return {
    messages,
    diagnostics,
    streaming,
    conversationId,
    error,
    activeCitation,
    setActiveCitation,
    send,
    stop,
    reset,
  };
}
