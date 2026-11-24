import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <section className="card mx-auto max-w-xl space-y-4 text-center">
      <p className="font-mono text-sm text-slate-400">404</p>
      <h1 className="text-xl font-semibold text-slate-900">页面尚未交付</h1>
      <p className="text-sm leading-6 text-slate-600">
        该路由会在后续阶段实现。Phase 3 将提供对话工作台、检索透视抽屉与管理后台看板。
      </p>
      <Link
        to="/"
        className="inline-flex rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-600"
      >
        返回工作台
      </Link>
    </section>
  );
}
