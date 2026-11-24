import type { UUID } from "@/types/contract";

export type Role = "owner" | "admin" | "editor" | "viewer";

export interface Identity {
  user_id: UUID;
  workspace_id: UUID;
  email: string;
  display_name: string;
  role: Role;
  role_label: string;
  permissions: string[];
}

export interface UserMember {
  user_id: UUID;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  last_login_at?: string | null;
  joined_at: string;
  invited_by?: string | null;
}

export interface AgentType {
  id: UUID;
  name: string;
  description: string;
  system_prompt: string;
  mode: "rag" | "agent";
  allowed_tools: string[];
  enabled: boolean;
  updated_at?: string;
}

export interface AgentTypeSummary {
  id: UUID;
  name: string;
  description: string;
  mode: "rag" | "agent";
}

export interface DocumentSummary {
  document_id: UUID;
  title: string;
  file_name: string;
  status: string;
  size_bytes: number;
  page_count: number;
  chunk_count: number;
  task_status: string;
  task_stage: string;
  progress: number;
  error_message?: string;
  created_at: string;
}

export interface GuestQuotaStatus {
  applicable: boolean;
  limit: number;
  used: number;
  remaining: number;
  reset_at: string;
}

export interface AdminSettings {
  guest_daily_query_quota: number;
  agent_types: AgentType[];
}
