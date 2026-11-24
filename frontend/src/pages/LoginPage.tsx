import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/features/auth/AuthContext";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

const DEMO_ACCOUNTS = [
  { email: "admin@demo.local", password: "Admin@12345", label: "超级管理员" },
  { email: "ops@demo.local", password: "Ops@12345", label: "受控管理员" },
  { email: "guest@demo.local", password: "Guest@12345", label: "游客" },
] as const;

export function LoginPage() {
  const { identity, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (identity) {
    return <Navigate to="/chat" replace />;
  }

  const from = (location.state as { from?: string } | null)?.from ?? "/chat";

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError("请输入邮箱和密码");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.status === 401 ? "邮箱或密码错误" : caught.message);
      } else {
        setError(caught instanceof Error ? caught.message : "登录失败");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-[1.05fr_0.95fr]">
      <section className="rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-white to-brand-50 p-8 shadow-card sm:p-10">
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-600">
          Enterprise Access
        </span>
        <h1 className="mt-3 text-3xl font-bold tracking-tight text-slate-900">
          登录企业知识库
        </h1>
        <p className="mt-3 text-sm leading-7 text-slate-600">
          超级管理员维护数字员工与知识库，受控管理员负责日常运营授权，游客按每日配额只读使用。
        </p>
        <div className="mt-7 grid gap-2">
          {DEMO_ACCOUNTS.map((account) => (
            <button
              key={account.email}
              type="button"
              onClick={() => {
                setEmail(account.email);
                setPassword(account.password);
                setError(null);
              }}
              className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left transition-colors hover:border-brand-300 hover:bg-brand-50"
            >
              <span>
                <span className="block text-xs font-semibold text-slate-700">{account.label}</span>
                <span className="font-mono text-[10px] text-slate-400">{account.email}</span>
              </span>
              <span className="font-mono text-[10px] text-brand-500">填入 →</span>
            </button>
          ))}
        </div>
        <p className="mt-4 text-[11px] leading-5 text-slate-400">
          本地演示账号；生产环境关闭种子账号，改用企业身份源。密码不通过前端持久化。
        </p>
      </section>

      <section className="card self-center">
        <h2 className="text-lg font-semibold text-slate-900">账号登录</h2>
        <p className="mt-1 text-xs text-slate-500">使用邮箱与密码建立 HttpOnly 会话。</p>
        <form className="mt-5 space-y-4" onSubmit={submit}>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-600">邮箱</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm text-slate-800 outline-none transition-colors focus:border-brand-400"
              placeholder="you@company.com"
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-600">密码</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              className="w-full rounded-xl border border-slate-300 px-3 py-2.5 text-sm text-slate-800 outline-none transition-colors focus:border-brand-400"
              placeholder="••••••••"
            />
          </label>
          {error ? (
            <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {error}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={submitting}
            className={cn(
              "w-full rounded-xl bg-brand-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-600",
              submitting && "cursor-wait opacity-70",
            )}
          >
            {submitting ? "登录中…" : "登录"}
          </button>
        </form>
        <div className="mt-5 rounded-xl bg-slate-50 p-3 text-[11px] leading-5 text-slate-500">
          <p className="font-medium text-slate-600">角色说明</p>
          <p className="mt-1">超级管理员：全部权限；受控管理员：用户/文档/数字员工运营；游客：只读 + 每日检索配额。</p>
        </div>
      </section>
    </div>
  );
}
