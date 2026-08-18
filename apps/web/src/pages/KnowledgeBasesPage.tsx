import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, LibraryBig, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { MultiSelect, Select } from "../components/ui/select";
import { api } from "../lib/api";
import type { KnowledgeBase, ProviderModel, User } from "../lib/types";
import { useAuthStore } from "../stores/auth";

export function KnowledgeBasesPage() {
  const user = useAuthStore((state) => state.user);
  const client = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [embeddingModelId, setEmbeddingModelId] = useState("");
  const [embeddingDimensions, setEmbeddingDimensions] = useState("");
  const [ragChatModelId, setRagChatModelId] = useState("");
  const [rerankModelId, setRerankModelId] = useState("");
  const [wikiChatModelId, setWikiChatModelId] = useState("");
  const [wikiHealthChatModelId, setWikiHealthChatModelId] = useState("");
  const [visibility, setVisibility] = useState<"all" | "users">("all");
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [wikiNodeTypes, setWikiNodeTypes] = useState("产业主题, 个股");
  const [wikiGenerationPrompt, setWikiGenerationPrompt] = useState("");
  const { data = [], isLoading } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api<KnowledgeBase[]>("/knowledge-bases"),
  });
  const { data: models = [] } = useQuery({
    queryKey: ["models"],
    queryFn: () => api<ProviderModel[]>("/models"),
    enabled: user?.role === "admin",
  });
  const { data: users = [] } = useQuery({
    queryKey: ["users"],
    queryFn: () => api<User[]>("/users"),
    enabled: user?.role === "admin",
  });
  const create = useMutation({
    mutationFn: () =>
      api<KnowledgeBase>("/knowledge-bases", {
        method: "POST",
        body: JSON.stringify({
          name,
          description,
          visibility,
          member_ids: visibility === "users" ? memberIds : [],
          embedding_model_id: embeddingModelId || null,
          embedding_dimensions: Number(embeddingDimensions),
          rag_chat_model_id: ragChatModelId || null,
          rerank_model_id: rerankModelId || null,
          rag_max_output_tokens: 8000,
          wiki_chat_model_id: wikiChatModelId || null,
          wiki_health_chat_model_id: wikiHealthChatModelId || null,
          wiki_enabled: true,
          wiki_node_types: wikiNodeTypes
            .split(/[,，]/)
            .map((item) => item.trim())
            .filter(Boolean),
          wiki_generation_prompt: wikiGenerationPrompt,
        }),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["knowledge-bases"] });
      setName("");
      setDescription("");
      setEmbeddingModelId("");
      setEmbeddingDimensions("");
      setRagChatModelId("");
      setRerankModelId("");
      setWikiChatModelId("");
      setWikiHealthChatModelId("");
      setVisibility("all");
      setMemberIds([]);
      setWikiNodeTypes("产业主题, 个股");
      setWikiGenerationPrompt("");
      setCreating(false);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <>
      <PageHeader
        eyebrow="Knowledge Bases"
        title="知识库"
        description="文档、时间和授权的边界。每个知识库拥有独立的检索范围与 Wiki。"
        actions={
          user?.role === "admin" ? (
            <Button onClick={() => setCreating((value) => !value)}>
              <Plus size={16} />
              新建知识库
            </Button>
          ) : undefined
        }
      />
      {creating && (
        <Card className="mb-6 p-6">
          <form className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" onSubmit={submit}>
            <Input
              aria-label="知识库名称"
              placeholder="知识库名称"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
            <Input
              aria-label="知识库描述"
              placeholder="一句话描述"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            <Select
              ariaLabel="Embedding 模型"
              value={embeddingModelId}
              onValueChange={(modelId) => {
                setEmbeddingModelId(modelId);
                const selected = models.find((model) => model.id === modelId);
                setEmbeddingDimensions(
                  selected?.embedding_dimensions
                    ? String(selected.embedding_dimensions)
                    : "",
                );
              }}
              placeholder="选择 Embedding 模型"
              options={models
                .filter((model) => model.kind === "embedding" && model.is_enabled)
                .map((model) => ({
                  value: model.id,
                  label: model.name,
                  description: `${model.model_name}${model.embedding_dimensions ? ` · 默认 ${model.embedding_dimensions} 维` : ""}`,
                }))}
            />
            <Input
              aria-label="Embedding 维度"
              type="number"
              min={1}
              max={2000}
              placeholder="Embedding 维度（创建后锁定）"
              value={embeddingDimensions}
              onChange={(event) => setEmbeddingDimensions(event.target.value)}
              required
            />
            <Select
              ariaLabel="RAG 问答 Chat 模型"
              value={ragChatModelId}
              onValueChange={setRagChatModelId}
              placeholder="选择 RAG 问答模型"
              options={models
                .filter((model) => model.kind === "chat" && model.is_enabled)
                .map((model) => ({
                  value: model.id,
                  label: model.name,
                  description: model.model_name,
                }))}
            />
            <Select
              ariaLabel="Rerank 模型"
              value={rerankModelId}
              onValueChange={setRerankModelId}
              placeholder="不使用 Rerank（可选）"
              clearable
              options={models
                .filter((model) => model.kind === "rerank" && model.is_enabled)
                .map((model) => ({
                  value: model.id,
                  label: model.name,
                  description: model.model_name,
                }))}
            />
            <Select
              ariaLabel="Wiki 生成 Chat 模型"
              value={wikiChatModelId}
              onValueChange={setWikiChatModelId}
              placeholder="选择 Wiki 生成模型"
              options={models
                .filter((model) => model.kind === "chat" && model.is_enabled)
                .map((model) => ({
                  value: model.id,
                  label: model.name,
                  description: model.model_name,
                }))}
            />
            <Select
              ariaLabel="Wiki 健康检查 Chat 模型"
              value={wikiHealthChatModelId}
              onValueChange={setWikiHealthChatModelId}
              placeholder="选择 Wiki 维护模型"
              options={models
                .filter((model) => model.kind === "chat" && model.is_enabled)
                .map((model) => ({
                  value: model.id,
                  label: model.name,
                  description: model.model_name,
                }))}
            />
            <Select
              ariaLabel="可见范围"
              value={visibility}
              onValueChange={(value) =>
                setVisibility(value as "all" | "users")
              }
              options={[
                { value: "all", label: "所有用户可用" },
                { value: "users", label: "指定用户可用" },
              ]}
            />
            {visibility === "users" && (
              <MultiSelect
                ariaLabel="授权用户"
                value={memberIds}
                onValueChange={setMemberIds}
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
            <label className="md:col-span-2 xl:col-span-3">
              <span className="mb-1.5 block text-xs font-medium text-[var(--muted)]">
                Wiki 节点类型（逗号分隔）
              </span>
              <Input
                aria-label="Wiki 节点类型"
                placeholder="产业主题, 个股"
                value={wikiNodeTypes}
                onChange={(event) => setWikiNodeTypes(event.target.value)}
                required
              />
            </label>
            <label className="md:col-span-2 xl:col-span-3">
              <span className="mb-1.5 block text-xs font-medium text-[var(--muted)]">
                Wiki 节点抽取提示词（可选）
              </span>
              <textarea
                aria-label="Wiki 节点抽取提示词"
                className="min-h-28 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none focus:border-violet-500"
                placeholder="例如：个股节点使用证券简称；产品节点区分芯片、软件和云服务。"
                value={wikiGenerationPrompt}
                onChange={(event) => setWikiGenerationPrompt(event.target.value)}
              />
            </label>
            <Button
              disabled={
                create.isPending ||
                !embeddingModelId ||
                !embeddingDimensions ||
                !ragChatModelId ||
                !wikiChatModelId ||
                !wikiHealthChatModelId ||
                wikiNodeTypes.trim().length === 0 ||
                (visibility === "users" && memberIds.length === 0)
              }
            >
              创建
            </Button>
          </form>
          {create.error && (
            <p className="mt-3 text-sm text-red-500">{create.error.message}</p>
          )}
        </Card>
      )}
      {isLoading ? (
        <p className="text-sm text-[var(--muted)]">正在读取知识库…</p>
      ) : data.length === 0 ? (
        <Card className="flex min-h-64 flex-col items-center justify-center p-8 text-center">
          <LibraryBig className="mb-4 text-violet-500" />
          <h2 className="font-semibold">还没有可访问的知识库</h2>
          <p className="mt-2 text-sm text-[var(--muted)]">
            管理员创建并授权后，这里会显示真实知识库。
          </p>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.map((knowledgeBase) => (
            <Link key={knowledgeBase.id} to={`/knowledge-bases/${knowledgeBase.id}`}>
              <Card className="group h-full p-6 transition hover:-translate-y-0.5 hover:border-violet-400/50">
                <div className="flex items-start justify-between">
                  <div className="rounded-xl bg-violet-500/10 p-2.5 text-violet-500">
                    <LibraryBig size={19} />
                  </div>
                  <ArrowUpRight className="text-[var(--muted)]" size={17} />
                </div>
                <h2 className="mt-8 text-lg font-semibold">{knowledgeBase.name}</h2>
                <p className="mt-2 min-h-12 text-sm leading-6 text-[var(--muted)]">
                  {knowledgeBase.description || "暂无描述"}
                </p>
                <div className="mt-5 flex gap-2 text-xs text-[var(--muted)]">
                  <span className="rounded-full bg-[var(--surface-hover)] px-2.5 py-1">
                    {knowledgeBase.visibility === "all" ? "所有用户" : "指定用户"}
                  </span>
                  {knowledgeBase.wiki_enabled && (
                    <span className="rounded-full bg-[var(--surface-hover)] px-2.5 py-1">
                      Wiki
                    </span>
                  )}
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
