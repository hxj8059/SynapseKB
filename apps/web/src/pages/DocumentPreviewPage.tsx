import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, RefreshCw, Save, Square, Trash2 } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { MarkdownContent } from "../components/MarkdownContent";
import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { DateTimePicker } from "../components/ui/date-time-picker";
import { Input } from "../components/ui/input";
import { api, authenticatedFetch, download } from "../lib/api";
import type { Document, DocumentChunk, ProcessingJob } from "../lib/types";
import { useAuthStore } from "../stores/auth";

export function DocumentPreviewPage() {
  const { id = "" } = useParams();
  const [searchParams] = useSearchParams();
  const selectedChunkId = searchParams.get("chunk");
  const navigate = useNavigate();
  const client = useQueryClient();
  const isAdmin = useAuthStore((state) => state.user?.role === "admin");
  const [view, setView] = useState<"parsed" | "chunks">(
    selectedChunkId ? "chunks" : "parsed",
  );
  const [title, setTitle] = useState("");
  const [sourceTime, setSourceTime] = useState("");
  const { data: document } = useQuery({
    queryKey: ["document", id],
    queryFn: () => api<Document>(`/documents/${id}`),
    enabled: Boolean(id),
  });
  const { data: parsed = "", error: parsedError } = useQuery({
    queryKey: ["document-parsed", id],
    queryFn: async () => {
      const response = await authenticatedFetch(`/documents/${id}/parsed`);
      if (!response.ok) throw new Error(`解析文本暂不可用（${response.status}）`);
      return response.text();
    },
    enabled: Boolean(id) && document?.status === "ready",
  });
  const { data: chunks = [] } = useQuery({
    queryKey: ["document-chunks", id],
    queryFn: () => api<DocumentChunk[]>(`/documents/${id}/chunks?limit=500`),
    enabled: Boolean(id) && document?.status === "ready",
  });
  const { data: jobs = [] } = useQuery({
    queryKey: ["document-jobs", id],
    queryFn: () => api<ProcessingJob[]>(`/documents/${id}/jobs`),
    enabled: Boolean(id),
    refetchInterval: document && ["queued", "processing"].includes(document.status) ? 3000 : false,
  });

  useEffect(() => {
    if (!document) return;
    setTitle(document.title);
    setSourceTime(
      document.source_time ? new Date(document.source_time).toISOString().slice(0, 16) : "",
    );
  }, [document]);
  useEffect(() => {
    if (!selectedChunkId || view !== "chunks" || chunks.length === 0) return;
    documentQuery(selectedChunkId)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [chunks, selectedChunkId, view]);

  const save = useMutation({
    mutationFn: () =>
      api<Document>(`/documents/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          title,
          source_time: sourceTime ? new Date(sourceTime).toISOString() : null,
        }),
      }),
    onSuccess: (updated) => {
      client.setQueryData(["document", id], updated);
      void client.invalidateQueries({ queryKey: ["documents", updated.knowledge_base_id] });
    },
  });
  const retry = useMutation({
    mutationFn: () => api(`/documents/${id}/retry`, { method: "POST" }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["document", id] });
      void client.invalidateQueries({ queryKey: ["document-jobs", id] });
    },
  });
  const cancel = useMutation({
    mutationFn: () => api(`/documents/${id}/cancel`, { method: "POST" }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["document-jobs", id] }),
  });
  const remove = useMutation({
    mutationFn: () => api<void>(`/documents/${id}`, { method: "DELETE" }),
    onSuccess: () => navigate(`/knowledge-bases/${document?.knowledge_base_id ?? ""}`),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <>
      <PageHeader
        eyebrow="Document"
        title={document?.title ?? "文档预览"}
        description={
          document
            ? `${document.filename} · source_time: ${document.source_time ?? "未知"}`
            : "正在读取文档"
        }
        actions={
          <div className="flex gap-2">
            <Link to={`/knowledge-bases/${document?.knowledge_base_id ?? ""}`}>
              <Button variant="ghost">
                <ArrowLeft size={15} />
                返回
              </Button>
            </Link>
            {document && (
              <Button
                variant="secondary"
                onClick={() =>
                  void download(`/documents/${document.id}/download`, document.filename)
                }
              >
                <Download size={15} />
                原文
              </Button>
            )}
          </div>
        }
      />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
        <Card className="min-w-0 p-6">
          <div className="mb-5 flex gap-2 border-b border-[var(--border)] pb-4">
            <Button
              variant={view === "parsed" ? "primary" : "ghost"}
              onClick={() => setView("parsed")}
            >
              解析文本
            </Button>
            <Button
              variant={view === "chunks" ? "primary" : "ghost"}
              onClick={() => setView("chunks")}
            >
              文本块（{chunks.length}）
            </Button>
          </div>
          {view === "parsed" ? (
            parsed ? (
              <MarkdownContent>{parsed}</MarkdownContent>
            ) : (
              <p className="py-16 text-center text-sm text-[var(--muted)]">
                {parsedError instanceof Error
                  ? parsedError.message
                  : "文档处理完成后可查看解析文本。"}
              </p>
            )
          ) : (
            <div className="space-y-3">
              {chunks.map((chunk) => (
                <article
                  id={`chunk-${chunk.id}`}
                  key={chunk.id}
                  className={`rounded-xl border p-4 ${
                    chunk.id === selectedChunkId
                      ? "border-violet-500 bg-violet-500/5"
                      : "border-[var(--border)]"
                  }`}
                >
                  <div className="mb-2 text-xs text-[var(--muted)]">
                    #{chunk.ordinal + 1} · {chunk.section ?? "未标注章节"} ·{" "}
                    {chunk.page_from ? `第 ${chunk.page_from} 页` : "页码未知"} ·{" "}
                    {chunk.token_count} tokens
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-7">{chunk.content}</p>
                </article>
              ))}
            </div>
          )}
        </Card>
        <aside className="space-y-5">
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">处理状态</h2>
              {document && <StatusPill status={document.status} />}
            </div>
            <div className="mt-4 space-y-3 text-xs text-[var(--muted)]">
              {jobs.map((job) => (
                <div key={job.id} className="rounded-lg bg-[var(--surface-hover)] p-3">
                  <div>
                    {job.stage ?? job.job_type} · {Math.round(job.progress * 100)}%
                  </div>
                  {job.error_summary && <p className="mt-1 text-red-500">{job.error_summary}</p>}
                </div>
              ))}
            </div>
            {isAdmin && (
              <div className="mt-4 flex gap-2">
                <Button size="sm" variant="secondary" onClick={() => retry.mutate()}>
                  <RefreshCw size={13} />
                  重新解析
                </Button>
                <Button size="sm" variant="ghost" onClick={() => cancel.mutate()}>
                  <Square size={13} />
                  取消
                </Button>
              </div>
            )}
          </Card>
          {isAdmin && document && (
            <Card className="p-5">
              <h2 className="text-sm font-semibold">文档信息</h2>
              <form className="mt-4 space-y-3" onSubmit={submit}>
                <Input value={title} onChange={(event) => setTitle(event.target.value)} />
                <DateTimePicker
                  ariaLabel="文档来源时间"
                  value={sourceTime}
                  onValueChange={setSourceTime}
                  placeholder="来源时间（可选）"
                />
                <Button size="sm" disabled={save.isPending} type="submit">
                  <Save size={13} />
                  保存
                </Button>
              </form>
              <Button
                className="mt-5 text-red-500"
                size="sm"
                variant="ghost"
                onClick={() => {
                  if (window.confirm(`确认删除“${document.title}”及其索引？`)) remove.mutate();
                }}
              >
                <Trash2 size={13} />
                删除文档
              </Button>
            </Card>
          )}
        </aside>
      </div>
    </>
  );
}

function documentQuery(chunkId: string): HTMLElement | null {
  return window.document.getElementById(`chunk-${chunkId}`);
}
