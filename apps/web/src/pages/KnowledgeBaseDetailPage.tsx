import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, FileUp, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { DateTimePicker } from "../components/ui/date-time-picker";
import { Select } from "../components/ui/select";
import { Input } from "../components/ui/input";
import { api, download } from "../lib/api";
import type { Document, KnowledgeBase, ProviderModel } from "../lib/types";
import { useAuthStore } from "../stores/auth";

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function KnowledgeBaseDetailPage() {
  const { id = "" } = useParams();
  const user = useAuthStore((state) => state.user);
  const input = useRef<HTMLInputElement>(null);
  const client = useQueryClient();
  const [sourceTime, setSourceTime] = useState("");
  const [importUrl, setImportUrl] = useState("");
  const emptyFilters = { name: "", status: "", created_from: "", created_to: "", source_from: "", source_to: "", include_unknown: false };
  const [filterDraft, setFilterDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const documentParams = new URLSearchParams({ knowledge_base_id: id });
  if (filters.name) documentParams.set("name", filters.name);
  if (filters.status) documentParams.set("status", filters.status);
  for (const field of ["created_from", "created_to", "source_from", "source_to"] as const) {
    if (filters[field]) documentParams.set(field, new Date(filters[field]).toISOString());
  }
  if (filters.include_unknown) documentParams.set("include_unknown", "true");
  const filterQuery = documentParams.toString();
  const [wikiNodeTypes, setWikiNodeTypes] = useState("");
  const [wikiGenerationPrompt, setWikiGenerationPrompt] = useState("");
  const [embeddingModelId, setEmbeddingModelId] = useState("");
  const [ragChatModelId, setRagChatModelId] = useState("");
  const [sourceTimeChatModelId, setSourceTimeChatModelId] = useState("");
  const [rerankModelId, setRerankModelId] = useState("");
  const [ragMaxOutputTokens, setRagMaxOutputTokens] = useState(8000);
  const [wikiChatModelId, setWikiChatModelId] = useState("");
  const [wikiHealthChatModelId, setWikiHealthChatModelId] = useState("");
  const [wikiHealthCheckEnabled, setWikiHealthCheckEnabled] = useState(true);
  const [wikiHealthIntervalHours, setWikiHealthIntervalHours] = useState(24);
  const [documentPage, setDocumentPage] = useState(1);
  const documentPageSize = 50;
  const { data: knowledgeBase } = useQuery({
    queryKey: ["knowledge-base", id],
    queryFn: () => api<KnowledgeBase>(`/knowledge-bases/${id}`),
    enabled: Boolean(id),
  });
  const { data: documents = [], refetch, error: documentsError } = useQuery({
    queryKey: ["documents", id, filterQuery, documentPage],
    queryFn: () => api<Document[]>(`/documents?${filterQuery}&limit=${documentPageSize}&offset=${(documentPage - 1) * documentPageSize}`),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data?.some((document) =>
        ["queued", "processing", "uploaded"].includes(document.status),
      )
        ? 3000
        : false,
  });
  const { data: documentCount = { count: 0 } } = useQuery({
    queryKey: ["document-count", id, filterQuery],
    queryFn: () => api<{ count: number }>(`/documents/count?${filterQuery}`),
    enabled: Boolean(id),
  });
  const { data: models = [] } = useQuery({
    queryKey: ["models"],
    queryFn: () => api<ProviderModel[]>("/models"),
    enabled: Boolean(user && ["admin", "super_admin"].includes(user.role)),
  });
  useEffect(() => {
    if (!knowledgeBase) return;
    setWikiNodeTypes(knowledgeBase.wiki_node_types.join(", "));
    setWikiGenerationPrompt(knowledgeBase.wiki_generation_prompt);
    setEmbeddingModelId(knowledgeBase.embedding_model_id ?? "");
    setRagChatModelId(knowledgeBase.rag_chat_model_id ?? "");
    setSourceTimeChatModelId(knowledgeBase.source_time_chat_model_id ?? "");
    setRerankModelId(knowledgeBase.rerank_model_id ?? "");
    setRagMaxOutputTokens(knowledgeBase.rag_max_output_tokens);
    setWikiChatModelId(knowledgeBase.wiki_chat_model_id ?? "");
    setWikiHealthChatModelId(knowledgeBase.wiki_health_chat_model_id ?? "");
    setWikiHealthCheckEnabled(knowledgeBase.wiki_health_check_enabled);
    setWikiHealthIntervalHours(knowledgeBase.wiki_health_check_interval_hours);
  }, [knowledgeBase]);
  const saveWikiConfig = useMutation({
    mutationFn: () =>
      api<KnowledgeBase>(`/knowledge-bases/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          wiki_node_types: wikiNodeTypes
            .split(/[,，]/)
            .map((item) => item.trim())
            .filter(Boolean),
          wiki_generation_prompt: wikiGenerationPrompt,
          embedding_model_id: embeddingModelId || null,
          embedding_dimensions: knowledgeBase?.embedding_dimensions,
          rag_chat_model_id: ragChatModelId || null,
          source_time_chat_model_id: sourceTimeChatModelId || null,
          rerank_model_id: rerankModelId || null,
          rag_max_output_tokens: ragMaxOutputTokens,
          wiki_chat_model_id: wikiChatModelId || null,
          wiki_health_chat_model_id: wikiHealthChatModelId || null,
          wiki_health_check_enabled: wikiHealthCheckEnabled,
          wiki_health_check_interval_hours: wikiHealthIntervalHours,
        }),
      }),
    onSuccess: (updated) => {
      client.setQueryData(["knowledge-base", id], updated);
      client.invalidateQueries({ queryKey: ["knowledge-bases"] });
    },
  });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("knowledge_base_id", id);
      body.append("file", file);
      if (sourceTime) body.append("source_time", new Date(sourceTime).toISOString());
      return api<Document>("/documents/upload", { method: "POST", body });
    },
    onSuccess: () => {
      setDocumentPage(1);
      client.invalidateQueries({ queryKey: ["documents", id] });
      client.invalidateQueries({ queryKey: ["document-count", id] });
      if (input.current) input.current.value = "";
    },
  });
  const fileDownload = useMutation({
    mutationFn: (document: Document) =>
      download(`/documents/${document.id}/download`, document.filename),
  });
  const importWebpage = useMutation({
    mutationFn: () => api<Document>("/documents/import-url", {
      method: "POST", body: JSON.stringify({ knowledge_base_id: id, url: importUrl.trim(), source_time: sourceTime ? new Date(sourceTime).toISOString() : null }),
    }),
    onSuccess: () => {
      setImportUrl(""); setDocumentPage(1);
      client.invalidateQueries({ queryKey: ["documents", id] });
      client.invalidateQueries({ queryKey: ["document-count", id] });
    },
  });

  return (
    <>
      <PageHeader
        eyebrow="Knowledge Base"
        title={knowledgeBase?.name ?? "知识库"}
        description={knowledgeBase?.description}
        actions={
          Boolean(user && ["admin", "super_admin"].includes(user.role)) ? (
            <div className="flex items-center gap-2">
              <div className="w-56 text-xs text-[var(--muted)]">
                <DateTimePicker
                  ariaLabel="来源时间"
                  value={sourceTime}
                  onValueChange={setSourceTime}
                  placeholder="来源时间（留空自动识别）"
                />
              </div>
              <input
                ref={input}
                className="hidden"
                type="file"
                accept=".pdf,.docx,.xlsx,.pptx,.md,.txt,.html,.png,.jpg,.jpeg,.tif,.tiff"
                multiple
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  void (async () => {
                    for (const file of files) await upload.mutateAsync(file);
                  })();
                }}
              />
              <Button onClick={() => input.current?.click()} disabled={upload.isPending}>
                <FileUp size={16} />
                {upload.isPending ? "上传中…" : "上传文档"}
              </Button>
            </div>
          ) : undefined
        }
      />
      {upload.error && (
        <p role="alert" className="mb-4 rounded-xl bg-red-500/10 p-3 text-sm text-red-500">
          {upload.error.message}
        </p>
      )}
      {Boolean(user && ["admin", "super_admin"].includes(user.role)) && <Card className="mb-5 p-5">
        <form className="flex flex-wrap gap-3" onSubmit={(event) => { event.preventDefault(); importWebpage.mutate(); }}>
          <Input className="min-w-60 flex-1" aria-label="网页链接" type="url" placeholder="粘贴网页或微信公众号文章链接" required value={importUrl} onChange={(event) => setImportUrl(event.target.value)} />
          <Button type="submit" disabled={importWebpage.isPending}>{importWebpage.isPending ? "正在读取…" : "导入链接"}</Button>
        </form>
        <p className="mt-2 text-xs text-[var(--muted)]">导入后自动解析与索引；需要微信验证的文章可保存正文为 HTML/Markdown 后上传。来源时间可使用上方选择器指定。</p>
        {importWebpage.error && <p role="alert" className="mt-3 text-sm text-red-500">{importWebpage.error.message}</p>}
        {importWebpage.isSuccess && <p role="status" className="mt-3 text-sm text-emerald-600">文章已导入，正在排队处理。</p>}
      </Card>}
      {Boolean(user && ["admin", "super_admin"].includes(user.role)) && knowledgeBase?.wiki_enabled && (
        <Card className="mb-5 p-5">
          <div>
            <h2 className="font-semibold">模块模型与 Wiki 配置</h2>
            <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
              Embedding 模型与维度在创建知识库时锁定；日期抽取、问答、Wiki 生成和 Wiki 健康检查可独立选择模型。
            </p>
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">Embedding</span>
              <Select
                ariaLabel="Embedding 模型"
                value={embeddingModelId}
                onValueChange={setEmbeddingModelId}
                placeholder="请选择"
                options={models
                  .filter((model) => model.kind === "embedding" && model.is_enabled)
                  .map((model) => ({ value: model.id, label: model.name, description: model.model_name }))}
                disabled
              />
              <span className="mt-1 block text-xs text-[var(--muted)]">
                已锁定为 {knowledgeBase.embedding_dimensions} 维
              </span>
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">RAG 问答 Chat</span>
              <Select
                ariaLabel="RAG 问答 Chat 模型"
                value={ragChatModelId}
                onValueChange={setRagChatModelId}
                placeholder="请选择"
                options={models
                  .filter((model) => model.kind === "chat" && model.is_enabled)
                  .map((model) => ({ value: model.id, label: model.name, description: model.model_name }))}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">日期抽取 Chat</span>
              <Select
                ariaLabel="日期抽取 Chat 模型"
                value={sourceTimeChatModelId}
                onValueChange={setSourceTimeChatModelId}
                placeholder="不使用模型（规则提取）"
                clearable
                clearLabel="不使用模型（规则提取）"
                options={models
                  .filter((model) => model.kind === "chat" && model.is_enabled)
                  .map((model) => ({ value: model.id, label: model.name, description: model.model_name }))}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">Rerank</span>
              <Select
                ariaLabel="Rerank 模型"
                value={rerankModelId}
                onValueChange={setRerankModelId}
                placeholder="不使用 Rerank"
                clearable
                clearLabel="不使用 Rerank"
                options={models
                  .filter((model) => model.kind === "rerank" && model.is_enabled)
                  .map((model) => ({ value: model.id, label: model.name, description: model.model_name }))}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">Wiki 生成 Chat</span>
              <Select
                ariaLabel="Wiki 生成 Chat 模型"
                value={wikiChatModelId}
                onValueChange={setWikiChatModelId}
                placeholder="请选择"
                options={models
                  .filter((model) => model.kind === "chat" && model.is_enabled)
                  .map((model) => ({
                    value: model.id,
                    label: model.name,
                    description: model.model_name,
                  }))}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">Wiki 健康检查 Chat</span>
              <Select
                ariaLabel="Wiki 健康检查 Chat 模型"
                value={wikiHealthChatModelId}
                onValueChange={setWikiHealthChatModelId}
                placeholder="请选择"
                options={models
                  .filter((model) => model.kind === "chat" && model.is_enabled)
                  .map((model) => ({ value: model.id, label: model.name, description: model.model_name }))}
              />
            </label>
          </div>
          <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_1fr_2fr_auto_auto] lg:items-end">
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">RAG 输出上限</span>
              <input
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3"
                type="number"
                min={1000}
                max={32000}
                step={1000}
                value={ragMaxOutputTokens}
                onChange={(event) => setRagMaxOutputTokens(Number(event.target.value))}
              />
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">Wiki 节点类型</span>
              <input
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
                value={wikiNodeTypes}
                onChange={(event) => setWikiNodeTypes(event.target.value)}
                placeholder="产业主题, 个股"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">节点抽取提示词</span>
              <textarea
                className="min-h-20 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm"
                value={wikiGenerationPrompt}
                onChange={(event) => setWikiGenerationPrompt(event.target.value)}
                placeholder="描述该知识库如何识别节点、命名节点和判断关系。"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1.5 block font-medium">健康检查</span>
              <span className="flex h-11 items-center gap-2 rounded-xl border border-[var(--border)] px-3">
                <input
                  type="checkbox"
                  checked={wikiHealthCheckEnabled}
                  onChange={(event) => setWikiHealthCheckEnabled(event.target.checked)}
                />
                定期执行
              </span>
            </label>
            <label className="w-28 text-sm">
              <span className="mb-1.5 block font-medium">间隔（小时）</span>
              <input
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3"
                type="number"
                min={1}
                max={720}
                value={wikiHealthIntervalHours}
                onChange={(event) => setWikiHealthIntervalHours(Number(event.target.value))}
              />
            </label>
            <Button
              variant="secondary"
              disabled={
                saveWikiConfig.isPending ||
                !wikiNodeTypes.trim() ||
                !embeddingModelId ||
                !ragChatModelId ||
                !wikiChatModelId ||
                !wikiHealthChatModelId
              }
              onClick={() => saveWikiConfig.mutate()}
            >
              保存模块配置
            </Button>
          </div>
          {saveWikiConfig.isSuccess && (
            <p className="mt-3 text-xs text-emerald-500">模块模型与 Wiki 配置已保存</p>
          )}
          {saveWikiConfig.error && (
            <p className="mt-3 text-xs text-red-500">{saveWikiConfig.error.message}</p>
          )}
        </Card>
      )}
      <Card className="overflow-hidden">
        <form className="border-b border-[var(--border)] p-5" onSubmit={(event) => { event.preventDefault(); setFilters(filterDraft); setDocumentPage(1); }}>
          <div className="grid items-end gap-3 md:grid-cols-2 xl:grid-cols-3">
            <label className="text-sm">文档名称<Input className="mt-2" aria-label="文档名称筛选" placeholder="搜索标题" value={filterDraft.name} onChange={(event) => setFilterDraft({ ...filterDraft, name: event.target.value })} /></label>
            <div className="text-sm"><p className="mb-2">处理状态</p><Select ariaLabel="文档状态" value={filterDraft.status} onValueChange={(status) => setFilterDraft({ ...filterDraft, status })} placeholder="全部状态" clearable options={[{ value: "ready", label: "可检索" }, { value: "queued", label: "排队中" }, { value: "processing", label: "处理中" }, { value: "failed", label: "失败" }, { value: "cancelled", label: "已取消" }]} /></div>
            {([{ key: "created_from", label: "上传时间 · 从" }, { key: "created_to", label: "上传时间 · 到" }, { key: "source_from", label: "来源时间 · 从" }, { key: "source_to", label: "来源时间 · 到" }] as const).map(({ key, label }) => <div key={key} className="text-sm"><p className="mb-2">{label}</p><DateTimePicker ariaLabel={label} value={filterDraft[key]} onValueChange={(value) => setFilterDraft({ ...filterDraft, [key]: value })} placeholder="不限" /></div>)}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <label className="mr-auto flex items-center gap-2 text-sm text-[var(--muted)]"><input type="checkbox" checked={filterDraft.include_unknown} onChange={(event) => setFilterDraft({ ...filterDraft, include_unknown: event.target.checked })} />来源时间筛选包含未知日期</label>
            <Button type="button" variant="ghost" onClick={() => { setFilterDraft(emptyFilters); setFilters(emptyFilters); setDocumentPage(1); }}>重置</Button>
            <Button type="submit">筛选文档</Button>
          </div>
          {documentsError && <p role="alert" className="mt-3 text-sm text-red-500">{documentsError.message}</p>}
        </form>
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
          <div>
            <h2 className="font-semibold">文档</h2>
            <p className="mt-1 text-xs text-[var(--muted)]">共 {documentCount.count} 个文件 · 第 {documentPage} 页</p>
          </div>
          <Button variant="ghost" size="icon" onClick={() => refetch()}>
            <RefreshCw size={16} />
          </Button>
        </div>
        <div className="divide-y divide-[var(--border)]">
          {documents.length === 0 ? (
            <div className="px-5 py-16 text-center text-sm text-[var(--muted)]">
              没有符合条件的文档。可以调整筛选条件或上传新文档。
            </div>
          ) : (
            documents.map((document) => (
              <div
                key={document.id}
                className="grid gap-3 px-5 py-4 sm:grid-cols-[1fr_auto_auto] sm:items-center"
              >
                <div className="min-w-0">
                  <Link
                    className="truncate text-sm font-medium hover:text-violet-500"
                    to={`/documents/${document.id}`}
                  >
                    {document.title}
                  </Link>
                  <div className="mt-1 flex flex-wrap gap-3 text-xs text-[var(--muted)]">
                    <span>{formatBytes(document.size_bytes)}</span>
                    <span>上传时间：{new Date(document.created_at).toLocaleString("zh-CN")}</span>
                    <span>
                      source_time：
                      {document.source_time
                        ? new Date(document.source_time).toLocaleString("zh-CN")
                        : "未知"}
                    </span>
                  </div>
                  {document.error_summary && (
                    <p className="mt-2 text-xs text-red-500">{document.error_summary}</p>
                  )}
                </div>
                <StatusPill status={document.status} />
                <button
                  type="button"
                  className="text-xs font-medium text-violet-500"
                  onClick={() => fileDownload.mutate(document)}
                >
                  下载原文
                </button>
              </div>
            ))
          )}
        </div>
        {documentCount.count > documentPageSize && (
          <div className="flex items-center justify-between border-t border-[var(--border)] px-5 py-3">
            <Button
              aria-label="上一页文档"
              size="sm"
              variant="ghost"
              disabled={documentPage === 1}
              onClick={() => setDocumentPage((page) => Math.max(1, page - 1))}
            >
              <ChevronLeft size={15} />
              上一页
            </Button>
            <span className="text-xs tabular-nums text-[var(--muted)]">
              {documentPage} / {Math.ceil(documentCount.count / documentPageSize)}
            </span>
            <Button
              aria-label="下一页文档"
              size="sm"
              variant="ghost"
              disabled={documentPage >= Math.ceil(documentCount.count / documentPageSize)}
              onClick={() => setDocumentPage((page) => page + 1)}
            >
              下一页
              <ChevronRight size={15} />
            </Button>
          </div>
        )}
      </Card>
    </>
  );
}
