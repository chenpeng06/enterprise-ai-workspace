import { useQuery } from "@tanstack/react-query";

import { fetchChunk } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { Citation } from "@/types/contract";

interface DocumentPreviewProps {
  citation: Citation | null;
}

function highlightContent(content: string, quote: string) {
  if (!quote) {
    return content;
  }
  const index = content.indexOf(quote);
  if (index === -1) {
    return content;
  }
  return (
    <>
      {content.slice(0, index)}
      <mark className="rounded bg-amber-200 px-0.5 text-slate-900">{quote}</mark>
      {content.slice(index + quote.length)}
    </>
  );
}

export function DocumentPreview({ citation }: DocumentPreviewProps) {
  const { data, error, isPending } = useQuery({
    queryKey: ["chunk-preview", citation?.chunk_id],
    queryFn: ({ signal }) => fetchChunk(citation!.chunk_id, signal),
    enabled: Boolean(citation?.chunk_id),
  });

  if (!citation) {
    return (
      <div className="flex min-h-[260px] flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-slate-50/70 px-6 text-center">
        <span className="font-mono text-2xl text-brand-500">[n]</span>
        <p className="mt-3 text-sm font-medium text-slate-700">点击回答中的角标查看原文</p>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          右侧会展示文档标题、页码、bbox 命中框与高亮片段。
        </p>
      </div>
    );
  }

  if (isPending) {
    return <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500">正在读取切片与原文定位…</div>;
  }

  if (error || !data) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm text-rose-700">
        原文加载失败：{error instanceof Error ? error.message : "未知错误"}
      </div>
    );
  }

  const bbox = data.bbox;
  const page = data.page_no ?? 0;

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-sm font-semibold text-slate-900">{data.document_title}</h3>
          <span className="chip shrink-0">第 {page || "?"} 页</span>
        </div>
        <p className="truncate font-mono text-[11px] text-slate-400">
          {data.file_name} · {data.page_count} 页 · 切片 #{data.chunk_id.slice(0, 8)}
        </p>
        <div className="flex flex-wrap gap-1">
          {data.section_path.map((section) => (
            <span key={section} className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
              {section}
            </span>
          ))}
        </div>
      </header>

      <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-[#fbfaf7] shadow-inner">
        <div className="flex items-center justify-between border-b border-slate-200 bg-white/80 px-4 py-2">
          <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">
            Document Preview
          </span>
          <span className="font-mono text-[10px] text-slate-400">
            {page} / {data.page_count || "?"}
          </span>
        </div>
        <div className="relative min-h-[330px] px-6 py-5">
          <div className="mb-4 space-y-2">
            <div className="h-2 w-2/5 rounded bg-slate-200" />
            <div className="h-1.5 w-4/5 rounded bg-slate-100" />
          </div>
          <p className="text-[13px] leading-7 text-slate-600">
            {highlightContent(data.content, citation.quote)}
          </p>

          {bbox ? (
            <div
              className="pointer-events-none absolute rounded-md border-2 border-amber-500 bg-amber-300/20 shadow-[0_0_0_3px_rgba(245,158,11,0.12)]"
              style={{
                left: `${bbox.x0 * 100}%`,
                top: `${bbox.y0 * 100}%`,
                width: `${(bbox.x1 - bbox.x0) * 100}%`,
                height: `${(bbox.y1 - bbox.y0) * 100}%`,
              }}
              aria-hidden="true"
            >
              <span className="absolute -top-5 left-0 rounded bg-amber-500 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-white">
                命中位置
              </span>
            </div>
          ) : null}

          <div className="pointer-events-none absolute inset-x-6 bottom-5 flex items-center justify-between border-t border-dashed border-slate-200 pt-2 font-mono text-[9px] text-slate-400">
            <span>bbox {bbox ? `${bbox.x0.toFixed(3)}, ${bbox.y0.toFixed(3)} → ${bbox.x1.toFixed(3)}, ${bbox.y1.toFixed(3)}` : "未提供"}</span>
            <span>{data.char_start ?? 0}–{data.char_end ?? 0} chars</span>
          </div>
        </div>
      </div>

      <div className={cn("rounded-xl border border-slate-200 bg-white p-3", !bbox && "border-dashed")}>
        <p className="font-mono text-[10px] uppercase tracking-widest text-slate-400">引用片段</p>
        <p className="mt-2 text-xs leading-6 text-slate-600">“{citation.quote}”</p>
      </div>

      {data.parent_content && data.parent_content !== data.content ? (
        <details className="rounded-xl border border-slate-200 bg-white p-3">
          <summary className="cursor-pointer text-xs font-medium text-slate-600">父切片上下文</summary>
          <p className="mt-2 text-xs leading-6 text-slate-500">{data.parent_content}</p>
        </details>
      ) : null}
    </div>
  );
}
