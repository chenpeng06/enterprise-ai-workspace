import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { useAuth } from "@/features/auth/AuthContext";
import { fetchDocuments, uploadDocument, type ApiError } from "@/lib/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const STATUS_STYLE: Record<string, string> = {
  ready: "bg-emerald-50 text-emerald-700",
  failed: "bg-rose-50 text-rose-700",
  queued: "bg-amber-50 text-amber-700",
  parsing: "bg-brand-50 text-brand-700",
  chunking: "bg-brand-50 text-brand-700",
  embedding: "bg-brand-50 text-brand-700",
  indexing: "bg-brand-50 text-brand-700",
};

export function AdminDocumentsPage() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: ({ signal }) => fetchDocuments(signal),
    refetchInterval: 3_000,
  });
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: uploadDocument,
    onSuccess: (result) => {
      setMessage(`已提交摄取任务 ${result.task_id.slice(0, 8)}…，正在解析与生成 Embedding。`);
      setFile(null);
      setTitle("");
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (error: ApiError) => setMessage(error.message),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file) {
      setMessage("请选择 PDF 文件");
      return;
    }
    setMessage(null);
    upload.mutate({ file, title: title.trim() || undefined });
  };

  if (!can("docs.upload")) {
    return <div className="card text-sm text-rose-600">当前角色没有文档上传权限。</div>;
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-brand-600">Knowledge Ingestion</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">文档摄取</h1>
          <p className="mt-1 text-sm text-slate-500">
            上传 PDF 后由引擎完成 pypdf 解析、父子切片、百炼 Embedding 与 pgvector 索引。
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/admin" className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50">返回监控</Link>
          <Link to="/chat" className="rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-600">去检索</Link>
        </div>
      </header>

      <section className="card space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">上传新 PDF</h2>
          <p className="mt-1 text-xs text-slate-500">仅支持 application/pdf，最大 50MB；重复 checksum 会被拒绝。</p>
        </div>
        <form className="grid gap-3 md:grid-cols-[1fr_1fr_auto]" onSubmit={submit}>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-600">PDF 文件</span>
            <input type="file" accept="application/pdf,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-xs" />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs text-slate-600">文档标题（可选）</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} className="w-full rounded-lg border border-slate-300 px-2.5 py-2 text-xs outline-none focus:border-brand-400" placeholder="默认使用文件名" />
          </label>
          <div className="flex items-end">
            <button type="submit" disabled={upload.isPending || !file} className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-600 disabled:opacity-60">
              {upload.isPending ? "上传中…" : "上传并摄取"}
            </button>
          </div>
        </form>
        {message ? <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">{message}</p> : null}
      </section>

      <section className="card overflow-hidden p-0">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-900">文档与摄取任务</h2>
          <span className="chip">{documents.data?.length ?? 0} docs</span>
        </div>
        {documents.isPending ? (
          <p className="p-4 text-sm text-slate-500">加载文档…</p>
        ) : documents.error ? (
          <p className="p-4 text-sm text-rose-600">文档加载失败。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-xs">
              <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-4 py-2 font-medium">文档</th>
                  <th className="px-4 py-2 font-medium">状态</th>
                  <th className="px-4 py-2 font-medium">切片</th>
                  <th className="px-4 py-2 font-medium">大小 / 页数</th>
                  <th className="px-4 py-2 font-medium">上传时间</th>
                </tr>
              </thead>
              <tbody>
                {(documents.data ?? []).map((document) => (
                  <tr key={document.document_id} className="border-t border-slate-100">
                    <td className="max-w-[280px] px-4 py-2.5">
                      <p className="truncate font-medium text-slate-700">{document.title}</p>
                      <p className="truncate font-mono text-[10px] text-slate-400">{document.file_name}</p>
                      {document.error_message ? <p className="mt-1 text-[10px] text-rose-600">{document.error_message}</p> : null}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`rounded-full px-2 py-1 text-[10px] ${STATUS_STYLE[document.status] ?? "bg-slate-100 text-slate-500"}`}>
                        {document.status}
                      </span>
                      {document.progress > 0 && document.progress < 100 ? (
                        <div className="mt-1.5 h-1 w-24 overflow-hidden rounded-full bg-slate-100">
                          <div className="h-full bg-brand-500" style={{ width: `${document.progress}%` }} />
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[10px] text-slate-500">{document.chunk_count}</td>
                    <td className="px-4 py-2.5 font-mono text-[10px] text-slate-500">
                      {formatBytes(document.size_bytes)} / {document.page_count}p
                    </td>
                    <td className="px-4 py-2.5 font-mono text-[10px] text-slate-400">
                      {new Date(document.created_at).toLocaleString("zh-CN")}
                    </td>
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
