import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { ChatMessageBubble } from "@/features/chat/ChatMessageBubble";
import { DocumentPreview } from "@/features/chat/DocumentPreview";
import { useChatSession } from "@/features/chat/useChatSession";
import { useAuth } from "@/features/auth/AuthContext";
import { RetrievalInspector } from "@/features/retrieval-inspector/RetrievalInspector";
import {
  fetchAgentTypes,
  fetchBootstrap,
  fetchGatewayHealth,
  fetchQuota,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Citation } from "@/types/contract";

type RightTab = "preview" | "inspector";

export function ChatPage() {
  const { identity, can } = useAuth();
  const bootstrap = useQuery({
    queryKey: ["bootstrap"],
    queryFn: ({ signal }) => fetchBootstrap(signal),
  });
  const health = useQuery({
    queryKey: ["gateway-health"],
    queryFn: ({ signal }) => fetchGatewayHealth(signal),
    refetchInterval: 30_000,
  });
  const agentTypes = useQuery({
    queryKey: ["agent-types"],
    queryFn: ({ signal }) => fetchAgentTypes(signal),
  });
  const quota = useQuery({
    queryKey: ["guest-quota"],
    queryFn: ({ signal }) => fetchQuota(signal),
    refetchInterval: 30_000,
    enabled: identity?.role === "viewer",
  });

  const [mode, setMode] = useState<"rag" | "agent">("agent");
  const [agentTypeId, setAgentTypeId] = useState("");
  const [rightTab, setRightTab] = useState<RightTab>("preview");
  const [input, setInput] = useState("");
  const kbIds = useMemo(
    () => (bootstrap.data ? [bootstrap.data.kb_id] : []),
    [bootstrap.data],
  );
  const session = useChatSession({ kbIds, mode, agentTypeId: agentTypeId || undefined });
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!agentTypeId && agentTypes.data && agentTypes.data.length > 0) {
      setAgentTypeId(agentTypes.data[0].id);
    }
  }, [agentTypeId, agentTypes.data]);

  const selectedAgent = agentTypes.data?.find((item) => item.id === agentTypeId);

  useEffect(() => {
    if (selectedAgent) {
      setMode(selectedAgent.mode);
    }
  }, [selectedAgent]);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [session.messages]);

  const handleCitation = (citation: Citation, messageID: string) => {
    session.setActiveCitation({ citation, messageId: messageID });
    setRightTab("preview");
  };

  const submit = () => {
    const query = input.trim();
    if (!query) {
      return;
    }
    setInput("");
    void session.send(query);
  };

  const disabled = !bootstrap.data || session.streaming;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-600">
            Ops Assistant Workspace
          </p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">
            企业知识库 · 数字员工
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            LangGraph 规划、混合检索、角标溯源与实时检索透视。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
              health.data?.status === "ok"
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-amber-200 bg-amber-50 text-amber-700",
            )}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            gateway {health.data?.status ?? "checking"}
          </span>
          {agentTypes.data && agentTypes.data.length > 0 ? (
            <select
              value={agentTypeId}
              onChange={(event) => setAgentTypeId(event.target.value)}
              className="max-w-[190px] rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-700 outline-none focus:border-brand-400"
              title="选择数字员工类型"
            >
              {agentTypes.data.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          ) : null}
          <div className="flex rounded-lg border border-slate-200 bg-white p-0.5">
            {(["agent", "rag"] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  mode === value
                    ? "bg-slate-900 text-white"
                    : "text-slate-500 hover:text-slate-900",
                )}
              >
                {value === "agent" ? "数字员工" : "RAG"}
              </button>
            ))}
          </div>
          {identity?.role === "viewer" && quota.data?.applicable ? (
            <span
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs",
                quota.data.remaining > 0
                  ? "border-amber-200 bg-amber-50 text-amber-700"
                  : "border-rose-200 bg-rose-50 text-rose-700",
              )}
              title={`每日 ${quota.data.limit} 次，明日 00:05 重置`}
            >
              今日配额 {quota.data.remaining}/{quota.data.limit}
            </span>
          ) : null}
          <button
            type="button"
            onClick={session.reset}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            新会话
          </button>
          {can("metrics.read") ? (
            <Link
              to="/admin"
              className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-600"
            >
              管理后台
            </Link>
          ) : null}
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_390px]">
        <section className="flex min-h-[calc(100vh-230px)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <span className="font-mono text-[10px] text-slate-400">
                conv {session.conversationId.slice(0, 8)}
              </span>
              <span className="h-1 w-1 rounded-full bg-slate-300" />
              <span>{session.streaming ? "SSE 流式接收中" : "空闲"}</span>
            </div>
            <p className="text-[11px] text-slate-400">点击回答中的 [n] 联动右侧原文定位</p>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-5 overflow-y-auto px-4 py-5">
            {session.messages.length === 0 ? (
              <div className="flex h-full min-h-[360px] flex-col items-center justify-center px-6 text-center">
                <span className="grid h-12 w-12 place-items-center rounded-2xl bg-slate-900 font-mono text-xs font-bold text-white">
                  OPS
                </span>
                <h2 className="mt-4 text-base font-semibold text-slate-900">
                  从一个运维问题开始
                </h2>
                <p className="mt-1 max-w-sm text-xs leading-6 text-slate-500">
                  数字员工会先拆解任务，再检索规范、分析日志，最后给出带角标的可执行报告。
                </p>
                <div className="mt-5 grid w-full max-w-lg gap-2">
                  {(bootstrap.data?.suggestions ?? [
                    "灰度发布错误率过高应该怎么处理？",
                    "自动回滚的判定条件是什么？",
                  ]).map((suggestion) => (
                    <button
                      key={suggestion}
                      type="button"
                      disabled={disabled}
                      onClick={() => {
                        setInput("");
                        void session.send(suggestion);
                      }}
                      className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs text-slate-600 transition-colors hover:border-brand-300 hover:bg-brand-50 hover:text-brand-800 disabled:opacity-50"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
                {!bootstrap.data && !bootstrap.isPending ? (
                  <p className="mt-4 text-xs text-rose-600">
                    演示知识库初始化失败：{bootstrap.error instanceof Error ? bootstrap.error.message : "未知错误"}
                  </p>
                ) : null}
              </div>
            ) : (
              session.messages.map((message) => (
                <ChatMessageBubble
                  key={message.id}
                  message={message}
                  activeCitation={session.activeCitation}
                  onCitationClick={handleCitation}
                />
              ))
            )}
          </div>

          {session.error ? (
            <div className="mx-4 mb-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {session.error}
            </div>
          ) : null}

          <div className="border-t border-slate-100 bg-slate-50/60 p-3">
            <div className="rounded-xl border border-slate-200 bg-white p-2 shadow-sm focus-within:border-brand-400">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit();
                  }
                }}
                rows={2}
                placeholder={
                  bootstrap.data
                    ? "输入问题，Enter 发送，Shift + Enter 换行"
                    : "正在连接知识库…"
                }
                disabled={!bootstrap.data}
                className="max-h-36 min-h-[48px] w-full resize-none border-0 bg-transparent px-2 py-1 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400 disabled:bg-transparent"
              />
              <div className="flex items-center justify-between px-1">
                <span className="font-mono text-[10px] text-slate-400">
                  {mode === "agent" ? "Planner → Retrieve → Tools → Reviewer → Writer" : "Retrieve → Reviewer → Writer"}
                </span>
                <div className="flex items-center gap-2">
                  {session.streaming ? (
                    <button
                      type="button"
                      onClick={session.stop}
                      className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
                    >
                      停止
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={submit}
                    disabled={disabled || !input.trim()}
                    className="rounded-lg bg-brand-500 px-4 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:bg-slate-300"
                  >
                    {session.streaming ? "生成中…" : "发送"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <aside className="space-y-3">
          <div className="flex rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
            {(
              [
                { key: "preview", label: "原文预览" },
                { key: "inspector", label: "检索透视" },
              ] as const
            ).map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setRightTab(tab.key)}
                className={cn(
                  "flex-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors",
                  rightTab === tab.key
                    ? "bg-slate-900 text-white"
                    : "text-slate-500 hover:bg-slate-50",
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {rightTab === "preview" ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-3 shadow-card">
              <DocumentPreview citation={session.activeCitation?.citation ?? null} />
            </div>
          ) : (
            <RetrievalInspector diagnostics={session.diagnostics} />
          )}

          <div className="rounded-xl border border-slate-200 bg-white p-3 text-[11px] leading-5 text-slate-500 shadow-sm">
            <p className="font-medium text-slate-700">本次会话可观测性</p>
            <p className="mt-1">
              网关会旁路解析 SSE，记录 TTFT、Token、限流与知识库命中率；数据在
              <Link to="/admin" className="mx-1 text-brand-600 hover:underline">
                管理看板
              </Link>
              聚合展示。
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
