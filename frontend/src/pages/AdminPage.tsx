import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { fetchMetrics } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { TrendPoint } from "@/types/public";

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(Math.round(value));
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatBucket(bucket: string): string {
  const date = new Date(bucket);
  if (Number.isNaN(date.getTime())) {
    return bucket;
  }
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function MetricCard({
  label,
  value,
  suffix,
  hint,
  tone = "slate",
}: {
  label: string;
  value: string;
  suffix?: string;
  hint: string;
  tone?: "slate" | "brand" | "rose" | "emerald";
}) {
  const tones = {
    slate: "bg-slate-900",
    brand: "bg-brand-500",
    rose: "bg-rose-500",
    emerald: "bg-emerald-500",
  } as const;
  return (
    <article className="card space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-slate-500">{label}</p>
        <span className={cn("h-2 w-2 rounded-full", tones[tone])} />
      </div>
      <p className="font-mono text-2xl font-semibold tracking-tight text-slate-900">
        {value}
        {suffix ? <span className="ml-1 text-sm font-normal text-slate-400">{suffix}</span> : null}
      </p>
      <p className="text-[11px] leading-5 text-slate-500">{hint}</p>
    </article>
  );
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-40 items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-xs text-slate-400">
      {label}
    </div>
  );
}

function TTFTChart({ points }: { points: TrendPoint[] }) {
  if (points.length === 0) {
    return <EmptyChart label="暂无 TTFT 数据，完成一次对话后出现趋势" />;
  }
  const width = 640;
  const height = 170;
  const padding = 24;
  const maxValue = Math.max(1, ...points.map((point) => point.avg_ttft_ms ?? 0));
  const stepX = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0;
  const coordinates = points.map((point, index) => {
    const x = padding + index * stepX;
    const y = height - padding - ((point.avg_ttft_ms ?? 0) / maxValue) * (height - padding * 2);
    return { x, y, point };
  });
  const line = coordinates.map(({ x, y }) => `${x},${y}`).join(" ");

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full overflow-visible" role="img" aria-label="平均 TTFT 趋势">
        {[0, 0.5, 1].map((ratio) => {
          const y = height - padding - ratio * (height - padding * 2);
          return (
            <g key={ratio}>
              <line x1={padding} x2={width - padding} y1={y} y2={y} stroke="#e2e8f0" strokeDasharray="4 4" />
              <text x={4} y={y + 3} fill="#94a3b8" fontSize="9" fontFamily="monospace">
                {Math.round(maxValue * ratio)}
              </text>
            </g>
          );
        })}
        <polyline points={line} fill="none" stroke="#3b6cf6" strokeWidth="2.5" strokeLinejoin="round" />
        {coordinates.map(({ x, y, point }) => (
          <g key={point.bucket}>
            <circle cx={x} cy={y} r="5" fill="#3b6cf6" stroke="white" strokeWidth="2.5" />
            <title>
              {formatBucket(point.bucket)} · {Math.round(point.avg_ttft_ms ?? 0)}ms · {point.count} 次
            </title>
          </g>
        ))}
        {coordinates.map(({ x, point }, index) =>
          index === 0 || index === coordinates.length - 1 || coordinates.length <= 6 ? (
            <text key={`label-${point.bucket}`} x={x} y={height - 4} fill="#94a3b8" fontSize="9" textAnchor="middle" fontFamily="monospace">
              {formatBucket(point.bucket)}
            </text>
          ) : null,
        )}
      </svg>
    </div>
  );
}

function RateLimitChart({ points }: { points: TrendPoint[] }) {
  if (points.length === 0) {
    return <EmptyChart label="暂无拦截记录" />;
  }
  const maxValue = Math.max(1, ...points.map((point) => point.count));
  return (
    <div className="flex h-40 items-end justify-center gap-3 overflow-x-auto">
      {points.map((point) => (
        <div
          key={point.bucket}
          className="flex w-16 shrink-0 flex-col items-center gap-1"
          title={`${formatBucket(point.bucket)} · ${point.count} 次`}
        >
          <span className="font-mono text-[9px] text-slate-500">{point.count}</span>
          <div className="flex h-28 w-10 items-end overflow-hidden rounded-t bg-slate-100">
            <div
              className="w-full rounded-t bg-rose-400"
              style={{ height: `${Math.max(8, (point.count / maxValue) * 100)}%` }}
            />
          </div>
          <span className="font-mono text-[9px] text-slate-400">{formatBucket(point.bucket)}</span>
        </div>
      ))}
    </div>
  );
}

export function AdminPage() {
  const metrics = useQuery({
    queryKey: ["admin-metrics", 24],
    queryFn: ({ signal }) => fetchMetrics(24, signal),
    refetchInterval: 15_000,
  });

  if (metrics.isPending) {
    return <div className="card text-sm text-slate-500">正在加载监控指标…</div>;
  }

  if (metrics.error || !metrics.data) {
    return (
      <div className="card border-rose-200 bg-rose-50 text-sm text-rose-700">
        监控指标加载失败：{metrics.error instanceof Error ? metrics.error.message : "未知错误"}
      </div>
    );
  }

  const { totals, knowledge_base: kb, ttft_trend: ttftTrend, rate_limit_trend: rateLimitTrend, recent_rate_limits: recent } = metrics.data;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-600">Admin Observatory</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">网关与知识库监控</h1>
          <p className="mt-1 text-sm text-slate-500">
            最近 24 小时 · 每 15 秒刷新 · 数据来自 request_logs / rate_limit_events / retrieval_traces。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/admin/users" className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">用户权限</Link>
          <Link to="/admin/agents" className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">数字员工</Link>
          <Link to="/admin/documents" className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">文档摄取</Link>
          <Link to="/admin/settings" className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">运营设置</Link>
          <button
            type="button"
            onClick={() => void metrics.refetch()}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            {metrics.isFetching ? "刷新中…" : "立即刷新"}
          </button>
          <Link
            to="/chat"
            className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-600"
          >
            返回对话
          </Link>
        </div>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="对话请求"
          value={formatNumber(totals.chat_requests)}
          suffix="次"
          hint={`总请求 ${formatNumber(totals.requests)} 次，Token ${formatNumber(totals.total_tokens)}`}
          tone="brand"
        />
        <MetricCard
          label="限流拦截"
          value={formatNumber(totals.rate_limited)}
          suffix="次"
          hint="Redis 分布式令牌桶拒绝的请求数"
          tone="rose"
        />
        <MetricCard
          label="平均 TTFT"
          value={formatNumber(totals.avg_ttft_ms)}
          suffix="ms"
          hint={`P95 ${formatNumber(totals.p95_ttft_ms)}ms · 网关旁路采集`}
          tone="emerald"
        />
        <MetricCard
          label="知识库命中率"
          value={formatPercent(kb.hit_rate)}
          hint={`${kb.hits} 次有证据 / ${kb.queries} 次检索`}
          tone="slate"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <section className="card space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">平均 TTFT 延迟趋势</h2>
            <p className="mt-1 text-xs text-slate-500">按小时聚合；TTFT 为网关发起上游请求到首个 generating 事件的耗时。</p>
          </div>
          <TTFTChart points={ttftTrend} />
        </section>

        <section className="card space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">限流拦截分布</h2>
            <p className="mt-1 text-xs text-slate-500">按小时聚合 Redis 令牌桶拒绝次数。</p>
          </div>
          <RateLimitChart points={rateLimitTrend} />
        </section>
      </div>

      <section className="card space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">最近限流事件</h2>
            <p className="mt-1 text-xs text-slate-500">仅展示最近 10 条，用于快速定位异常调用方。</p>
          </div>
          <span className="chip">{recent.length} events</span>
        </div>
        {recent.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-xs text-slate-400">
            当前窗口内没有触发限流。可以并发发起对话验证令牌桶。
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] text-left text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-[10px] uppercase tracking-wider text-slate-400">
                  <th className="pb-2 pr-3 font-medium">时间</th>
                  <th className="pb-2 pr-3 font-medium">路由</th>
                  <th className="pb-2 pr-3 font-medium">配额</th>
                  <th className="pb-2 pr-3 font-medium">观测值</th>
                  <th className="pb-2 pr-3 font-medium">Retry</th>
                  <th className="pb-2 font-medium">来源 IP</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((record, index) => (
                  <tr key={`${record.created_at}-${index}`} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 pr-3 font-mono text-[10px] text-slate-500">
                      {new Date(record.created_at).toLocaleString("zh-CN")}
                    </td>
                    <td className="py-2 pr-3 font-mono text-[10px] text-slate-600">{record.route}</td>
                    <td className="py-2 pr-3 font-mono text-[10px]">{record.limit_value}</td>
                    <td className="py-2 pr-3 font-mono text-[10px] text-rose-600">{record.observed}</td>
                    <td className="py-2 pr-3 font-mono text-[10px]">{record.retry_after_ms}ms</td>
                    <td className="py-2 font-mono text-[10px] text-slate-500">{record.client_ip ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
