import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useAuth } from "@/features/auth/AuthContext";
import {
  createUser,
  fetchMembers,
  removeMember,
  resetMemberPassword,
  updateMemberRole,
  type ApiError,
} from "@/lib/api";
import type { Role } from "@/types/auth";

const ROLE_LABEL: Record<Role, string> = {
  owner: "超级管理员",
  admin: "受控管理员",
  editor: "运营人员",
  viewer: "游客",
};

export function AdminUsersPage() {
  const { identity } = useAuth();
  const queryClient = useQueryClient();
  const members = useQuery({
    queryKey: ["admin-users"],
    queryFn: ({ signal }) => fetchMembers(signal),
  });
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("viewer");
  const [message, setMessage] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      setEmail("");
      setDisplayName("");
      setPassword("");
      setMessage("用户已创建并加入当前 workspace。");
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: ApiError) => setMessage(error.message),
  });

  const changeRole = useMutation({
    mutationFn: ({ userId, nextRole }: { userId: string; nextRole: string }) =>
      updateMemberRole(userId, nextRole),
    onSuccess: () => {
      setMessage("角色已更新，下一次请求立即生效。");
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: ApiError) => setMessage(error.message),
  });

  const remove = useMutation({
    mutationFn: removeMember,
    onSuccess: () => {
      setMessage("成员已移出 workspace。");
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (error: ApiError) => setMessage(error.message),
  });

  const resetPassword = useMutation({
    mutationFn: ({ userId, nextPassword }: { userId: string; nextPassword: string }) =>
      resetMemberPassword(userId, nextPassword),
    onSuccess: () => setMessage("密码已重置。"),
    onError: (error: ApiError) => setMessage(error.message),
  });

  if (!identity) {
    return null;
  }

  const availableRoles: Role[] =
    identity.role === "owner" ? ["admin", "editor", "viewer"] : ["editor", "viewer"];

  const canManage = (targetRole: Role, targetID: string): boolean => {
    if (targetID === identity.user_id || targetRole === "owner") {
      return false;
    }
    if (identity.role === "owner") {
      return true;
    }
    return identity.role === "admin" && (targetRole === "editor" || targetRole === "viewer");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    create.mutate({ email, display_name: displayName, password, role });
  };

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-600">Access Control</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">用户与角色</h1>
          <p className="mt-1 text-sm text-slate-500">
            受控管理员可以管理游客/运营人员；只有超级管理员可以任命管理员或修改游客配额。
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/admin" className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">
            返回监控
          </Link>
          <Link to="/chat" className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-600">
            返回对话
          </Link>
        </div>
      </header>

      {message ? (
        <p className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">{message}</p>
      ) : null}

      <section className="card space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">创建 / 授权成员</h2>
          <p className="mt-1 text-xs text-slate-500">
            直接设置初始密码；受控管理员无法创建管理员或超级管理员。
          </p>
        </div>
        <form className="grid gap-3 md:grid-cols-2" onSubmit={submit}>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-600">邮箱</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-400" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-600">显示名</span>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-400" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-600">初始密码（≥8 位）</span>
            <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" required minLength={8} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-400" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-600">角色</span>
            <select value={role} onChange={(event) => setRole(event.target.value as Role)} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-400">
              {availableRoles.map((item) => (
                <option key={item} value={item}>{ROLE_LABEL[item]}</option>
              ))}
            </select>
          </label>
          <div className="md:col-span-2">
            <button type="submit" disabled={create.isPending} className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-60">
              {create.isPending ? "创建中…" : "创建成员"}
            </button>
          </div>
        </form>
      </section>

      <section className="card overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">当前 workspace 成员</h2>
          <span className="chip">{members.data?.length ?? 0} members</span>
        </div>
        {members.isPending ? (
          <p className="p-4 text-sm text-slate-500">加载成员…</p>
        ) : members.error ? (
          <p className="p-4 text-sm text-rose-600">成员加载失败。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-xs">
              <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-4 py-2 font-medium">成员</th>
                  <th className="px-4 py-2 font-medium">角色</th>
                  <th className="px-4 py-2 font-medium">最近登录</th>
                  <th className="px-4 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {(members.data ?? []).map((member) => {
                  const editable = canManage(member.role, member.user_id);
                  return (
                    <tr key={member.user_id} className="border-t border-slate-100">
                      <td className="px-4 py-2.5">
                        <p className="font-medium text-slate-700">{member.display_name}</p>
                        <p className="font-mono text-[10px] text-slate-400">{member.email}</p>
                      </td>
                      <td className="px-4 py-2.5">
                        {editable ? (
                          <select
                            value={member.role}
                            onChange={(event) =>
                              changeRole.mutate({ userId: member.user_id, nextRole: event.target.value })
                            }
                            className="rounded-lg border border-slate-300 px-2 py-1 text-xs"
                          >
                            {availableRoles.map((item) => (
                              <option key={item} value={item}>{ROLE_LABEL[item]}</option>
                            ))}
                          </select>
                        ) : (
                          <span className="rounded-full bg-slate-100 px-2 py-1 text-[10px] text-slate-600">
                            {ROLE_LABEL[member.role]}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-[10px] text-slate-400">
                        {member.last_login_at ? new Date(member.last_login_at).toLocaleString("zh-CN") : "—"}
                      </td>
                      <td className="px-4 py-2.5">
                        {editable ? (
                          <div className="flex gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                const next = window.prompt(`为 ${member.email} 设置新密码（≥8 位）`);
                                if (next) {
                                  resetPassword.mutate({ userId: member.user_id, nextPassword: next });
                                }
                              }}
                              className="text-brand-600 hover:underline"
                            >
                              重置密码
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                if (window.confirm(`确认将 ${member.email} 移出 workspace？`)) {
                                  remove.mutate(member.user_id);
                                }
                              }}
                              className="text-rose-600 hover:underline"
                            >
                              移除
                            </button>
                          </div>
                        ) : (
                          <span className="text-slate-300">受保护</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
