import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, ServerCog, Trash2, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { api } from "../lib/api";
import type { ModelTestResult, ProviderModel } from "../lib/types";

const presets: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  deepseek: "https://api.deepseek.com/v1",
  dashscope: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  ollama: "http://host.docker.internal:11434/v1",
};

function presetBaseUrl(provider: string, kind: string) {
  if (provider === "dashscope" && kind === "rerank") {
    return "https://dashscope.aliyuncs.com/compatible-api/v1";
  }
  return presets[provider] ?? "";
}

function hasReasoningDisabled(model: ProviderModel) {
  const chatExtraBody = model.config.chat_extra_body as
    | Record<string, unknown>
    | undefined;
  return (
    chatExtraBody?.enable_thinking === false ||
    chatExtraBody?.reasoning_effort === "none"
  );
}

type ModelForm = {
  name: string;
  kind: ProviderModel["kind"];
  provider: string;
  base_url: string;
  model_name: string;
  api_key: string;
  embedding_dimensions: string;
  embedding_dimension_mode: "auto" | "send" | "omit";
  timeout_seconds: string;
  max_concurrency: string;
};

const initialForm: ModelForm = {
  name: "",
  kind: "embedding",
  provider: "openai",
  base_url: presets.openai,
  model_name: "",
  api_key: "",
  embedding_dimensions: "",
  embedding_dimension_mode: "auto",
  timeout_seconds: "60",
  max_concurrency: "5",
};

const providerOptions = [
  ...Object.keys(presets).map((provider) => ({ value: provider, label: provider })),
  { value: "openai-compatible", label: "openai-compatible" },
  { value: "mock", label: "mock（仅测试）" },
];

export function ModelsPage() {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [disableReasoning, setDisableReasoning] = useState(false);
  const [editing, setEditing] = useState<ProviderModel | null>(null);
  const [editForm, setEditForm] = useState<ModelForm>(initialForm);
  const [editDisableReasoning, setEditDisableReasoning] = useState(false);
  const [clearApiKey, setClearApiKey] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, ModelTestResult>>({});
  const [form, setForm] = useState<ModelForm>(initialForm);
  const { data = [] } = useQuery({
    queryKey: ["models"],
    queryFn: () => api<ProviderModel[]>("/models"),
  });
  const create = useMutation({
    mutationFn: () =>
      api<ProviderModel>("/models", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          embedding_dimensions:
            form.kind === "embedding" && form.embedding_dimensions
              ? Number(form.embedding_dimensions)
              : null,
          timeout_seconds: Number(form.timeout_seconds),
          max_concurrency: Number(form.max_concurrency),
          config:
            form.kind === "embedding"
              ? form.embedding_dimension_mode === "auto"
                ? {}
                : {
                    embedding_send_dimensions:
                      form.embedding_dimension_mode === "send",
                  }
              : form.kind === "chat" && disableReasoning
              ? {
                  chat_extra_body: {
                    enable_thinking: false,
                    reasoning_effort: "none",
                  },
                }
              : {},
        }),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["models"] });
      setOpen(false);
      setForm(initialForm);
      setDisableReasoning(false);
    },
  });
  const update = useMutation({
    mutationFn: () => {
      if (!editing) throw new Error("没有正在编辑的模型");
      const config = { ...editing.config };
      if (editing.kind === "chat") {
        if (editDisableReasoning) {
          config.chat_extra_body = {
            enable_thinking: false,
            reasoning_effort: "none",
          };
        } else {
          delete config.chat_extra_body;
        }
      }
      if (editing.kind === "embedding") {
        if (editForm.embedding_dimension_mode === "auto") {
          delete config.embedding_send_dimensions;
        } else {
          config.embedding_send_dimensions =
            editForm.embedding_dimension_mode === "send";
        }
      }
      return api<ProviderModel>(`/models/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: editForm.name,
          provider: editForm.provider,
          base_url: editForm.base_url,
          model_name: editForm.model_name,
          api_key: editForm.api_key || null,
          clear_api_key: clearApiKey,
          timeout_seconds: Number(editForm.timeout_seconds),
          max_concurrency: Number(editForm.max_concurrency),
          embedding_dimensions:
            editing.kind === "embedding" && editForm.embedding_dimensions
              ? Number(editForm.embedding_dimensions)
              : null,
          clear_embedding_dimensions:
            editing.kind === "embedding" && !editForm.embedding_dimensions,
          config,
        }),
      });
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["models"] });
      setEditing(null);
    },
  });
  const remove = useMutation({
    mutationFn: (model: ProviderModel) =>
      api<void>(`/models/${model.id}`, { method: "DELETE" }),
    onSuccess: (_result, model) => {
      client.invalidateQueries({ queryKey: ["models"] });
      setTestResults((current) => {
        const next = { ...current };
        delete next[model.id];
        return next;
      });
      if (editing?.id === model.id) setEditing(null);
    },
  });
  const test = useMutation({
    mutationFn: (id: string) =>
      api<ModelTestResult>(`/models/${id}/test`, { method: "POST" }),
    onSuccess: (result, id) =>
      setTestResults((current) => ({ ...current, [id]: result })),
  });
  const toggle = useMutation({
    mutationFn: (model: ProviderModel) =>
      api<ProviderModel>(`/models/${model.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_enabled: !model.is_enabled }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["models"] }),
  });
  const toggleReasoningCompatibility = useMutation({
    mutationFn: (model: ProviderModel) => {
      const currentExtraBody = model.config.chat_extra_body as
        | Record<string, unknown>
        | undefined;
      const currentlyDisabled =
        currentExtraBody?.enable_thinking === false ||
        currentExtraBody?.reasoning_effort === "none";
      const config = { ...model.config };
      if (currentlyDisabled) {
        delete config.chat_extra_body;
      } else {
        config.chat_extra_body = {
          enable_thinking: false,
          reasoning_effort: "none",
        };
      }
      return api<ProviderModel>(`/models/${model.id}`, {
        method: "PATCH",
        body: JSON.stringify({ config }),
      });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["models"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  function startEditing(model: ProviderModel) {
    setOpen(false);
    setEditing(model);
    setClearApiKey(false);
    setEditDisableReasoning(hasReasoningDisabled(model));
    setEditForm({
      name: model.name,
      kind: model.kind,
      provider: model.provider,
      base_url: model.base_url,
      model_name: model.model_name,
      api_key: "",
      embedding_dimensions: String(model.embedding_dimensions ?? ""),
      embedding_dimension_mode:
        model.config.embedding_send_dimensions === true
          ? "send"
          : model.config.embedding_send_dimensions === false
            ? "omit"
            : "auto",
      timeout_seconds: String(model.timeout_seconds),
      max_concurrency: String(model.max_concurrency),
    });
  }

  function confirmDelete(model: ProviderModel) {
    if (
      window.confirm(
        `确认删除模型配置“${model.name}”？此操作不可恢复；正在被知识库、Agent 或任务使用时系统会阻止删除。`,
      )
    ) {
      remove.mutate(model);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="模型设置"
        description="Chat、Embedding、Rerank 和 OCR 分开配置。密钥加密保存且不会从 API 返回。"
        actions={
          <Button
            onClick={() => {
              setEditing(null);
              setOpen((value) => !value);
            }}
          >
            <Plus size={16} />
            添加模型
          </Button>
        }
      />
      {editing && (
        <Card className="mb-6 p-6">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <h2 className="font-semibold">编辑模型</h2>
              <p className="mt-1 text-sm text-[var(--muted)]">
                类型创建后不可修改；API Key 留空会保留当前密钥。
              </p>
            </div>
            <Button
              aria-label="关闭编辑"
              size="icon"
              variant="ghost"
              onClick={() => setEditing(null)}
            >
              <X size={17} />
            </Button>
          </div>
          <form
            className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
            onSubmit={(event) => {
              event.preventDefault();
              update.mutate();
            }}
          >
            <Input
              aria-label="配置名称"
              placeholder="配置名称"
              value={editForm.name}
              onChange={(event) =>
                setEditForm({ ...editForm, name: event.target.value })
              }
              required
            />
            <Input
              aria-label="模型类型"
              value={editing.kind}
              disabled
              title="模型类型创建后不可修改"
            />
            <Select
              ariaLabel="模型提供商"
              value={editForm.provider}
              onValueChange={(provider) =>
                setEditForm({
                  ...editForm,
                  provider,
                  base_url:
                    presetBaseUrl(provider, editing.kind) || editForm.base_url,
                })
              }
              options={providerOptions}
            />
            <Input
              aria-label="Base URL"
              placeholder="Base URL"
              value={editForm.base_url}
              onChange={(event) =>
                setEditForm({ ...editForm, base_url: event.target.value })
              }
              required
            />
            <Input
              aria-label="模型名"
              placeholder="模型名"
              value={editForm.model_name}
              onChange={(event) =>
                setEditForm({ ...editForm, model_name: event.target.value })
              }
              required
            />
            <Input
              aria-label="新 API Key"
              type="password"
              autoComplete="new-password"
              placeholder={
                editing.has_api_key ? "新 API Key（留空保留）" : "API Key"
              }
              value={editForm.api_key}
              disabled={clearApiKey}
              onChange={(event) => {
                setClearApiKey(false);
                setEditForm({ ...editForm, api_key: event.target.value });
              }}
            />
            <Input
              aria-label="请求超时秒数"
              type="number"
              min={1}
              max={600}
              placeholder="请求超时（秒）"
              value={editForm.timeout_seconds}
              onChange={(event) =>
                setEditForm({ ...editForm, timeout_seconds: event.target.value })
              }
              required
            />
            <Input
              aria-label="最大并发"
              type="number"
              min={1}
              max={100}
              placeholder="最大并发"
              value={editForm.max_concurrency}
              onChange={(event) =>
                setEditForm({ ...editForm, max_concurrency: event.target.value })
              }
              required
            />
            {editing.kind === "embedding" && (
              <>
                <Input
                  aria-label="Embedding 默认维度"
                  type="number"
                  min={1}
                  max={2000}
                  placeholder="默认维度（可留空，测试后填写）"
                  value={editForm.embedding_dimensions}
                  onChange={(event) =>
                    setEditForm({
                      ...editForm,
                      embedding_dimensions: event.target.value,
                    })
                  }
                />
                <Select
                  ariaLabel="dimensions 参数策略"
                  value={editForm.embedding_dimension_mode}
                  onValueChange={(value) =>
                    setEditForm({
                      ...editForm,
                      embedding_dimension_mode: value as ModelForm["embedding_dimension_mode"],
                    })
                  }
                  options={[
                    { value: "auto", label: "自动兼容 dimensions 参数" },
                    { value: "send", label: "始终发送 dimensions" },
                    { value: "omit", label: "从不发送 dimensions" },
                  ]}
                />
              </>
            )}
            {editing.has_api_key && (
              <label className="flex h-11 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-sm">
                <input
                  type="checkbox"
                  checked={clearApiKey}
                  onChange={(event) => {
                    setClearApiKey(event.target.checked);
                    if (event.target.checked) {
                      setEditForm({ ...editForm, api_key: "" });
                    }
                  }}
                />
                清除已保存的 API Key
              </label>
            )}
            {editing.kind === "chat" && (
              <label className="flex h-11 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-sm">
                <input
                  type="checkbox"
                  checked={editDisableReasoning}
                  onChange={(event) =>
                    setEditDisableReasoning(event.target.checked)
                  }
                />
                请求关闭推理（兼容参数）
              </label>
            )}
            <div className="flex gap-2">
              <Button disabled={update.isPending} type="submit">
                {update.isPending ? "保存中…" : "保存修改"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => setEditing(null)}
              >
                取消
              </Button>
            </div>
          </form>
          {update.error && (
            <p className="mt-3 text-sm text-red-500">{update.error.message}</p>
          )}
        </Card>
      )}
      {open && (
        <Card className="mb-6 p-6">
          <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" onSubmit={submit}>
            <Input
              placeholder="配置名称"
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
            />
            <Select
              ariaLabel="模型类型"
              value={form.kind}
              onValueChange={(kind) => {
                const modelKind = kind as ProviderModel["kind"];
                setForm({
                  ...form,
                  kind: modelKind,
                  base_url:
                    presetBaseUrl(form.provider, modelKind) || form.base_url,
                });
              }}
              options={[
                { value: "chat", label: "Chat" },
                { value: "embedding", label: "Embedding" },
                { value: "rerank", label: "Rerank" },
                { value: "ocr", label: "OCR" },
              ]}
            />
            <Select
              ariaLabel="模型提供商"
              value={form.provider}
              onValueChange={(provider) => {
                setForm({
                  ...form,
                  provider,
                  base_url: presetBaseUrl(provider, form.kind) || form.base_url,
                });
              }}
              options={providerOptions}
            />
            <Input
              placeholder="Base URL"
              value={form.base_url}
              onChange={(event) => setForm({ ...form, base_url: event.target.value })}
              required
            />
            <Input
              placeholder="模型名"
              value={form.model_name}
              onChange={(event) => setForm({ ...form, model_name: event.target.value })}
              required
            />
            <Input
              type="password"
              autoComplete="new-password"
              placeholder="API Key"
              value={form.api_key}
              onChange={(event) => setForm({ ...form, api_key: event.target.value })}
            />
            {form.kind === "embedding" && (
              <>
                <Input
                  aria-label="Embedding 默认维度"
                  type="number"
                  min={1}
                  max={2000}
                  placeholder="默认维度（可留空，测试后填写）"
                  value={form.embedding_dimensions}
                  onChange={(event) =>
                    setForm({ ...form, embedding_dimensions: event.target.value })
                  }
                />
                <Select
                  ariaLabel="dimensions 参数策略"
                  value={form.embedding_dimension_mode}
                  onValueChange={(value) =>
                    setForm({
                      ...form,
                      embedding_dimension_mode: value as ModelForm["embedding_dimension_mode"],
                    })
                  }
                  options={[
                    { value: "auto", label: "自动兼容（推荐）" },
                    { value: "send", label: "始终发送 dimensions" },
                    { value: "omit", label: "从不发送 dimensions" },
                  ]}
                />
              </>
            )}
            <Input
              type="number"
              min={1}
              max={600}
              placeholder="请求超时（秒）"
              value={form.timeout_seconds}
              onChange={(event) =>
                setForm({ ...form, timeout_seconds: event.target.value })
              }
              required
            />
            <Input
              type="number"
              min={1}
              max={100}
              placeholder="最大并发"
              value={form.max_concurrency}
              onChange={(event) =>
                setForm({ ...form, max_concurrency: event.target.value })
              }
              required
            />
            {form.kind === "chat" && (
              <label className="flex h-11 items-center gap-2 rounded-xl border border-[var(--border)] px-3 text-sm">
                <input
                  type="checkbox"
                  checked={disableReasoning}
                  onChange={(event) => setDisableReasoning(event.target.checked)}
                />
                请求关闭推理（兼容参数）
              </label>
            )}
            <Button disabled={create.isPending} type="submit">
              保存模型
            </Button>
          </form>
          {create.error && (
            <p className="mt-3 text-sm text-red-500">{create.error.message}</p>
          )}
        </Card>
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.map((model) => (
          <Card key={model.id} className="p-5">
            <div className="flex items-start justify-between">
              <div className="rounded-xl bg-cyan-500/10 p-2.5 text-cyan-500">
                <ServerCog size={18} />
              </div>
              <span className="rounded-full bg-[var(--surface-hover)] px-2.5 py-1 text-xs">
                {model.kind}
              </span>
            </div>
            <h2 className="mt-7 font-semibold">{model.name}</h2>
            <div className="mt-3 space-y-1 text-xs text-[var(--muted)]">
              <p>
                {model.provider} · {model.model_name}
              </p>
              <p>密钥：{model.has_api_key ? "已安全保存" : "未配置"}</p>
              {model.embedding_dimensions && <p>维度：{model.embedding_dimensions}</p>}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={test.isPending}
                onClick={() => test.mutate(model.id)}
              >
                连接测试
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={toggle.isPending}
                onClick={() => toggle.mutate(model)}
              >
                {model.is_enabled ? "停用" : "启用"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => startEditing(model)}
              >
                <Pencil size={14} />
                编辑
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-red-500 hover:bg-red-500/10 hover:text-red-600"
                disabled={remove.isPending}
                onClick={() => confirmDelete(model)}
              >
                <Trash2 size={14} />
                删除
              </Button>
              {model.kind === "chat" && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={toggleReasoningCompatibility.isPending}
                  onClick={() => toggleReasoningCompatibility.mutate(model)}
                >
                  {hasReasoningDisabled(model)
                    ? "移除关闭推理参数"
                    : "请求关闭推理"}
                </Button>
              )}
            </div>
            {model.kind === "chat" && (
              <p className="mt-2 text-xs text-[var(--muted)]">
                结构化 JSON：
                {hasReasoningDisabled(model)
                  ? "发送 enable_thinking=false 与 reasoning_effort=none；是否生效以连接测试为准"
                  : "使用模型/网关默认推理策略"}
              </p>
            )}
            {testResults[model.id] && (
              <div
                className={`mt-3 space-y-1 text-xs ${
                  testResults[model.id].ok ? "text-emerald-500" : "text-red-500"
                }`}
              >
                <p>
                  {testResults[model.id].ok ? "测试通过" : "测试失败"} ·{" "}
                  {testResults[model.id].latency_ms} ms
                </p>
                {typeof testResults[model.id].details.message_zh === "string" && (
                  <p>{String(testResults[model.id].details.message_zh)}</p>
                )}
                {typeof testResults[model.id].details.message === "string" && (
                  <p>{String(testResults[model.id].details.message)}</p>
                )}
                {typeof testResults[model.id].details.http_status === "number" && (
                  <p className="text-[var(--muted)]">
                    HTTP {String(testResults[model.id].details.http_status)}
                    {testResults[model.id].details.provider_code
                      ? ` · 厂商错误码 ${String(testResults[model.id].details.provider_code)}`
                      : ""}
                  </p>
                )}
                {typeof testResults[model.id].details.endpoint === "string" && (
                  <p className="break-all text-[var(--muted)]">
                    请求地址：{String(testResults[model.id].details.endpoint)}
                  </p>
                )}
                {typeof testResults[model.id].details.provider_request_id ===
                  "string" && (
                  <p className="break-all text-[var(--muted)]">
                    厂商 Request ID：
                    {String(testResults[model.id].details.provider_request_id)}
                  </p>
                )}
                {typeof testResults[model.id].details.embedding_dimensions ===
                  "number" && (
                  <p className="text-[var(--muted)]">
                    实际维度：
                    {String(testResults[model.id].details.embedding_dimensions)}
                  </p>
                )}
                {typeof testResults[model.id].details.reasoning_tokens === "number" && (
                  <p className="text-[var(--muted)]">
                    reasoning tokens：
                    {String(testResults[model.id].details.reasoning_tokens)}
                  </p>
                )}
                {typeof testResults[model.id].details.warning === "string" && (
                  <p className="text-amber-500">
                    {String(testResults[model.id].details.warning)}
                  </p>
                )}
              </div>
            )}
            {test.error && test.variables === model.id && (
              <p className="mt-3 text-xs text-red-500">{test.error.message}</p>
            )}
            {remove.error && remove.variables?.id === model.id && (
              <p className="mt-3 text-xs text-red-500">{remove.error.message}</p>
            )}
          </Card>
        ))}
      </div>
    </>
  );
}
