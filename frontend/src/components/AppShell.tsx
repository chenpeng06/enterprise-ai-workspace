import { NavLink, Outlet } from "react-router-dom";

import { cn } from "@/lib/cn";
import { CONTRACT_VERSION } from "@/types/contract";

const NAV_ITEMS = [
  { to: "/", label: "工作台", end: true },
  { to: "/chat", label: "数字员工", end: false },
  { to: "/admin", label: "监控看板", end: false },
] as const;

export function AppShell() {
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

          <nav className="ml-auto flex items-center gap-1">
            {NAV_ITEMS.map((item) => (
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
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-5 text-xs text-slate-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span>Phase 3 · 对话、原文溯源与监控看板</span>
          <span className="font-mono">Redis Token Bucket · SSE Proxy · TTFT · pgvector</span>
        </div>
      </footer>
    </div>
  );
}
