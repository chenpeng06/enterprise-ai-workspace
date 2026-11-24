/**
 * 极简、无依赖的 SSE 客户端。
 *
 * 关键点：
 * - 用 fetch + ReadableStream 读取，支持 POST 请求（原生 EventSource 仅支持 GET）；
 * - 正确处理跨 chunk 截断的 UTF-8 与 SSE 帧边界；
 * - 忽略心跳注释帧（": ping"），保留 id 以支持断线续传。
 */

export interface RawSSEEvent {
  event: string;
  id?: number;
  data: unknown;
}

export class SSEHttpError extends Error {
  readonly status: number;
  readonly bodySnippet: string;

  constructor(status: number, bodySnippet: string) {
    super(`SSE 建流失败：HTTP ${status}`);
    this.name = "SSEHttpError";
    this.status = status;
    this.bodySnippet = bodySnippet;
  }
}

export class SSEProtocolError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "SSEProtocolError";
  }
}

export interface StreamSSEOptions {
  url: string;
  init?: RequestInit;
  signal?: AbortSignal;
  onEvent: (event: RawSSEEvent) => void;
  onHeartbeat?: () => void;
}

export async function streamSSE(options: StreamSSEOptions): Promise<void> {
  const { url, init, signal, onEvent, onHeartbeat } = options;

  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "text/event-stream");
  }

  const response = await fetch(url, { ...init, headers, signal });

  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new SSEHttpError(response.status, body.slice(0, 500));
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("text/event-stream")) {
    throw new SSEProtocolError(`预期的 Content-Type 为 text/event-stream，实际为 "${contentType}"`);
  }
  if (!response.body) {
    throw new SSEProtocolError("当前运行环境不支持 ReadableStream 响应体");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const dispatch = (frame: string): void => {
    const event = parseFrame(frame);
    if (event === null) {
      onHeartbeat?.();
      return;
    }
    onEvent(event);
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (frame.trim().length > 0) {
          dispatch(frame);
        }
        boundary = buffer.indexOf("\n\n");
      }
    }

    buffer += decoder.decode();
    buffer = buffer.replace(/\r\n/g, "\n");
    if (buffer.trim().length > 0) {
      dispatch(buffer);
    }
  } finally {
    reader.releaseLock();
  }
}

export function parseFrame(frame: string): RawSSEEvent | null {
  let eventName = "message";
  let id: number | undefined;
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.length === 0 || line.startsWith(":")) {
      continue;
    }

    const colonIndex = line.indexOf(":");
    const field = colonIndex === -1 ? line : line.slice(0, colonIndex);
    let value = colonIndex === -1 ? "" : line.slice(colonIndex + 1);
    if (value.startsWith(" ")) {
      value = value.slice(1);
    }

    switch (field) {
      case "event":
        if (value.length > 0) {
          eventName = value;
        }
        break;
      case "data":
        dataLines.push(value);
        break;
      case "id": {
        const parsed = Number(value);
        if (Number.isSafeInteger(parsed) && parsed >= 0) {
          id = parsed;
        }
        break;
      }
      default:
        break;
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  let data: unknown;
  try {
    data = JSON.parse(dataLines.join("\n")) as unknown;
  } catch (error) {
    throw new SSEProtocolError(`无法解析 ${eventName} 事件的 JSON 数据`, { cause: error });
  }

  return id === undefined ? { event: eventName, data } : { event: eventName, id, data };
}
