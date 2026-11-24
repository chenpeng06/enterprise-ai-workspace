import { cn } from "@/lib/cn";
import type { Citation } from "@/types/contract";
import type { CitationTarget } from "@/types/public";

import { CitationText } from "./CitationText";
import { ProgressTimeline } from "./ProgressTimeline";
import type { ChatMessage } from "./types";

interface ChatMessageBubbleProps {
  message: ChatMessage;
  activeCitation: CitationTarget | null;
  onCitationClick: (citation: Citation, messageID: string) => void;
}

const STATUS_LABEL: Record<ChatMessage["status"], string> = {
  streaming: "生成中",
  completed: "已完成",
  refused: "证据不足 · 已拒答",
  failed: "失败",
  canceled: "已取消",
};

export function ChatMessageBubble({
  message,
  activeCitation,
  onCitationClick,
}: ChatMessageBubbleProps) {
  const isUser = message.role === "user";
  const activeIndex =
    activeCitation?.messageId === message.id ? activeCitation.citation.index : undefined;

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-tr-md bg-brand-500 px-4 py-3 text-sm leading-7 text-white shadow-sm">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="mt-1 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-slate-900 font-mono text-[10px] font-bold text-white">
        AI
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        <div
          className={cn(
            "rounded-2xl rounded-tl-md border bg-white px-4 py-3 shadow-sm",
            message.status === "failed"
              ? "border-rose-200"
              : message.status === "refused"
                ? "border-amber-200"
                : "border-slate-200",
          )}
        >
          {message.content ? (
            <CitationText
              text={message.content}
              citations={message.citations}
              activeIndex={activeIndex}
              onCitationClick={(citation) => onCitationClick(citation, message.id)}
            />
          ) : message.status === "streaming" ? (
            <div className="flex items-center gap-1.5 py-1 text-xs text-slate-400">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400 [animation-delay:-0.2s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400 [animation-delay:-0.1s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-brand-400" />
              <span className="ml-1">正在规划与检索…</span>
            </div>
          ) : (
            <p className="text-sm text-slate-400">未生成内容</p>
          )}

          <ProgressTimeline items={message.progress} />
        </div>

        {message.citations.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-wider text-slate-400">
              Sources
            </span>
            {message.citations.map((citation) => (
              <button
                key={citation.index}
                type="button"
                onClick={() => onCitationClick(citation, message.id)}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                  activeIndex === citation.index
                    ? "border-amber-400 bg-amber-50 text-amber-800"
                    : "border-slate-200 bg-white text-slate-500 hover:border-brand-300 hover:text-brand-700",
                )}
              >
                <span className="font-mono font-semibold">[{citation.index}]</span>
                <span className="max-w-[170px] truncate">{citation.document_title}</span>
                {citation.page_no ? <span className="text-slate-400">p.{citation.page_no}</span> : null}
              </button>
            ))}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-3 font-mono text-[10px] text-slate-400">
          <span
            className={cn(
              "rounded px-1.5 py-0.5",
              message.status === "failed"
                ? "bg-rose-50 text-rose-600"
                : message.status === "refused"
                  ? "bg-amber-50 text-amber-700"
                  : "bg-slate-100 text-slate-500",
            )}
          >
            {STATUS_LABEL[message.status]}
          </span>
          {message.timings ? (
            <>
              <span>TTFT {Math.round(message.timings.ttft_ms)}ms</span>
              <span>total {Math.round(message.timings.total_ms)}ms</span>
            </>
          ) : null}
          {message.usage ? (
            <span>
              tokens {message.usage.prompt_tokens}+{message.usage.completion_tokens}
              {" "}· {message.usage.model}
            </span>
          ) : null}
          {message.status === "streaming" ? (
            <span className="inline-flex items-center gap-1 text-brand-500">
              <span className="h-1 w-1 animate-ping rounded-full bg-brand-500" />
              live
            </span>
          ) : null}
        </div>

        {message.error ? (
          <p className="rounded-lg border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {message.error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
