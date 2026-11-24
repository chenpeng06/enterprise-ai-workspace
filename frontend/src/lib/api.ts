import type { SSEEvent } from "@/types/contract";
import type {
  BootstrapResponse,
  ChunkPreview,
  MetricsOverview,
  PublicChatRequest,
} from "@/types/public";

import { apiUrl } from "./env";
import { streamSSE } from "./sse";

export interface GatewayHealth {
  status: string;
  service: string;
  version: string;
  time: string;
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { message?: string } };
    return body.error?.message ?? `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
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

export async function fetchBootstrap(signal?: AbortSignal): Promise<BootstrapResponse> {
  const response = await fetch(apiUrl("/api/v1/bootstrap"), {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as BootstrapResponse;
}

export async function fetchChunk(
  chunkId: string,
  signal?: AbortSignal,
): Promise<ChunkPreview> {
  const response = await fetch(apiUrl(`/api/v1/chunks/${chunkId}`), {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as ChunkPreview;
}

export async function fetchMetrics(
  hours = 24,
  signal?: AbortSignal,
): Promise<MetricsOverview> {
  const response = await fetch(apiUrl(`/api/v1/admin/metrics?hours=${hours}`), {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as MetricsOverview;
}

export interface StreamChatHandlers {
  onEvent: (event: SSEEvent) => void;
  onHeartbeat?: () => void;
}

/**
 * 公共对话入口。gateway-go 负责限流、SSE 透传与指标落库，
 * 事件结构与内部契约保持一致。
 */
export async function streamChat(
  request: PublicChatRequest,
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
