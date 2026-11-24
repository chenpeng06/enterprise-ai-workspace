import { useQuery } from "@tanstack/react-query";

import { fetchGatewayHealth } from "@/lib/api";
import { cn } from "@/lib/cn";

export function StatusPanel() {
  const { data, error, isPending, isFetching, refetch } = useQuery({
    queryKey: ["gateway-health"],
    queryFn: ({ signal }) => fetchGatewayHealth(signal),
  });

  const online = data?.status === "ok";

  return (
    <section className="card flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "mt-1 h-3 w-3 shrink-0 rounded-full",
            isPending ? "animate-pulse bg-amber-400" : online ? "bg-emerald-500" : "bg-rose-500",
          )}
          aria-hidden="true"
        />
        <div>
          <h2 className="text-sm font-semibold text-slate-900">网关运行状态</h2>
          <p className="mt-1 text-sm text-slate-600">
            {isPending
              ? "正在探测 gateway-go ..."
              : online
                ? `服务 ${data?.service ?? "gateway-go"} · 版本 ${data?.version ?? "unknown"}`
                : "无法连接 gateway-go，请先在 gateway-go/ 下执行 go run ./cmd/gateway"}
          </p>
          {error ? (
            <p className="mt-1 font-mono text-xs text-rose-600">
              {error instanceof Error ? error.message : "未知错误"}
            </p>
          ) : null}
          <p className="mt-2 font-mono text-xs text-slate-400">GET /healthz</p>
        </div>
      </div>

      <button
        type="button"
        onClick={() => void refetch()}
        disabled={isFetching}
        className="inline-flex shrink-0 items-center justify-center rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {isFetching ? "探测中..." : "重新探测"}
      </button>
    </section>
  );
}
