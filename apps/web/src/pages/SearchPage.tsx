import { useMutation, useQuery } from "@tanstack/react-query";
import { CalendarRange, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { DateTimePicker } from "../components/ui/date-time-picker";
import { Input } from "../components/ui/input";
import { MultiSelect, Select } from "../components/ui/select";
import { api } from "../lib/api";
import type { KnowledgeBase, SearchCitation } from "../lib/types";

type SearchResponse = {
  query: string;
  results: SearchCitation[];
};

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [knowledgeBaseIds, setKnowledgeBaseIds] = useState<string[]>([]);
  const [field, setField] = useState("source_time");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [includeUnknown, setIncludeUnknown] = useState(false);
  const { data: knowledgeBases = [] } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api<KnowledgeBase[]>("/knowledge-bases"),
  });
  const search = useMutation({
    mutationFn: () =>
      api<SearchResponse>("/search", {
        method: "POST",
        body: JSON.stringify({
          query,
          knowledge_base_ids: knowledgeBaseIds,
          document_ids: [],
          tag_ids: [],
          time_filter:
            from || to
              ? {
                  field,
                  from: from ? new Date(from).toISOString() : null,
                  to: to ? new Date(to).toISOString() : null,
                  include_unknown: includeUnknown,
                }
              : null,
          top_k: 20,
        }),
      }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    search.mutate();
  }

  return (
    <>
      <PageHeader
        eyebrow="Temporal Retrieval"
        title="知识检索"
        description="时间条件直接进入向量与关键词候选查询。这里不会先召回全库再丢弃不符合时间的结果。"
      />
      <Card className="p-5 sm:p-6">
        <form onSubmit={submit}>
          <div className="flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 shadow-[0_10px_35px_rgba(30,25,55,.05)] focus-within:border-violet-400/50 focus-within:ring-2 focus-within:ring-violet-500/10">
            <Input
              className="border-0 bg-transparent shadow-none focus:ring-0"
              aria-label="查询内容"
              placeholder="例如：只看 2024 年的政策变化"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              required
            />
            <Button
              type="submit"
              aria-label="执行知识检索"
              disabled={search.isPending || knowledgeBaseIds.length === 0}
            >
              <Search size={16} />
              {search.isPending ? "检索中…" : "检索"}
            </Button>
          </div>
          <div className="mt-5 grid gap-4 border-t border-[var(--border)] pt-5 lg:grid-cols-[1.3fr_.7fr_1fr_1fr_auto]">
            <label className="text-xs text-[var(--muted)]">
              <span className="mb-2 block">知识库范围</span>
              <MultiSelect
                ariaLabel="知识库范围"
                className="h-11"
                value={knowledgeBaseIds}
                onValueChange={setKnowledgeBaseIds}
                placeholder="选择知识库"
                options={knowledgeBases.map((knowledgeBase) => ({
                  value: knowledgeBase.id,
                  label: knowledgeBase.name,
                }))}
              />
            </label>
            <label className="text-xs text-[var(--muted)]">
              <span className="mb-2 block">时间字段</span>
              <Select
                ariaLabel="时间字段"
                value={field}
                onValueChange={setField}
                options={[
                  { value: "source_time", label: "source_time" },
                  { value: "created_at", label: "created_at" },
                  { value: "updated_at", label: "updated_at" },
                ]}
              />
            </label>
            <label className="text-xs text-[var(--muted)]">
              <span className="mb-2 block">从</span>
              <DateTimePicker
                ariaLabel="开始时间"
                value={from}
                onValueChange={setFrom}
                placeholder="选择开始时间"
              />
            </label>
            <label className="text-xs text-[var(--muted)]">
              <span className="mb-2 block">到</span>
              <DateTimePicker
                ariaLabel="结束时间"
                value={to}
                onValueChange={setTo}
                placeholder="选择结束时间"
              />
            </label>
            <label className="flex items-end gap-2 pb-3 text-xs text-[var(--muted)]">
              <input
                type="checkbox"
                checked={includeUnknown}
                onChange={(event) => setIncludeUnknown(event.target.checked)}
              />
              包含未知时间
            </label>
          </div>
        </form>
      </Card>
      {search.error && (
        <p className="mt-5 rounded-xl bg-red-500/10 p-3 text-sm text-red-500">
          {search.error.message}
        </p>
      )}
      <section className="mt-7 space-y-4">
        {search.data?.results.map((result) => (
          <Card key={result.chunk_id} className="p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/10 text-xs font-semibold text-violet-500">
                  {result.citation_number}
                </span>
                <span className="text-sm font-semibold">{result.document_name}</span>
              </div>
              <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
                <CalendarRange size={14} />
                {result.source_time
                  ? new Date(result.source_time).toLocaleString("zh-CN")
                  : "时间未知"}
              </div>
            </div>
            {result.section && (
              <div className="mb-2 text-xs font-medium text-violet-500">
                {result.section}
              </div>
            )}
            <p className="whitespace-pre-wrap text-sm leading-7 text-[var(--muted)]">
              {result.original_text}
            </p>
            <Link
              className="mt-3 inline-block text-xs font-medium text-violet-500"
              to={`/documents/${result.document_id}?chunk=${result.chunk_id}`}
            >
              定位到原文
            </Link>
          </Card>
        ))}
      </section>
    </>
  );
}
