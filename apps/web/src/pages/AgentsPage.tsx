import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Bot,
  ChevronLeft,
  ChevronRight,
  History,
  Plus,
  Send,
  Square,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { MarkdownContent } from "../components/MarkdownContent";
import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { MultiSelect, Select } from "../components/ui/select";
import { api } from "../lib/api";
import type {
  Agent,
  AgentRun,
  AgentRunHistory,
  KnowledgeBase,
  ProviderModel,
  User,
} from "../lib/types";
import { useAuthStore } from "../stores/auth";

const HISTORY_PAGE_SIZE = 12;

export function AgentsPage() {
  const user = useAuthStore((state) => state.user);
  const client = useQueryClient();
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [question, setQuestion] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [historyPage, setHistoryPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const [editingRuntime, setEditingRuntime] = useState(false);
  const [runtime, setRuntime] = useState({
    chat_model_id: "",
    max_steps: 8,
    max_tokens: 12000,
    timeout_seconds: 300,
  });
  const [form, setForm] = useState({
    name: "",
    description: "",
    system_prompt: "仅依据 SynapseKB 内部知识进行分析，关键结论必须保留引用。",
    chat_model_id: "",
    knowledge_base_ids: [] as string[],
    visibility: "all",
    user_ids: [] as string[],
    max_steps: 8,
    max_tokens: 12000,
    timeout_seconds: 300,
  });
  const { data: agents = [] } = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Agent[]>("/agents"),
  });
  const { data: models = [] } = useQuery({
    queryKey: ["models"],
    queryFn: () => api<ProviderModel[]>("/models"),
    enabled: user?.role === "admin",
  });
  const { data: knowledgeBases = [] } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api<KnowledgeBase[]>("/knowledge-bases"),
  });
  const { data: users = [] } = useQuery({
    queryKey: ["users"],
    queryFn: () => api<User[]>("/users"),
    enabled: user?.role === "admin",
  });
  const { data: run } = useQuery({
    queryKey: ["agent-run", runId],
    queryFn: () => api<AgentRun>(`/agents/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      query.state.data && ["completed", "cancelled", "failed"].includes(query.state.data.status)
        ? false
        : 1200,
  });
  const historyOffset = (historyPage - 1) * HISTORY_PAGE_SIZE;
  const {
    data: history,
    error: historyError,
    isLoading: historyLoading,
  } = useQuery({
    queryKey: ["agent-runs", selectedAgentId, historyPage],
    queryFn: () =>
      api<AgentRunHistory>(
        `/agents/${selectedAgentId}/runs?limit=${HISTORY_PAGE_SIZE}&offset=${historyOffset}`,
      ),
    enabled: Boolean(selectedAgentId),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) =>
        ["queued", "running"].includes(item.status),
      )
        ? 2000
        : false,
  });
  useEffect(() => {
    if (!selectedAgentId && agents[0]) setSelectedAgentId(agents[0].id);
  }, [agents, selectedAgentId]);
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId);
  useEffect(() => {
    if (!selectedAgent) return;
    setRuntime({
      chat_model_id: selectedAgent.chat_model_id,
      max_steps: selectedAgent.max_steps,
      max_tokens: selectedAgent.max_tokens,
      timeout_seconds: selectedAgent.timeout_seconds,
    });
  }, [selectedAgent]);
  useEffect(() => {
    if (
      run &&
      selectedAgentId === run.agent_id &&
      ["completed", "cancelled", "failed"].includes(run.status)
    ) {
      client.invalidateQueries({ queryKey: ["agent-runs", selectedAgentId] });
    }
  }, [client, run?.agent_id, run?.id, run?.status, selectedAgentId]);

  const start = useMutation({
    mutationFn: () =>
      api<AgentRun>(`/agents/${selectedAgentId}/runs`, {
        method: "POST",
        body: JSON.stringify({ query: question }),
      }),
    onSuccess: (created) => {
      setRunId(created.id);
      setQuestion("");
      setHistoryPage(1);
      client.invalidateQueries({ queryKey: ["agent-runs", selectedAgentId] });
    },
  });
  const cancel = useMutation({
    mutationFn: () =>
      api<AgentRun>(`/agents/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: (updated) => {
      client.setQueryData(["agent-run", runId], updated);
    },
  });
  const create = useMutation({
    mutationFn: () =>
      api<Agent>("/agents", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          max_steps: form.max_steps,
          max_tokens: form.max_tokens,
          timeout_seconds: form.timeout_seconds,
          recommended_questions: [],
        }),
      }),
    onSuccess: (agent) => {
      client.invalidateQueries({ queryKey: ["agents"] });
      setSelectedAgentId(agent.id);
      setCreating(false);
    },
  });
  const updateRuntime = useMutation({
    mutationFn: () =>
      api<Agent>(`/agents/${selectedAgentId}`, {
        method: "PATCH",
        body: JSON.stringify(runtime),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["agents"] });
      setEditingRuntime(false);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate();
  }

  const historyTotalPages = Math.max(
    1,
    Math.ceil((history?.total ?? 0) / HISTORY_PAGE_SIZE),
  );

  return (
    <>
      <PageHeader
        eyebrow="Knowledge Agent"
        title="知识分析 Agent"
        description="Agent 只能读取已授权的 SynapseKB 数据，具备步骤、时间和超时边界。"
        actions={
          user?.role === "admin" ? (
            <Button onClick={() => setCreating((value) => !value)}>
              <Plus size={16} />
              创建 Agent
            </Button>
          ) : undefined
        }
      />
      {creating && (
        <Card className="mb-6 p-6">
          <div className="grid gap-3 md:grid-cols-2">
            <Input
              placeholder="Agent 名称"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
            <Input
              placeholder="描述"
              value={form.description}
              onChange={(event) =>
                setForm({ ...form, description: event.target.value })
              }
            />
            <Select
              ariaLabel="Agent 专用 Chat 模型"
              value={form.chat_model_id}
              onValueChange={(value) =>
                setForm({ ...form, chat_model_id: value })
              }
              placeholder="选择 Agent 专用模型"
              options={models
                .filter((model) => model.kind === "chat")
                .map((model) => ({ value: model.id, label: model.name }))}
            />
            <label className="text-sm">
              <span className="mb-1.5 block text-xs font-medium text-[var(--muted)]">
                最终回答输出上限（Token）
              </span>
              <Input
                type="number"
                min={4000}
                max={32000}
                step={1000}
                value={form.max_tokens}
                onChange={(event) =>
                  setForm({ ...form, max_tokens: Number(event.target.value) })
                }
              />
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block text-xs font-medium text-[var(--muted)]">
                最大工具步骤
              </span>
              <Input
                type="number"
                min={1}
                max={20}
                value={form.max_steps}
                onChange={(event) =>
                  setForm({ ...form, max_steps: Number(event.target.value) })
                }
              />
            </label>
            <Select
              ariaLabel="可见范围"
              value={form.visibility}
              onValueChange={(value) =>
                setForm({ ...form, visibility: value })
              }
              options={[
                { value: "all", label: "所有用户可用" },
                { value: "users", label: "指定用户可用" },
              ]}
            />
            <MultiSelect
              ariaLabel="Agent 知识库"
              value={form.knowledge_base_ids}
              onValueChange={(value) =>
                setForm({
                  ...form,
                  knowledge_base_ids: value,
                })
              }
              placeholder="选择可访问知识库"
              options={knowledgeBases.map((knowledgeBase) => ({
                value: knowledgeBase.id,
                label: knowledgeBase.name,
              }))}
            />
            {form.visibility === "users" && (
              <MultiSelect
                ariaLabel="授权用户"
                value={form.user_ids}
                onValueChange={(value) =>
                  setForm({
                    ...form,
                    user_ids: value,
                  })
                }
                placeholder="选择授权用户"
                options={users
                  .filter((item) => item.is_active)
                  .map((item) => ({
                    value: item.id,
                    label: item.display_name,
                    description: item.email,
                  }))}
              />
            )}
            <textarea
              className="min-h-28 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3 text-sm md:col-span-2"
              value={form.system_prompt}
              onChange={(event) =>
                setForm({ ...form, system_prompt: event.target.value })
              }
            />
          </div>
          <Button
            className="mt-4"
            onClick={() => create.mutate()}
            disabled={
              create.isPending ||
              !form.name ||
              !form.chat_model_id ||
              form.knowledge_base_ids.length === 0 ||
              (form.visibility === "users" && form.user_ids.length === 0)
            }
          >
            保存
          </Button>
          {create.error && <p className="mt-3 text-sm text-red-500">{create.error.message}</p>}
        </Card>
      )}
      <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
        <aside className="space-y-4 lg:sticky lg:top-5 lg:self-start">
          <Card className="p-3">
            {agents.length === 0 ? (
              <p className="p-5 text-sm text-[var(--muted)]">暂无可用 Agent</p>
            ) : (
              agents.map((agent) => (
                <button
                  key={agent.id}
                  type="button"
                  className={`w-full rounded-xl p-3 text-left ${
                    selectedAgentId === agent.id
                      ? "bg-violet-500/10"
                      : "hover:bg-[var(--surface-hover)]"
                  }`}
                  onClick={() => {
                    if (selectedAgentId !== agent.id) {
                      setSelectedAgentId(agent.id);
                      setRunId(null);
                      setHistoryPage(1);
                    }
                  }}
                >
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <Bot size={16} className="text-violet-500" />
                    {agent.name}
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">
                    {agent.description}
                  </p>
                </button>
              ))
            )}
          </Card>
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
              <div className="flex items-center gap-2">
                <History size={15} className="text-violet-500" />
                <h2 className="text-sm font-semibold">运行历史</h2>
              </div>
              <span className="text-xs text-[var(--muted)]">
                {history?.total ?? 0} 条
              </span>
            </div>
            <div className="max-h-[28rem] overflow-y-auto p-2">
              {historyLoading ? (
                <p className="px-3 py-6 text-center text-xs text-[var(--muted)]">
                  正在加载历史…
                </p>
              ) : historyError ? (
                <p className="px-3 py-6 text-center text-xs text-red-500">
                  {historyError.message}
                </p>
              ) : history?.items.length ? (
                history.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    aria-label={`打开历史：${item.query}`}
                    className={`mb-1 w-full rounded-xl px-3 py-2.5 text-left transition ${
                      runId === item.id
                        ? "bg-violet-500/10 ring-1 ring-violet-500/15"
                        : "hover:bg-[var(--surface-hover)]"
                    }`}
                    onClick={() => setRunId(item.id)}
                  >
                    <p className="line-clamp-2 text-sm leading-5">{item.query}</p>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <StatusPill status={item.status} />
                      <time className="text-[11px] text-[var(--muted)]">
                        {new Date(item.created_at).toLocaleString("zh-CN", {
                          month: "numeric",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </time>
                    </div>
                  </button>
                ))
              ) : (
                <p className="px-3 py-6 text-center text-xs text-[var(--muted)]">
                  这个 Agent 还没有运行记录
                </p>
              )}
            </div>
            {history && history.total > HISTORY_PAGE_SIZE && (
              <div className="flex items-center justify-between border-t border-[var(--border)] px-3 py-2">
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label="上一页历史"
                  disabled={historyPage <= 1}
                  onClick={() => setHistoryPage((page) => Math.max(1, page - 1))}
                >
                  <ChevronLeft size={15} />
                </Button>
                <span className="text-xs text-[var(--muted)]">
                  {historyPage} / {historyTotalPages}
                </span>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label="下一页历史"
                  disabled={historyPage >= historyTotalPages}
                  onClick={() =>
                    setHistoryPage((page) => Math.min(historyTotalPages, page + 1))
                  }
                >
                  <ChevronRight size={15} />
                </Button>
              </div>
            )}
          </Card>
        </aside>
        <section>
          {user?.role === "admin" && selectedAgent && (
            <Card className="mb-4 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold">Agent 专用模型</h2>
                  <p className="mt-1 text-xs text-[var(--muted)]">
                    当前：{models.find((model) => model.id === selectedAgent.chat_model_id)?.name ?? "未找到模型"} · 最终回答 {selectedAgent.max_tokens} Token
                  </p>
                </div>
                <Button size="sm" variant="secondary" onClick={() => setEditingRuntime((value) => !value)}>
                  {editingRuntime ? "收起" : "调整"}
                </Button>
              </div>
              {editingRuntime && (
                <div className="mt-4 grid gap-3 md:grid-cols-4 md:items-end">
                  <label className="text-sm">
                    <span className="mb-1.5 block text-xs text-[var(--muted)]">Chat 模型</span>
                    <Select
                      ariaLabel="调整 Agent Chat 模型"
                      value={runtime.chat_model_id}
                      onValueChange={(value) => setRuntime({ ...runtime, chat_model_id: value })}
                      options={models
                        .filter((model) => model.kind === "chat" && model.is_enabled)
                        .map((model) => ({ value: model.id, label: model.name, description: model.model_name }))}
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1.5 block text-xs text-[var(--muted)]">回答上限</span>
                    <Input type="number" min={4000} max={32000} step={1000} value={runtime.max_tokens} onChange={(event) => setRuntime({ ...runtime, max_tokens: Number(event.target.value) })} />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1.5 block text-xs text-[var(--muted)]">工具步骤</span>
                    <Input type="number" min={1} max={20} value={runtime.max_steps} onChange={(event) => setRuntime({ ...runtime, max_steps: Number(event.target.value) })} />
                  </label>
                  <Button disabled={updateRuntime.isPending || !runtime.chat_model_id} onClick={() => updateRuntime.mutate()}>
                    {updateRuntime.isPending ? "保存中…" : "保存 Agent 配置"}
                  </Button>
                </div>
              )}
              {updateRuntime.error && <p className="mt-3 text-xs text-red-500">{updateRuntime.error.message}</p>}
            </Card>
          )}
          <Card className="min-h-80 p-6">
            {!run ? (
              <div className="flex min-h-64 items-center justify-center text-sm text-[var(--muted)]">
                选择 Agent 并提交一个分析问题。
              </div>
            ) : (
              <>
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-[var(--muted)]">分析问题</p>
                    <h2 className="mt-1 text-base font-semibold leading-6">{run.query}</h2>
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      {new Date(run.created_at).toLocaleString("zh-CN")}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusPill status={run.status} />
                    {["queued", "running"].includes(run.status) && (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => cancel.mutate()}
                      >
                        <Square size={14} />
                        取消
                      </Button>
                    )}
                  </div>
                </div>
                {run.resolved_time_summary && (
                  <div className="mt-5 rounded-xl bg-cyan-500/10 p-3 text-xs leading-6 text-cyan-700 dark:text-cyan-300">
                    {run.resolved_time_summary}
                  </div>
                )}
                <div className="mt-5">
                  {run.result ? (
                    <MarkdownContent>{run.result}</MarkdownContent>
                  ) : (
                    <p className={`text-sm leading-7 ${run.error_summary ? "text-red-500" : "text-[var(--muted)]"}`}>
                      {run.error_summary || "Agent 正在调用内部知识工具…"}
                    </p>
                  )}
                </div>
                {run.citations.length > 0 && (
                  <section className="mt-7 border-t border-[var(--border)] pt-5">
                    <div className="flex items-center gap-2">
                      <BookOpen size={16} className="text-violet-500" />
                      <h2 className="text-sm font-semibold">
                        来源文章（{run.citations.length}）
                      </h2>
                    </div>
                    <div className="mt-3 grid gap-3 lg:grid-cols-2">
                      {run.citations.map((citation) => (
                        <Link
                          key={`${citation.citation_number}-${citation.document_id}-${citation.chunk_id ?? "document"}`}
                          className="rounded-xl border border-[var(--border)] p-3 transition hover:border-violet-400/60 hover:bg-violet-500/5"
                          to={`/documents/${citation.document_id}${citation.chunk_id ? `?chunk=${citation.chunk_id}` : ""}`}
                        >
                          <div className="flex items-start gap-2 text-sm font-medium">
                            <span className="rounded-md bg-violet-500/10 px-1.5 py-0.5 text-xs text-violet-600 dark:text-violet-300">
                              [{citation.citation_number}]
                            </span>
                            <span className="line-clamp-2">{citation.document_name}</span>
                          </div>
                          <p className="mt-2 text-xs text-[var(--muted)]">
                            {citation.knowledge_base_name ? `${citation.knowledge_base_name} · ` : ""}
                            {citation.page_from !== null ? `第 ${citation.page_from} 页 · ` : ""}
                            {citation.section || "未标注章节"} · {citation.source_time ? new Date(citation.source_time).toLocaleDateString("zh-CN") : "时间未知"}
                          </p>
                          <p className="mt-2 line-clamp-3 text-xs leading-5 text-[var(--muted)]">
                            {citation.original_text}
                          </p>
                        </Link>
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </Card>
          <form
            className="mt-4 flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 shadow-[0_10px_35px_rgba(30,25,55,.06)] focus-within:border-violet-400/50 focus-within:ring-2 focus-within:ring-violet-500/10"
            onSubmit={submit}
          >
            <Input
              className="border-0 bg-transparent shadow-none focus:ring-0"
              placeholder="例如：比较 2023 年与 2025 年的制度变化"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
            />
            <Button
              type="submit"
              aria-label="运行 Agent"
              disabled={!selectedAgentId || !question.trim() || start.isPending}
            >
              <Send size={15} />
              {start.isPending ? "启动中…" : "运行"}
            </Button>
          </form>
          {start.error && <p className="mt-3 text-sm text-red-500">{start.error.message}</p>}
        </section>
      </div>
    </>
  );
}
