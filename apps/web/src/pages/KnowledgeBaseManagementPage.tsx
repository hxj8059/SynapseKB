import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { api } from "../lib/api";
import type {
  KnowledgeBaseDeletionJob,
  KnowledgeBaseManagementItem,
} from "../lib/types";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${unit}`;
}

const lifecycleLabels: Record<string, string> = {
  active: "正常",
  deleting: "正在删除",
  deletion_failed: "删除失败",
};

export function KnowledgeBaseManagementPage() {
  const client = useQueryClient();
  const [target, setTarget] = useState<KnowledgeBaseManagementItem | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const { data = [], refetch, isFetching } = useQuery({
    queryKey: ["knowledge-bases", "management"],
    queryFn: () =>
      api<KnowledgeBaseManagementItem[]>("/knowledge-bases/management"),
    refetchInterval: (query) =>
      query.state.data?.some((item) => item.lifecycle_status === "deleting")
        ? 3000
        : false,
  });
  const remove = useMutation({
    mutationFn: (item: KnowledgeBaseManagementItem) =>
      api<KnowledgeBaseDeletionJob>(`/knowledge-bases/${item.id}`, {
        method: "DELETE",
        body: JSON.stringify({ confirmation_name: confirmation }),
      }),
    onSuccess: () => {
      setTarget(null);
      setConfirmation("");
      void client.invalidateQueries({ queryKey: ["knowledge-bases"] });
      void client.invalidateQueries({ queryKey: ["operation-tasks"] });
    },
  });

  function openDeletion(item: KnowledgeBaseManagementItem) {
    remove.reset();
    setConfirmation("");
    setTarget(item);
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="知识库管理"
        description="集中查看知识库规模和生命周期。删除会在后台分批清理对象存储与索引，并记录到任务中心和审计日志。"
        actions={
          <Button variant="secondary" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw size={15} />
            刷新
          </Button>
        }
      />

      <Card className="overflow-hidden">
        {data.length === 0 ? (
          <div className="flex min-h-64 items-center justify-center text-sm text-[var(--muted)]">
            暂无知识库
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {data.map((item) => {
              const job = item.deletion_job;
              const busy = item.lifecycle_status === "deleting";
              return (
                <div
                  key={item.id}
                  className="grid gap-4 px-5 py-5 lg:grid-cols-[minmax(260px,1fr)_150px_160px_150px_auto] lg:items-center"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="truncate text-base font-semibold">{item.name}</h2>
                      <StatusPill status={item.lifecycle_status} />
                      <span className="text-xs text-[var(--muted)]">
                        {lifecycleLabels[item.lifecycle_status] ?? item.lifecycle_status}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm leading-6 text-[var(--muted)]">
                      {item.description || "暂无描述"}
                    </p>
                    {job?.error_summary && (
                      <p className="mt-2 text-xs text-red-500">{job.error_summary}</p>
                    )}
                    {busy && job && (
                      <div className="mt-3 max-w-sm">
                        <div className="mb-1 flex justify-between text-xs text-[var(--muted)]">
                          <span>{job.stage || "正在准备"}</span>
                          <span>{Math.round(job.progress * 100)}%</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-strong)]">
                          <div
                            className="h-full rounded-full bg-violet-500 transition-[width]"
                            style={{ width: `${Math.round(job.progress * 100)}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                  <div>
                    <div className="text-xs text-[var(--muted)]">文档</div>
                    <div className="mt-1 text-sm font-semibold">
                      {item.document_count.toLocaleString("zh-CN")}
                    </div>
                    <div className="mt-0.5 text-xs text-[var(--muted)]">
                      {item.ready_document_count.toLocaleString("zh-CN")} 已就绪
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-[var(--muted)]">原始文件总量</div>
                    <div className="mt-1 text-sm font-semibold">
                      {formatBytes(item.total_size_bytes)}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-[var(--muted)]">创建时间</div>
                    <div className="mt-1 text-sm">
                      {new Date(item.created_at).toLocaleDateString("zh-CN")}
                    </div>
                  </div>
                  <div className="flex gap-2 lg:justify-end">
                    {item.lifecycle_status === "active" && (
                      <Button asChild size="sm" variant="secondary">
                        <Link to={`/knowledge-bases/${item.id}`}>
                          <ExternalLink size={14} />
                          打开
                        </Link>
                      </Button>
                    )}
                    {!busy && (
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => openDeletion(item)}
                      >
                        <Trash2 size={14} />
                        {item.lifecycle_status === "deletion_failed"
                          ? "重试删除"
                          : "删除"}
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Dialog.Root
        open={Boolean(target)}
        onOpenChange={(open) => {
          if (!open && !remove.isPending) setTarget(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-zinc-950/45 backdrop-blur-[2px]" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,520px)] -translate-x-1/2 -translate-y-1/2 rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-2xl outline-none">
            <div className="flex items-start justify-between gap-4">
              <div>
                <Dialog.Title className="text-xl font-semibold tracking-[-0.02em]">
                  删除知识库
                </Dialog.Title>
                <Dialog.Description className="mt-2 text-sm leading-6 text-[var(--muted)]">
                  将永久删除文档、文本块、Wiki、关系图和对象存储文件。任务开始后知识库会立即停止检索。
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <Button aria-label="关闭" size="icon" variant="ghost">
                  <X size={17} />
                </Button>
              </Dialog.Close>
            </div>
            <div className="mt-5 rounded-2xl border border-red-500/20 bg-red-500/5 p-4 text-sm">
              <div className="font-semibold">{target?.name}</div>
              <div className="mt-1 text-[var(--muted)]">
                {target?.document_count.toLocaleString("zh-CN")} 份文档 · {" "}
                {formatBytes(target?.total_size_bytes ?? 0)}
              </div>
            </div>
            <label className="mt-5 block text-sm font-medium" htmlFor="kb-delete-name">
              输入知识库名称以确认
            </label>
            <Input
              id="kb-delete-name"
              className="mt-2"
              autoComplete="off"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              placeholder={target?.name}
            />
            {remove.error && (
              <p className="mt-3 text-sm text-red-500">{remove.error.message}</p>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <Dialog.Close asChild>
                <Button variant="secondary" disabled={remove.isPending}>
                  取消
                </Button>
              </Dialog.Close>
              <Button
                variant="danger"
                disabled={
                  !target || confirmation !== target.name || remove.isPending
                }
                onClick={() => target && remove.mutate(target)}
              >
                <Trash2 size={15} />
                {remove.isPending ? "正在创建删除任务" : "确认永久删除"}
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
