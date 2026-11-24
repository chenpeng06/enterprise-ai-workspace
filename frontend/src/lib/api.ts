import type { SSEEvent } from "@/types/contract";
import type {
  AdminSettings,
  AgentType,
  AgentTypeSummary,
  DocumentSummary,
  GuestQuotaStatus,
  Identity,
  UserMember,
} from "@/types/auth";
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

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { error?: { message?: string } };
    return body.error?.message ?? `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

async function requestJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  if (init?.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    let code: string | undefined;
    try {
      const body = (await response.json()) as { error?: { code?: string } };
      code = body.error?.code;
    } catch {
      code = undefined;
    }
    throw new ApiError(response.status, await readError(response), code);
  }
  return (await response.json()) as T;
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

export async function login(email: string, password: string): Promise<Identity> {
  const result = await requestJSON<{ identity: Identity }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return result.identity;
}

export async function logout(): Promise<void> {
  await requestJSON<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" });
}

export async function fetchMe(signal?: AbortSignal): Promise<Identity> {
  const result = await requestJSON<{ identity: Identity }>("/api/v1/auth/me", { signal });
  return result.identity;
}

export async function fetchQuota(signal?: AbortSignal): Promise<GuestQuotaStatus> {
  return requestJSON<GuestQuotaStatus>("/api/v1/auth/quota", { signal });
}

export async function fetchBootstrap(signal?: AbortSignal): Promise<BootstrapResponse> {
  return requestJSON<BootstrapResponse>("/api/v1/bootstrap", { signal });
}

export async function fetchChunk(
  chunkId: string,
  signal?: AbortSignal,
): Promise<ChunkPreview> {
  return requestJSON<ChunkPreview>(`/api/v1/chunks/${chunkId}`, { signal });
}

export async function fetchMetrics(
  hours = 24,
  signal?: AbortSignal,
): Promise<MetricsOverview> {
  return requestJSON<MetricsOverview>(`/api/v1/admin/metrics?hours=${hours}`, { signal });
}

export async function fetchAgentTypes(signal?: AbortSignal): Promise<AgentTypeSummary[]> {
  const result = await requestJSON<{ agent_types: AgentTypeSummary[] }>("/api/v1/agent-types", {
    signal,
  });
  return result.agent_types;
}

export async function fetchMembers(signal?: AbortSignal): Promise<UserMember[]> {
  const result = await requestJSON<{ members: UserMember[] }>("/api/v1/admin/users", { signal });
  return result.members;
}

export async function createUser(payload: {
  email: string;
  display_name: string;
  password: string;
  role: string;
}): Promise<UserMember> {
  const result = await requestJSON<{ member: UserMember }>("/api/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return result.member;
}

export async function updateMemberRole(userId: string, role: string): Promise<UserMember> {
  const result = await requestJSON<{ member: UserMember }>(
    `/api/v1/admin/users/${userId}/role`,
    { method: "PATCH", body: JSON.stringify({ role }) },
  );
  return result.member;
}

export async function removeMember(userId: string): Promise<void> {
  await requestJSON<{ ok: boolean }>(`/api/v1/admin/users/${userId}`, { method: "DELETE" });
}

export async function resetMemberPassword(userId: string, password: string): Promise<void> {
  await requestJSON<{ ok: boolean }>(`/api/v1/admin/users/${userId}/reset-password`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export async function fetchAdminSettings(signal?: AbortSignal): Promise<AdminSettings> {
  return requestJSON<AdminSettings>("/api/v1/admin/settings", { signal });
}

export async function updateGuestQuota(quota: number): Promise<number> {
  const result = await requestJSON<{ guest_daily_query_quota: number }>(
    "/api/v1/admin/settings/guest-quota",
    { method: "PUT", body: JSON.stringify({ quota }) },
  );
  return result.guest_daily_query_quota;
}

export async function fetchAdminAgentTypes(signal?: AbortSignal): Promise<AgentType[]> {
  const result = await requestJSON<{ agent_types: AgentType[] }>("/api/v1/admin/agent-types", {
    signal,
  });
  return result.agent_types;
}

export async function saveAgentTypes(agentTypes: AgentType[]): Promise<AgentType[]> {
  const result = await requestJSON<{ agent_types: AgentType[] }>("/api/v1/admin/agent-types", {
    method: "PUT",
    body: JSON.stringify({ agent_types: agentTypes }),
  });
  return result.agent_types;
}

export async function fetchDocuments(signal?: AbortSignal): Promise<DocumentSummary[]> {
  const result = await requestJSON<{ documents: DocumentSummary[] }>("/api/v1/documents", {
    signal,
  });
  return result.documents;
}

export async function uploadDocument(input: {
  file: File;
  title?: string;
  knowledgeBaseId?: string;
}): Promise<{ task_id: string; document_id: string; status: string }> {
  const form = new FormData();
  form.append("file", input.file);
  if (input.title) {
    form.append("title", input.title);
  }
  if (input.knowledgeBaseId) {
    form.append("knowledge_base_id", input.knowledgeBaseId);
  }
  return requestJSON<{ task_id: string; document_id: string; status: string }>(
    "/api/v1/documents",
    { method: "POST", body: form },
  );
}

export interface StreamChatHandlers {
  onEvent: (event: SSEEvent) => void;
  onHeartbeat?: () => void;
}

/**
 * 公共对话入口。gateway-go 负责限流、游客配额、SSE 透传与指标落库。
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
      credentials: "include",
    },
    onEvent: (event) => {
      handlers.onEvent(event as unknown as SSEEvent);
    },
    onHeartbeat: handlers.onHeartbeat,
  });
}
