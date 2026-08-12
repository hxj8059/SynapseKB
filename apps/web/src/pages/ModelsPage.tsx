import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, ServerCog } from "lucide-react";
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

export function ModelsPage() {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [disableReasoning, setDisableReasoning] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, ModelTestResult>>({});
  const [form, setForm] = useState({
    name: "",
    kind: "embedding",
    provider: "openai",
    base_url: presets.openai,
    model_name: "",
    api_key: "",
    embedding_dimensions: "1536",
  });
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
            form.kind === "embedding" ? Number(form.embedding_dimensions) : null,
          timeout_seconds: 60,
          max_concurrency: 5,
          config:
            form.kind === "chat" && disableReasoning
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

  return (
    <>
      <PageHeader
        eyebrow="Administration"
        title="模型设置"
        description="Chat、Embedding、Rerank 和 OCR 分开配置。密钥加密保存且不会从 API 返回。"
        actions={
          <Button onClick={() => setOpen((value) => !value)}>
            <Plus size={16} />
            添加模型
          </Button>
        }
      />
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
                setForm({
                  ...form,
                  kind,
                  base_url: presetBaseUrl(form.provider, kind) || form.base_url,
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
              options={[
                ...Object.keys(presets).map((provider) => ({
                  value: provider,
                  label: provider,
                })),
                { value: "openai-compatible", label: "openai-compatible" },
                { value: "mock", label: "mock（仅测试）" },
              ]}
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
              <Input
                type="number"
                placeholder="Embedding 维度"
                value={form.embedding_dimensions}
                onChange={(event) =>
                  setForm({ ...form, embedding_dimensions: event.target.value })
                }
              />
            )}
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
            <div className="mt-4 flex gap-2">
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
          </Card>
        ))}
      </div>
    </>
  );
}
