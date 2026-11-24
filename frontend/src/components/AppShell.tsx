import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "@/features/auth/AuthContext";
import { cn } from "@/lib/cn";
import { CONTRACT_VERSION } from "@/types/contract";

export function AppShell() {
  const { identity, logout, can } = useAuth();
  const navigate = useNavigate();

  const navItems = [
    { to: "/", label: "工作台", end: true },
    ...(identity ? [{ to: "/chat", label: "数字员工", end: false }] : []),
    ...(can("metrics.read") ? [{ to: "/admin", label: "管理后台", end: false }] : []),
  ];

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-4 sm:px-6">
          <NavLink to="/" className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500 font-mono text-sm font-bold text-white">
              AI
            </span>
            <span>
              <span className="block text-sm font-semibold tracking-tight text-slate-900">
                Enterprise AI Workspace
              </span>
              <span className="block text-xs text-slate-500">
                企业级知识库 · 数字员工工作台
              </span>
            </span>
          </NavLink>

          <nav className="ml-auto flex flex-wrap items-center gap-1">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-brand-50 text-brand-700"
                      : "text-slate-600 hover:bg-slate-100",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
            <span className="chip ml-2 hidden sm:inline-flex">
              contract v{CONTRACT_VERSION}
            </span>

            {identity ? (
              <div className="ml-2 flex items-center gap-2 border-l border-slate-200 pl-3">
                <div className="hidden text-right sm:block">
                  <p className="text-xs font-medium text-slate-700">{identity.display_name}</p>
                  <p className="font-mono text-[10px] text-slate-400">{identity.role_label}</p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    void logout().then(() => navigate("/login"));
                  }}
                  className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
                >
                  退出
                </button>
              </div>
            ) : (
              <NavLink
                to="/login"
                className="ml-2 rounded-lg bg-brand-500 px-3 py-2 text-sm font-semibold text-white hover:bg-brand-600"
              >
                登录
              </NavLink>
            )}
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-5 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span>Phase 4 · 角色权限、内容运营与文档摄取</span>
          <span className="font-mono">RBAC · Guest Quota · PDF Ingest · GTE Rerank</span>
        </div>
      </footer>
    </div>
  );
}
