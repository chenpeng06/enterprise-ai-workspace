import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useAuth } from "@/features/auth/AuthContext";
import { fetchAdminAgentTypes, saveAgentTypes, type ApiError } from "@/lib/api";
import type { AgentType } from "@/types/auth";

const TOOLS = [
  { id: "search_knowledge_base", label: "知识库检索" },
  { id: "analyze_service_logs", label: "服务日志分析" },
  { id: "query_service_status", label: "服务状态查询" },
] as const;

function blankAgent(): AgentType {
  return {
    id: crypto.randomUUID(),
    name: "新的数字员工",
    description: "面向特定业务场景的知识库助手",
    system_prompt: "你是企业知识库数字员工，必须基于检索证据回答，并保留引用角标。",
    mode: "agent",
    allowed_tools: ["search_knowledge_base"],
    enabled: true,
  };
}

export function AdminAgentsPage() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const agents = useQuery({
    queryKey: ["admin-agent-types"],
    queryFn: ({ signal }) => fetchAdminAgentTypes(signal),
  });
  const [types, setTypes] = useState<AgentType[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (agents.data) {
      setTypes(agents.data);
    }
  }, [agents.data]);

  const save = useMutation({
    mutationFn: saveAgentTypes,
    onSuccess: (data) => {
      setTypes(data);
      setMessage("数字员工类型已保存，下一次对话立即生效。");
      void queryClient.invalidateQueries({ queryKey: ["agent-types"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-agent-types"] });
    },
    onError: (error: ApiError) => setMessage(error.message),
  });

  const update = (index: number, patch: Partial<AgentType>) => {
    setTypes((previous) =>
      previous.map((item, current) => (current === index ? { ...item, ...patch } : item)),
    );
  };

  if (!can("agents.manage")) {
    return <div className="card text-sm text-rose-600">当前角色不能维护数字员工类型。</div>;
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-600">Agent Registry</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">数字员工类型</h1>
          <p className="mt-1 text-sm text-slate-500">
            System Prompt 由受控管理员/超管维护，前端不能直接注入任意 prompt。
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/admin" className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">返回监控</Link>
          <button type="button" onClick={() => setTypes((previous) => [...previous, blankAgent()])} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">新增类型</button>
          <button type="button" onClick={() => save.mutate(types)} disabled={save.isPending} className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-600 disabled:opacity-60">
            {save.isPending ? "保存中…" : "保存全部"}
          </button>
        </div>
      </header>

      {message ? <p className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{message}</p> : null}

      {agents.isPending ? (
        <div className="card text-sm text-slate-500">加载数字员工类型…</div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {types.map((agent, index) => (
            <article key={agent.id} className="card space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <input value={agent.name} onChange={(event) => update(index, { name: event.target.value })} className="w-full border-0 border-b border-slate-200 bg-transparent pb-1 text-sm font-semibold text-slate-900 outline-none focus:border-brand-400" />
                  <p className="mt-1 font-mono text-[10px] text-slate-400">{agent.id.slice(0, 18)}…</p>
                </div>
                <label className="flex shrink-0 items-center gap-1 text-[11px] text-slate-500">
                  <input type="checkbox" checked={agent.enabled} onChange={(event) => update(index, { enabled: event.target.checked })} />
                  启用
                </label>
              </div>
              <input value={agent.description} onChange={(event) => update(index, { description: event.target.value })} placeholder="职责描述" className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs outline-none focus:border-brand-400" />
              <textarea value={agent.system_prompt} onChange={(event) => update(index, { system_prompt: event.target.value })} rows={4} placeholder="System Prompt" className="w-full resize-y rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs leading-5 outline-none focus:border-brand-400" />
              <div className="flex flex-wrap items-center gap-3">
                <label className="text-[11px] text-slate-500">
                  模式{" "}
                  <select value={agent.mode} onChange={(event) => update(index, { mode: event.target.value as "rag" | "agent" })} className="ml-1 rounded border border-slate-300 px-1.5 py-1 text-[11px]">
                    <option value="agent">agent</option>
                    <option value="rag">rag</option>
                  </select>
                </label>
                <div className="flex flex-wrap gap-2">
                  {TOOLS.map((tool) => (
                    <label key={tool.id} className="flex items-center gap-1 text-[11px] text-slate-500">
                      <input
                        type="checkbox"
                        checked={agent.allowed_tools.includes(tool.id)}
                        onChange={(event) => {
                          const next = event.target.checked
                            ? [...agent.allowed_tools, tool.id]
                            : agent.allowed_tools.filter((item) => item !== tool.id);
                          update(index, { allowed_tools: next });
                        }}
                      />
                      {tool.label}
                    </label>
                  ))}
                </div>
                <button type="button" onClick={() => setTypes((previous) => previous.filter((item) => item.id !== agent.id))} className="ml-auto text-[11px] text-rose-600 hover:underline">删除</button>
              </div>
            </article>
          ))}
          {types.length === 0 ? (
            <div className="card text-sm text-slate-500">还没有自定义类型；未选择时使用默认运维数字员工。</div>
          ) : null}
        </div>
      )}
    </div>
  );
}
