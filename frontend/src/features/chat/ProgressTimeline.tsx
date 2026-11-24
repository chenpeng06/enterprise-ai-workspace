import type { ProgressItem } from "./types";
import { cn } from "@/lib/cn";

const STATUS_CLASS: Record<ProgressItem["status"], string> = {
  started: "bg-amber-400",
  succeeded: "bg-emerald-500",
  failed: "bg-rose-500",
  skipped: "bg-slate-300",
};

const STATUS_TEXT: Record<ProgressItem["status"], string> = {
  started: "进行中",
  succeeded: "完成",
  failed: "失败",
  skipped: "跳过",
};

export function ProgressTimeline({ items }: { items: ProgressItem[] }) {
  if (items.length === 0) {
    return null;
  }

  return (
    <ol className="mt-3 space-y-1.5 border-t border-slate-100 pt-3">
      {items.map((item) => (
        <li key={item.id} className="flex items-start gap-2 text-xs">
          <span
            className={cn("mt-1 h-1.5 w-1.5 shrink-0 rounded-full", STATUS_CLASS[item.status])}
            aria-hidden="true"
          />
          <span className="min-w-0">
            <span className="font-medium text-slate-700">{item.label}</span>
            <span className="ml-2 text-slate-400">{STATUS_TEXT[item.status]}</span>
            {item.detail ? (
              <span className="ml-2 text-slate-500">{item.detail}</span>
            ) : null}
          </span>
        </li>
      ))}
    </ol>
  );
}
