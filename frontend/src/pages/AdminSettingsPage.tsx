import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useAuth } from "@/features/auth/AuthContext";
import {
  fetchAdminSettings,
  updateGuestQuota,
  type ApiError,
} from "@/lib/api";

export function AdminSettingsPage() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ["admin-settings"],
    queryFn: ({ signal }) => fetchAdminSettings(signal),
  });
  const [quota, setQuota] = useState(20);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data) {
      setQuota(settings.data.guest_daily_query_quota);
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: updateGuestQuota,
    onSuccess: (value) => {
      setQuota(value);
      setMessage("游客每日配额已更新，下一次请求立即生效。");
      void queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
      void queryClient.invalidateQueries({ queryKey: ["guest-quota"] });
    },
    onError: (error: ApiError) => setMessage(error.message),
  });

  if (!can("users.read")) {
    return <div className="card text-sm text-rose-600">当前角色不能访问运营设置。</div>;
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-600">Workspace Settings</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">运营设置</h1>
          <p className="mt-1 text-sm text-slate-500">游客配额只允许超级管理员修改；受控管理员可查看。</p>
        </div>
        <Link to="/admin" className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">返回监控</Link>
      </header>

      {message ? <p className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{message}</p> : null}

      <section className="card max-w-xl space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">游客每日检索配额</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            按 Asia/Shanghai 自然日重置，只对 viewer 角色生效。0 表示游客当天不能发起检索。
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block">
            <span className="mb-1 block text-xs text-slate-600">每日次数 N</span>
            <input
              type="number"
              min={0}
              max={10000}
              value={quota}
              disabled={!can("quota.manage")}
              onChange={(event) => setQuota(Number(event.target.value))}
              className="w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-400 disabled:bg-slate-100"
            />
          </label>
          <button
            type="button"
            disabled={!can("quota.manage") || save.isPending}
            onClick={() => save.mutate(quota)}
            className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-50"
          >
            {save.isPending ? "保存中…" : "保存配额"}
          </button>
        </div>
        {!can("quota.manage") ? (
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
            受控管理员只能查看，不能修改游客配额。
          </p>
        ) : null}
      </section>

      <section className="card max-w-xl space-y-2">
        <h2 className="text-sm font-semibold text-slate-900">当前数字员工类型</h2>
        <p className="text-xs text-slate-500">
          共 {settings.data?.agent_types.length ?? 0} 个；在「数字员工」页面维护 System Prompt 与工具范围。
        </p>
        <div className="flex flex-wrap gap-2">
          {(settings.data?.agent_types ?? []).map((agent) => (
            <span key={agent.id} className="chip">{agent.name}{agent.enabled ? "" : " · 停用"}</span>
          ))}
        </div>
      </section>
    </div>
  );
}
