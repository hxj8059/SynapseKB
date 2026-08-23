import { useMutation, useQuery } from "@tanstack/react-query";
import { Activity, RefreshCw, RotateCcw } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { api } from "../lib/api";
import type { OperationTask } from "../lib/types";

const PAGE_SIZE = 100;
const TASK_CATEGORIES = [
  { value: "all", label: "全部" },
  { value: "document", label: "文档 / OCR" },
  { value: "agent", label: "Agent" },
  { value: "wiki_update", label: "Wiki 生成" },
  { value: "wiki_health", label: "Wiki 健康检查" },
  { value: "knowledge_base", label: "知识库管理" },
] as const;

const TASK_TYPE_LABELS: Record<string, string> = {
  "document.parse": "文档解析 / OCR",
  "agent.run": "Agent 运行",
  "wiki.update": "Wiki 生成 / 更新",
  "wiki.health": "Wiki 健康检查",
  "knowledge_base.delete": "删除知识库",
};

export function TasksPage() {
  const [category, setCategory] = useState<(typeof TASK_CATEGORIES)[number]["value"]>("all");
  const [page, setPage] = useState(0);
  const { data: tasks = [], refetch, isFetching } = useQuery({
    queryKey: ["operation-tasks", category, page],
    queryFn: () =>
      api<OperationTask[]>(
        `/operations/tasks?category=${category}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`,
      ),
    refetchInterval: (query) =>
      query.state.data?.some((task) =>
        ["queued", "running", "quality_check"].includes(task.status),
      )
        ? 3000
        : false,
  });
  const retryFailedWikiDocuments = useMutation({
    mutationFn: (taskId: string) =>
      api(`/wiki/jobs/${taskId}/retry-failed`, { method: "POST" }),
    onSuccess: () => refetch(),
  });
  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title="任务中心"
        description="文档、OCR、Agent、Wiki 与知识库维护任务的数据库真实状态。"
        actions={
          <Button variant="secondary" onClick={() => refetch()} disabled={isFetching}>
            <RefreshCw size={15} />
            刷新
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {TASK_CATEGORIES.map((item) => (
          <Button
            key={item.value}
            size="sm"
            variant={category === item.value ? "primary" : "secondary"}
            onClick={() => {
              setCategory(item.value);
              setPage(0);
            }}
          >
            {item.label}
          </Button>
        ))}
      </div>
      <Card className="overflow-hidden">
        {tasks.length === 0 ? (
          <div className="flex min-h-64 flex-col items-center justify-center text-sm text-[var(--muted)]">
            <Activity className="mb-3 text-violet-500" />
            暂无任务
          </div>
        ) : (
          <div className="divide-y divide-[var(--border)]">
            {tasks.map((task) => (
              <div
                key={`${task.task_type}-${task.id}`}
                className="grid gap-3 px-5 py-4 md:grid-cols-[1fr_140px_100px_170px_auto] md:items-center"
              >
                <div>
                  <div className="text-sm font-semibold">
                    {TASK_TYPE_LABELS[task.task_type] ?? task.task_type}
                  </div>
                  <div className="mt-1 font-mono text-xs text-[var(--muted)]">
                    {task.id}
                  </div>
                  {task.error_summary && (
                    <p className="mt-2 text-xs text-red-500">{task.error_summary}</p>
                  )}
                  {task.model_name && (
                    <p className="mt-2 text-xs text-[var(--muted)]">
                      模型：{task.model_name}
                    </p>
                  )}
                  {task.summary && (
                    <p className="mt-1 text-xs text-[var(--muted)]">{task.summary}</p>
                  )}
                  {typeof task.progress === "number" && (
                    <div className="mt-2 flex items-center gap-2 text-xs text-[var(--muted)]">
                      <div className="h-1.5 w-32 overflow-hidden rounded-full bg-[var(--surface-strong)]">
                        <div
                          className="h-full rounded-full bg-violet-500 transition-[width]"
                          style={{ width: `${Math.round(task.progress * 100)}%` }}
                        />
                      </div>
                      {Math.round(task.progress * 100)}%
                    </div>
                  )}
                </div>
                <span className="text-xs text-[var(--muted)]">
                  {task.stage || "—"}
                </span>
                <StatusPill status={task.status} />
                <span className="text-xs text-[var(--muted)]">
                  {new Date(task.updated_at).toLocaleString("zh-CN")}
                </span>
                <div className="min-w-36 md:text-right">
                  {task.task_type === "wiki.update" &&
                  ["failed", "quality_failed"].includes(task.status) ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={retryFailedWikiDocuments.isPending}
                      onClick={() => retryFailedWikiDocuments.mutate(task.id)}
                    >
                      <RotateCcw size={14} />
                      重试失败文档
                    </Button>
                  ) : null}
                  {retryFailedWikiDocuments.isError &&
                  retryFailedWikiDocuments.variables === task.id ? (
                    <p className="mt-2 text-xs text-red-500">
                      {retryFailedWikiDocuments.error.message}
                    </p>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
      <div className="mt-4 flex items-center justify-between">
        <span className="text-xs text-[var(--muted)]">
          第 {page + 1} 页 · 每类任务独立分页
        </span>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={page === 0 || isFetching}
            onClick={() => setPage((value) => Math.max(0, value - 1))}
          >
            上一页
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={tasks.length < PAGE_SIZE || isFetching}
            onClick={() => setPage((value) => value + 1)}
          >
            下一页
          </Button>
        </div>
      </div>
    </>
  );
}
