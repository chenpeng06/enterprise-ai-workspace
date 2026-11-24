import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/cn";
import type { Citation } from "@/types/contract";

interface CitationTextProps {
  text: string;
  citations: Citation[];
  activeIndex?: number;
  onCitationClick: (citation: Citation) => void;
}

export function CitationText({
  text,
  citations,
  activeIndex,
  onCitationClick,
}: CitationTextProps) {
  const byIndex = new Map(citations.map((citation) => [citation.index, citation]));
  const markdown = text.replace(/\[(\d+)\]/g, (match, value: string) =>
    byIndex.has(Number(value)) ? `[${value}](#citation-${value})` : match,
  );

  const components: Components = {
    h1: ({ children }) => (
      <h1 className="mb-3 mt-5 text-lg font-bold tracking-tight text-slate-900 first:mt-0">
        {children}
      </h1>
    ),
    h2: ({ children }) => (
      <h2 className="mb-2 mt-5 text-base font-semibold tracking-tight text-slate-900 first:mt-0">
        {children}
      </h2>
    ),
    h3: ({ children }) => (
      <h3 className="mb-2 mt-4 text-sm font-semibold text-slate-800 first:mt-0">{children}</h3>
    ),
    p: ({ children }) => <p className="mb-3 text-sm leading-7 text-slate-700 last:mb-0">{children}</p>,
    ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 text-sm leading-7 text-slate-700">{children}</ul>,
    ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm leading-7 text-slate-700">{children}</ol>,
    li: ({ children }) => <li className="pl-0.5">{children}</li>,
    blockquote: ({ children }) => (
      <blockquote className="mb-3 border-l-2 border-brand-200 bg-brand-50/50 px-3 py-1 text-sm text-slate-600">
        {children}
      </blockquote>
    ),
    code: ({ className, children, ...props }) => {
      const isBlock = Boolean(className);
      if (isBlock) {
        return (
          <code className={cn("font-mono text-xs text-slate-100", className)} {...props}>
            {children}
          </code>
        );
      }
      return (
        <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[12px] text-slate-700" {...props}>
          {children}
        </code>
      );
    },
    pre: ({ children }) => (
      <pre className="mb-3 overflow-x-auto rounded-xl bg-slate-900 p-3 font-mono text-xs leading-6 text-slate-100">
        {children}
      </pre>
    ),
    table: ({ children }) => (
      <div className="mb-3 overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full border-collapse text-left text-xs">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">{children}</thead>,
    th: ({ children }) => <th className="border-b border-slate-200 px-2 py-1.5 font-medium">{children}</th>,
    td: ({ children }) => <td className="border-b border-slate-100 px-2 py-1.5 align-top text-slate-600 last:border-0">{children}</td>,
    hr: () => <hr className="my-4 border-slate-100" />,
    a: ({ href, children }) => {
      if (href?.startsWith("#citation-")) {
        const citationIndex = Number(href.replace("#citation-", ""));
        const citation = byIndex.get(citationIndex);
        if (citation) {
          return (
            <button
              type="button"
              onClick={() => onCitationClick(citation)}
              className={cn(
                "mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md border px-1 align-baseline font-mono text-[11px] font-semibold transition-colors",
                activeIndex === citationIndex
                  ? "border-amber-500 bg-amber-400 text-amber-950"
                  : "border-brand-200 bg-brand-50 text-brand-700 hover:border-brand-400 hover:bg-brand-100",
              )}
              title={`${citation.document_title}${citation.page_no ? ` · 第 ${citation.page_no} 页` : ""}`}
            >
              {citationIndex}
            </button>
          );
        }
      }
      return (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="text-brand-600 underline decoration-brand-200 underline-offset-2 hover:text-brand-700"
        >
          {children}
        </a>
      );
    },
  };

  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {markdown}
    </ReactMarkdown>
  );
}
