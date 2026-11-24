import { useState } from "react";

import { cn } from "@/lib/cn";
import type {
  RetrievalDiagnostics,
  RetrievalStageStats,
  SearchCandidate,
} from "@/types/contract";

interface RetrievalInspectorProps {
  diagnostics: RetrievalDiagnostics | null;
}

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "—";
  }
  return value.toFixed(3);
}

function ScoreBar({ value, max = 1 }: { value: number | null | undefined; max?: number }) {
  const ratio = value === null || value === undefined || max <= 0 ? 0 : Math.min(1, Math.max(0, value / max));
  return (
    <div className="flex min-w-[74px] items-center gap-1.5">
      <div className="h-1.5 w-10 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-brand-500" style={{ width: `${ratio * 100}%` }} />
      </div>
      <span className="font-mono text-[10px] text-slate-500">{formatScore(value)}</span>
    </div>
  );
}

function RankDelta({ candidate }: { candidate: SearchCandidate }) {
  const delta = candidate.rank_delta;
  if (delta === null || delta === undefined) {
    return <span className="text-slate-300">—</span>;
  }
  if (delta === 0) {
    return <span className="text-slate-400">持平</span>;
  }
  return (
    <span className={delta > 0 ? "text-emerald-600" : "text-rose-500"}>
      {delta > 0 ? "↑" : "↓"} {Math.abs(delta)}
    </span>
  );
}

const STAGE_LABELS: Array<{ key: keyof RetrievalStageStats; label: string }> = [
  { key: "vector", label: "Vector" },
  { key: "lexical", label: "BM25" },
  { key: "fusion", label: "RRF" },
  { key: "rerank", label: "Rerank" },
];

export function RetrievalInspector({ diagnostics }: RetrievalInspectorProps) {
  const [open, setOpen] = useState(true);

  if (!diagnostics) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50/60 p-5 text-sm text-slate-500">
        发起一次提问后，这里会展示向量、BM25、RRF 与 Rerank 的完整检索漏斗。
      </div>
    );
  }

  const { query, stages, candidates, selected_count } = diagnostics;
  const bm25Max = Math.max(1, ...candidates.map((candidate) => candidate.bm25_score ?? 0));
  const rrfMax = Math.max(...candidates.map((candidate) => candidate.rrf_score ?? 0), 0.0001);

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-card">
      <button
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50"
        aria-expanded={open}
      >
        <span>
          <span className="block text-sm font-semibold text-slate-900">检索过程透视</span>
          <span className="mt-0.5 block font-mono text-[10px] text-slate-400">
            {candidates.length} candidates · {selected_count} selected · {Math.round(diagnostics.total_latency_ms)}ms
          </span>
        </span>
        <span className="flex items-center gap-2">
          <span className="chip hidden sm:inline-flex">{stages.fusion.algorithm.toUpperCase()}</span>
          <span className={cn("text-xs text-slate-400 transition-transform", open && "rotate-180")}>▾</span>
        </span>
      </button>

      {open ? (
        <div className="space-y-4 border-t border-slate-100 px-4 pb-4 pt-3">
          <div className="rounded-xl bg-slate-50 p-3">
            <p className="font-mono text-[10px] uppercase tracking-widest text-slate-400">Query rewrite</p>
            <p className="mt-1 text-xs text-slate-500">
              <span className="text-slate-400">原始：</span>
              {query.original}
            </p>
            <p className="mt-1 text-xs text-slate-600">
              <span className="text-slate-400">改写：</span>
              {query.rewritten}
            </p>
            {query.rewrite_latency_ms !== null && query.rewrite_latency_ms !== undefined ? (
              <p className="mt-1 font-mono text-[10px] text-slate-400">
                rewrite {Math.round(query.rewrite_latency_ms)}ms · {query.rewrite_model ?? "rule"}
              </p>
            ) : null}
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {STAGE_LABELS.map(({ key, label }) => {
              const stage = stages[key];
              return (
                <div key={key} className="rounded-xl border border-slate-100 bg-slate-50/70 p-2.5">
                  <p className="font-mono text-[10px] uppercase tracking-wider text-slate-400">{label}</p>
                  <p className="mt-1 text-sm font-semibold text-slate-800">
                    {Math.round(stage.latency_ms)}ms
                  </p>
                  <p className="mt-0.5 text-[10px] text-slate-500">
                    {stage.candidates} 候选
                    {key === "rerank"
                      ? "enabled" in stage && stage.enabled
                        ? " · 已启用"
                        : " · 未配置"
                      : ""}
                  </p>
                  {key === "rerank" && "enabled" in stage && stage.enabled && stage.model ? (
                    <p
                      className="mt-0.5 break-all font-mono text-[8px] leading-tight text-slate-400"
                      title={stage.model}
                    >
                      {stage.model}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>

          <div className="space-y-2">
            {candidates.map((candidate) => (
              <article
                key={candidate.chunk_id}
                className={cn(
                  "rounded-xl border p-2.5",
                  candidate.selected
                    ? "border-amber-200 bg-amber-50/40"
                    : "border-slate-200 bg-white",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-slate-700">
                      <span className="mr-1 font-mono text-[10px] text-slate-400">
                        #{candidate.fused_rank ?? "—"}
                      </span>
                      {candidate.document_title}
                    </p>
                    <p className="mt-0.5 font-mono text-[10px] text-slate-400">
                      p.{candidate.page_no ?? "?"} · {candidate.chunk_type ?? "text"} ·{" "}
                      {candidate.section_path?.slice(-1)[0] ?? "未标注章节"}
                    </p>
                  </div>
                  {candidate.selected ? (
                    <span className="shrink-0 rounded-full bg-emerald-100 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-emerald-700">
                      ✓ [{candidate.citation_index ?? "?"}]
                    </span>
                  ) : null}
                </div>

                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-wider text-slate-400">Vector</p>
                    <ScoreBar value={candidate.vector_score} />
                  </div>
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-wider text-slate-400">BM25</p>
                    <ScoreBar value={candidate.bm25_score} max={bm25Max} />
                  </div>
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-wider text-slate-400">RRF</p>
                    <ScoreBar value={candidate.rrf_score} max={rrfMax} />
                  </div>
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-wider text-slate-400">Rerank</p>
                    <ScoreBar value={candidate.rerank_score} />
                  </div>
                </div>

                <div className="mt-2 flex items-center justify-between border-t border-slate-100 pt-1.5 font-mono text-[10px] text-slate-400">
                  <span>
                    fused #{candidate.fused_rank ?? "—"} → rerank #{candidate.rerank_rank ?? "—"}
                  </span>
                  <RankDelta candidate={candidate} />
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
