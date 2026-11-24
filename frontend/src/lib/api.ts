import type { ChatStreamRequest, SSEEvent } from "@/types/contract";

import { apiUrl } from "./env";
import { streamSSE } from "./sse";

export interface GatewayHealth {
  status: string;
  service: string;
  version: string;
  time: string;
}

export async function fetchGatewayHealth(signal?: AbortSignal): Promise<GatewayHealth> {
  const response = await fetch(apiUrl("/healthz"), {
    signal,
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error(`网关健康检查失败：HTTP ${response.status}`);
  }

  return (await response.json()) as GatewayHealth;
}

export interface StreamChatHandlers {
  onEvent: (event: SSEEvent) => void;
  onHeartbeat?: () => void;
}

/**
 * 对话流入口。Phase 3 由 gateway-go 实现 /api/v1/chat/stream 并原样透传
 * ai-engine-py 的 SSE 事件；前端只依赖 docs/ARCHITECTURE.md 中的事件契约。
 */
export async function streamChat(
  request: ChatStreamRequest,
  handlers: StreamChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  await streamSSE({
    url: apiUrl("/api/v1/chat/stream"),
    signal,
    init: {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    onEvent: (event) => {
      handlers.onEvent(event as unknown as SSEEvent);
    },
    onHeartbeat: handlers.onHeartbeat,
  });
}
