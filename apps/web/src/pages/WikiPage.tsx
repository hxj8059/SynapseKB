import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Activity,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  FileText,
  Network,
  RefreshCw,
  Search,
  Square,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { MarkdownContent } from "../components/MarkdownContent";
import { StatusPill } from "../components/StatusPill";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { api } from "../lib/api";
import { WIKI_INDEX_PAGE_SIZE, wikiIndexPagePath } from "../lib/wikiIndex";
import type {
  KnowledgeBase,
  WikiHealthJob,
  WikiIndexPage,
  WikiJob,
  WikiPageContent,
  WikiPageVersion,
  WikiGraph,
  WikiEntityResolution,
  WikiSimilarityCandidate,
} from "../lib/types";
import { useAuthStore } from "../stores/auth";

const HEALTH_SUMMARY_LABELS: Record<string, string> = {
  orphan_pages: "孤立页面",
  isolated_nodes: "孤立图节点",
  missing_sources: "缺失来源",
  similar_candidates: "待复核相似节点",
  proposed_actions: "模型建议",
  auto_repaired: "自动修复",
  auto_merged: "模型自动合并",
  auto_marked_distinct: "模型判定不同实体",
  embedded_nodes: "本次生成向量（旧字段）",
  embedded_nodes_updated: "本次更新向量",
  embedded_nodes_total: "已有向量节点",
};

export function WikiPage() {
  const [searchParams] = useSearchParams();
  const requestedPageId = searchParams.get("page");
  const requestedKnowledgeBaseId = searchParams.get("kb");
  const user = useAuthStore((state) => state.user);
  const client = useQueryClient();
  const [knowledgeBaseId, setKnowledgeBaseId] = useState("");
  const [pageId, setPageId] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [healthJobId, setHealthJobId] = useState<string | null>(null);
  const [showHealth, setShowHealth] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [showVersions, setShowVersions] = useState(false);
  const [relationNotice, setRelationNotice] = useState("");
  const [indexPage, setIndexPage] = useState(1);
  const [indexQuery, setIndexQuery] = useState("");
  const [debouncedIndexQuery, setDebouncedIndexQuery] = useState("");
  const [indexNodeType, setIndexNodeType] = useState("");
  const contentRef = useRef<HTMLDivElement>(null);
  const [selectedCandidate, setSelectedCandidate] =
    useState<WikiSimilarityCandidate | null>(null);
  const { data: knowledgeBases = [] } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api<KnowledgeBase[]>("/knowledge-bases"),
  });
  useEffect(() => {
    if (
      requestedKnowledgeBaseId &&
      knowledgeBases.some((item) => item.id === requestedKnowledgeBaseId)
    ) {
      setKnowledgeBaseId(requestedKnowledgeBaseId);
      return;
    }
    if (!knowledgeBaseId && knowledgeBases[0]) {
      setKnowledgeBaseId(knowledgeBases[0].id);
    }
  }, [knowledgeBaseId, knowledgeBases, requestedKnowledgeBaseId]);
  useEffect(() => {
    const timeout = window.setTimeout(() => setDebouncedIndexQuery(indexQuery), 250);
    return () => window.clearTimeout(timeout);
  }, [indexQuery]);
  const {
    data: indexData,
    error: indexError,
    isFetching: isIndexFetching,
    isLoading,
  } = useQuery({
    queryKey: [
      "wiki-index",
      knowledgeBaseId,
      indexPage,
      debouncedIndexQuery,
      indexNodeType,
    ],
    queryFn: () =>
      api<WikiIndexPage>(
        wikiIndexPagePath(
          knowledgeBaseId,
          indexPage,
          debouncedIndexQuery,
          indexNodeType,
        ),
      ),
    enabled: Boolean(knowledgeBaseId),
    retry: false,
    placeholderData: (previousData, previousQuery) =>
      previousQuery?.queryKey[1] === knowledgeBaseId
        ? keepPreviousData(previousData)
        : undefined,
  });
  const pages = indexData?.items ?? [];
  const totalPublished = indexData?.total_published ?? 0;
  const filteredTotal = indexData?.total ?? 0;
  const typeCounts = indexData?.type_counts ?? [];
  const indexPageCount = Math.max(
    1,
    Math.ceil(filteredTotal / WIKI_INDEX_PAGE_SIZE),
  );
  const currentIndexPage = Math.min(indexPage, indexPageCount);
  useEffect(() => {
    setIndexPage(1);
  }, [debouncedIndexQuery, indexNodeType, knowledgeBaseId]);
  useEffect(() => {
    if (indexPage > indexPageCount) setIndexPage(indexPageCount);
  }, [indexPage, indexPageCount]);
  useEffect(() => {
    if (requestedPageId && indexData) {
      setPageId(requestedPageId);
      return;
    }
    if (!pageId && pages[0]) {
      setPageId(pages[0].id);
    }
  }, [indexData, pageId, pages, requestedPageId]);
  const { data: page } = useQuery({
    queryKey: ["wiki-page", pageId],
    queryFn: () => api<WikiPageContent>(`/wiki/pages/${pageId}`),
    enabled: Boolean(pageId),
  });
  const { data: relations } = useQuery({
    queryKey: ["wiki-page-relations", pageId],
    queryFn: () => api<WikiGraph>(`/wiki/pages/${pageId}/relations`),
    enabled: Boolean(pageId),
  });
  useEffect(() => {
    if (page) setEditContent(page.content);
  }, [page]);
  const { data: versions = [] } = useQuery({
    queryKey: ["wiki-versions", pageId],
    queryFn: () => api<WikiPageVersion[]>(`/wiki/pages/${pageId}/versions`),
    enabled: Boolean(pageId && showVersions),
  });
  const { data: job } = useQuery({
    queryKey: ["wiki-job", jobId],
    queryFn: () => api<WikiJob>(`/wiki/jobs/${jobId}`),
    enabled: Boolean(jobId),
    refetchInterval: (query) =>
      query.state.data &&
      ["published", "failed", "quality_failed", "cancelled"].includes(
        query.state.data.status,
      )
        ? false
        : 1500,
  });
  const { data: latestHealth } = useQuery({
    queryKey: ["wiki-health-latest", knowledgeBaseId],
    queryFn: () =>
      api<WikiHealthJob>(`/wiki/${knowledgeBaseId}/health/latest`),
    enabled: Boolean(knowledgeBaseId && showHealth && !healthJobId),
    retry: false,
  });
  const { data: runningHealth } = useQuery({
    queryKey: ["wiki-health-job", healthJobId],
    queryFn: () => api<WikiHealthJob>(`/wiki/health/jobs/${healthJobId}`),
    enabled: Boolean(healthJobId),
    refetchInterval: (query) =>
      query.state.data && ["completed", "failed", "cancelled"].includes(query.state.data.status)
        ? false
        : 1500,
  });
  const health = runningHealth ?? latestHealth;
  const healthReport = health?.report as
    | {
        summary?: Record<string, unknown>;
        similar_candidates?: WikiSimilarityCandidate[];
        llm_review_error?: string | null;
        embedding_error?: string | null;
      }
    | undefined;
  const healthSummary = healthReport?.summary;
  const similarityCandidates = (healthReport?.similar_candidates ?? []).filter(
    (candidate) => candidate.candidate_source !== "embedding_cosine",
  );
  const relationProposals =
    health?.proposed_actions.filter((action) => action.type === "add_relation") ?? [];
  const { data: reversibleMerges = [] } = useQuery({
    queryKey: ["wiki-entity-resolutions", knowledgeBaseId, "merge"],
    queryFn: () =>
      api<WikiEntityResolution[]>(
        `/wiki/${knowledgeBaseId}/entity-resolutions?decision=merge&limit=50`,
      ),
    enabled: Boolean(knowledgeBaseId && showHealth && user?.role === "admin"),
  });
  const { data: candidateLeftPage } = useQuery({
    queryKey: ["wiki-candidate-page", selectedCandidate?.left_page_id],
    queryFn: () =>
      api<WikiPageContent>(`/wiki/pages/${selectedCandidate?.left_page_id}`),
    enabled: Boolean(selectedCandidate?.left_page_id),
  });
  const { data: candidateRightPage } = useQuery({
    queryKey: ["wiki-candidate-page", selectedCandidate?.right_page_id],
    queryFn: () =>
      api<WikiPageContent>(`/wiki/pages/${selectedCandidate?.right_page_id}`),
    enabled: Boolean(selectedCandidate?.right_page_id),
  });
  useEffect(() => {
    if (job?.status === "published") {
      client.invalidateQueries({ queryKey: ["wiki-index", knowledgeBaseId] });
    }
  }, [client, job?.status, knowledgeBaseId]);
  const generate = useMutation({
    mutationFn: () =>
      api<WikiJob>("/wiki/generate", {
        method: "POST",
        body: JSON.stringify({
          knowledge_base_id: knowledgeBaseId,
          document_ids: [],
        }),
      }),
    onSuccess: (created) => setJobId(created.id),
  });
  const cancel = useMutation({
    mutationFn: () =>
      api<WikiJob>(`/wiki/jobs/${jobId}/cancel`, { method: "POST" }),
    onSuccess: (updated) => client.setQueryData(["wiki-job", jobId], updated),
  });
  const startHealth = useMutation({
    mutationFn: () =>
      api<WikiHealthJob>("/wiki/health/check", {
        method: "POST",
        body: JSON.stringify({
          knowledge_base_id: knowledgeBaseId,
          auto_repair: true,
        }),
      }),
    onSuccess: (created) => {
      setHealthJobId(created.id);
      setShowHealth(true);
    },
  });
  const mergePages = useMutation({
    mutationFn: ({
      candidate,
      target,
    }: {
      candidate: WikiSimilarityCandidate;
      target: "left" | "right";
    }) =>
      api<WikiPageContent>(`/wiki/${knowledgeBaseId}/merge`, {
        method: "POST",
        body: JSON.stringify({
          target_page_id:
            target === "left" ? candidate.left_page_id : candidate.right_page_id,
          source_page_ids: [
            target === "left" ? candidate.right_page_id : candidate.left_page_id,
          ],
          change_summary: `健康检查人工确认合并：${candidate.left_label} / ${candidate.right_label}`,
          health_job_id: health?.id,
        }),
      }),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["wiki-index", knowledgeBaseId] });
      client.invalidateQueries({ queryKey: ["wiki-page"] });
      client.invalidateQueries({ queryKey: ["wiki-page-relations"] });
      setSelectedCandidate(null);
      client.invalidateQueries({ queryKey: ["wiki-health-job", health?.id] });
      client.invalidateQueries({ queryKey: ["wiki-health-latest", knowledgeBaseId] });
      client.invalidateQueries({ queryKey: ["wiki-entity-resolutions", knowledgeBaseId] });
    },
  });
  const markDistinct = useMutation({
    mutationFn: (candidate: WikiSimilarityCandidate) =>
      api<{ id: string; decision: string }>(
        `/wiki/${knowledgeBaseId}/similarity-decisions`,
        {
          method: "POST",
          body: JSON.stringify({
            left_page_id: candidate.left_page_id,
            right_page_id: candidate.right_page_id,
            decision: "distinct",
            reason: "管理员人工确认不是同一 Wiki 实体",
            health_job_id: health?.id,
          }),
        },
      ),
    onSuccess: () => {
      setSelectedCandidate(null);
      client.invalidateQueries({ queryKey: ["wiki-health-job", health?.id] });
      client.invalidateQueries({ queryKey: ["wiki-health-latest", knowledgeBaseId] });
    },
  });
  const undoMerge = useMutation({
    mutationFn: (action: WikiEntityResolution) =>
      api<WikiPageContent>(
        `/wiki/${knowledgeBaseId}/merges/${String(action.id)}/undo`,
        { method: "POST" },
      ),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["wiki-index", knowledgeBaseId] });
      client.invalidateQueries({ queryKey: ["wiki-page"] });
      client.invalidateQueries({ queryKey: ["wiki-page-relations"] });
      client.invalidateQueries({ queryKey: ["wiki-health-job", health?.id] });
      client.invalidateQueries({ queryKey: ["wiki-health-latest", knowledgeBaseId] });
      client.invalidateQueries({ queryKey: ["wiki-entity-resolutions", knowledgeBaseId] });
    },
  });
  const addRelation = useMutation({
    mutationFn: (action: Record<string, unknown>) =>
      api<{ id: string; status: string }>(`/wiki/${knowledgeBaseId}/relations`, {
        method: "POST",
        body: JSON.stringify({
          source_page_id: action.source_page_id,
          target_page_id: action.target_page_id,
          relation_type: action.relation_type ?? "related_to",
          evidence: action.reason,
          health_job_id: health?.id,
          proposal_id: action.id,
        }),
      }),
    onSuccess: async (_created, action) => {
      setRelationNotice(`关系已添加：${String(action.reason ?? "")}`);
      client.invalidateQueries({ queryKey: ["wiki-page-relations"] });
      await Promise.all([
        client.invalidateQueries({ queryKey: ["wiki-health-job", health?.id] }),
        client.invalidateQueries({ queryKey: ["wiki-health-latest", knowledgeBaseId] }),
      ]);
    },
  });
  const save = useMutation({
    mutationFn: () =>
      api<WikiPageContent>(`/wiki/pages/${pageId}`, {
        method: "PATCH",
        body: JSON.stringify({
          content: editContent,
          protected_blocks: page?.protected_blocks ?? [],
          change_summary: "管理员手动编辑",
          source_time: page?.source_time,
        }),
      }),
    onSuccess: (updated) => {
      client.setQueryData(["wiki-page", pageId], updated);
      client.invalidateQueries({ queryKey: ["wiki-versions", pageId] });
      setEditing(false);
    },
  });
  const rollback = useMutation({
    mutationFn: (versionId: string) =>
      api<WikiPageContent>(`/wiki/pages/${pageId}/rollback/${versionId}`, {
        method: "POST",
      }),
    onSuccess: (updated) => {
      client.setQueryData(["wiki-page", pageId], updated);
      client.invalidateQueries({ queryKey: ["wiki-versions", pageId] });
    },
  });
  const centerNode = relations?.nodes.find((node) => node.page_id === pageId);
  const linkedNodes = (relations?.edges ?? []).flatMap((edge) => {
    if (!centerNode) return [];
    const neighborId = edge.source === centerNode.id ? edge.target : edge.source;
    const neighbor = relations?.nodes.find((node) => node.id === neighborId);
    return neighbor ? [{ edge, node: neighbor }] : [];
  });

  return (
    <>
      <PageHeader
        eyebrow="Wiki"
        title="知识 Wiki"
        description="这里只展示通过来源检查并原子发布的版本，生成失败时仍保留旧版本。"
        actions={
          <div className="flex items-center gap-2">
            <Select
              ariaLabel="Wiki 知识库"
              className="w-44"
              value={knowledgeBaseId}
              onValueChange={(value) => {
                setKnowledgeBaseId(value);
                setPageId("");
                setJobId(null);
                setHealthJobId(null);
              }}
              placeholder="选择知识库"
              options={knowledgeBases.map((knowledgeBase) => ({
                value: knowledgeBase.id,
                label: knowledgeBase.name,
              }))}
            />
            {user?.role === "admin" && (
              <>
                <Button
                  variant="secondary"
                  onClick={() => setShowHealth((value) => !value)}
                  disabled={!knowledgeBaseId}
                >
                  <Activity size={15} />
                  健康检查
                </Button>
                <Button
                  onClick={() => generate.mutate()}
                  disabled={!knowledgeBaseId || generate.isPending}
                >
                  <RefreshCw size={15} />
                  生成/更新
                </Button>
              </>
            )}
          </div>
        }
      />
      {job && (
        <Card className="mb-5 flex items-center justify-between p-4">
          <div className="flex items-center gap-3">
            <StatusPill status={job.status} />
            <span className="text-xs text-[var(--muted)]">
              {job.change_summary || job.error_summary || "Wiki 任务处理中"}
            </span>
          </div>
          {["queued", "running", "quality_check"].includes(job.status) && (
            <Button variant="secondary" size="sm" onClick={() => cancel.mutate()}>
              <Square size={14} />
              取消
            </Button>
          )}
        </Card>
      )}
      {generate.error && (
        <p className="mb-5 rounded-xl bg-red-500/10 p-3 text-sm text-red-500">
          {generate.error.message}
        </p>
      )}
      {showHealth && user?.role === "admin" && (
        <Card className="mb-5 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-semibold">Wiki 健康报告</h2>
                {health && <StatusPill status={health.status} />}
              </div>
              <p className="mt-1 text-xs text-[var(--muted)]">
                模型只会自动合并高置信度的同一实体，并保存完整快照；所有合并都可人工撤销。
              </p>
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => startHealth.mutate()}
              disabled={
                startHealth.isPending ||
                ["queued", "running"].includes(health?.status ?? "")
              }
            >
              立即检查
            </Button>
          </div>
          {health?.error_summary && (
            <p className="mt-3 text-xs text-red-500">{health.error_summary}</p>
          )}
          {healthReport?.llm_review_error && (
            <div className="mt-3 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-xs leading-5 text-amber-700 dark:text-amber-300">
              模型语义复核未完成：{healthReport.llm_review_error}
              <span className="mt-1 block text-[var(--muted)]">
                粗候选仍可在下方人工比较，不会因为模型失败而消失。
              </span>
            </div>
          )}
          {healthReport?.embedding_error && (
            <p className="mt-3 text-xs text-amber-600">
              节点向量更新提示：{healthReport.embedding_error}
            </p>
          )}
          {healthSummary && (
            <div className="mt-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {Object.entries(healthSummary).map(
                ([key, value]) => (
                  <div key={key} className="rounded-xl bg-[var(--surface-hover)] p-3">
                    <div className="text-lg font-semibold">{String(value)}</div>
                    <div className="mt-1 text-[11px] text-[var(--muted)]">
                      {HEALTH_SUMMARY_LABELS[key] ?? key}
                    </div>
                  </div>
                ),
              )}
            </div>
          )}
          {similarityCandidates.length > 0 && (
            <div className="mt-5 space-y-3">
              <div>
                <h3 className="text-sm font-semibold">相似节点人工复核</h3>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  高置信度的同一/不同实体结论已由模型自动执行；这里仅保留低置信度或执行失败的候选。
                </p>
              </div>
              {similarityCandidates.map((candidate) => {
                const recommendation = health?.proposed_actions.find(
                  (action) =>
                    action.type === "merge_pages" &&
                    [
                      String(action.target_page_id),
                      ...((action.source_page_ids as string[] | undefined) ?? []),
                    ].every((id) =>
                      [candidate.left_page_id, candidate.right_page_id].includes(id),
                    ),
                );
                return (
                  <div
                    key={`${candidate.left_page_id}-${candidate.right_page_id}`}
                    className="rounded-xl border border-[var(--border)] p-3 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="font-medium">
                          {candidate.left_label}
                          <span className="mx-2 text-[var(--muted)]">↔</span>
                          {candidate.right_label}
                        </div>
                        <p className="mt-1 text-[var(--muted)]">
                          {candidate.node_type} · {candidate.candidate_source === "alias_exact"
                            ? "别名完全匹配"
                            : `名称重合度 ${Math.round(candidate.similarity * 100)}%（仅用于候选召回）`}
                        </p>
                        {recommendation && (
                          <>
                            <p className="mt-1 text-violet-500">
                              {recommendation.resolution_mode === "fold_into"
                                ? "模型建议归并非实体页面"
                                : "模型建议合并"}
                              ：{String(recommendation.reason ?? "")}
                            </p>
                            {recommendation.auto_apply_block_reason && (
                              <p className="mt-1 text-amber-600 dark:text-amber-400">
                                暂未自动执行：
                                {String(recommendation.auto_apply_block_reason)}
                              </p>
                            )}
                          </>
                        )}
                        {!recommendation && candidate.model_reason && (
                          <p className="mt-1 text-cyan-600 dark:text-cyan-300">
                            模型判定 {candidate.model_classification ?? "待定"}
                            {typeof candidate.model_confidence === "number"
                              ? `（${Math.round(candidate.model_confidence * 100)}%）`
                              : ""}：{candidate.model_reason}
                          </p>
                        )}
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        aria-label={`比较 ${candidate.left_label} 和 ${candidate.right_label}`}
                        onClick={() => setSelectedCandidate(candidate)}
                      >
                        比较并处理
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {selectedCandidate && (
            <div className="mt-5 rounded-2xl border border-violet-400/30 bg-violet-500/5 p-4">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold">节点合并预览</h3>
                <Button variant="ghost" size="sm" onClick={() => setSelectedCandidate(null)}>
                  关闭
                </Button>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                {[
                  { side: "left" as const, page: candidateLeftPage },
                  { side: "right" as const, page: candidateRightPage },
                ].map(({ side, page: candidatePage }) => (
                  <div
                    key={side}
                    className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4"
                  >
                    <div className="font-semibold">
                      {candidatePage?.title ??
                        (side === "left"
                          ? selectedCandidate.left_label
                          : selectedCandidate.right_label)}
                    </div>
                    <div className="mt-1 text-[11px] text-[var(--muted)]">
                      {candidatePage
                        ? `${candidatePage.sources.length} 个来源 · v${candidatePage.version_number}`
                        : "正在读取内容…"}
                    </div>
                    <div className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap text-xs leading-5 text-[var(--muted)]">
                      {candidatePage?.content.slice(0, 1800) ?? ""}
                    </div>
                    <Button
                      className="mt-4 w-full"
                      size="sm"
                      variant="secondary"
                      disabled={!candidatePage || mergePages.isPending || markDistinct.isPending}
                      onClick={() => {
                        const sourceName =
                          side === "left"
                            ? selectedCandidate.right_label
                            : selectedCandidate.left_label;
                        if (
                          window.confirm(
                            `确认以“${candidatePage?.title}”为主节点，并将“${sourceName}”的内容、来源和关系合入？`,
                          )
                        ) {
                          mergePages.mutate({ candidate: selectedCandidate, target: side });
                        }
                      }}
                    >
                      保留此节点并合并另一节点
                    </Button>
                  </div>
                ))}
              </div>
              <Button
                className="mt-3"
                size="sm"
                variant="ghost"
                disabled={mergePages.isPending || markDistinct.isPending}
                onClick={() => {
                  if (window.confirm("确认这两个节点不是同一实体？该结论会在后续检查中保留。")) {
                    markDistinct.mutate(selectedCandidate);
                  }
                }}
              >
                标记为不同节点
              </Button>
            </div>
          )}
          {relationProposals.length > 0 && (
            <div className="mt-5 space-y-3">
              <h3 className="text-sm font-semibold">待确认的关系建议</h3>
              {relationProposals.map((action) => (
                <div
                  key={String(action.id)}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--border)] p-3 text-xs"
                >
                  <p className="text-[var(--muted)]">{String(action.reason ?? "")}</p>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={addRelation.isPending}
                    onClick={() => {
                      if (window.confirm("确认添加这条 Wiki 双链关系？")) {
                        setRelationNotice("");
                        addRelation.mutate(action);
                      }
                    }}
                  >
                    {addRelation.isPending && addRelation.variables?.id === action.id
                      ? "添加中…"
                      : "确认加关系"}
                  </Button>
                </div>
              ))}
            </div>
          )}
          {reversibleMerges.length > 0 && (
            <div className="mt-5 space-y-3">
              <h3 className="text-sm font-semibold">本次检查已执行的合并</h3>
              {reversibleMerges.map((action) => (
                <div
                  key={String(action.id)}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[var(--border)] p-3 text-xs"
                >
                  <div>
                    <div className="font-medium">
                      {(action.left_page_id === action.canonical_page_id
                        ? action.right_title
                        : action.left_title) ?? "来源节点"}
                      <span className="mx-2 text-[var(--muted)]">→</span>
                      {action.canonical_title ?? "主节点"}
                    </div>
                      <p className="mt-1 text-[var(--muted)]">
                        {action.decision_source === "llm_auto" ? "模型自动处理 · " : "人工合并 · "}
                        {action.reason}
                      </p>
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={undoMerge.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          "确认撤销这次合并？系统会恢复来源页面、节点、别名和原始关系。",
                        )
                      ) {
                        undoMerge.mutate(action);
                      }
                    }}
                  >
                    撤销合并
                  </Button>
                </div>
              ))}
            </div>
          )}
          {startHealth.error && (
            <p className="mt-3 text-xs text-red-500">{startHealth.error.message}</p>
          )}
          {mergePages.error && (
            <p className="mt-3 text-xs text-red-500">{mergePages.error.message}</p>
          )}
          {markDistinct.error && (
            <p className="mt-3 text-xs text-red-500">{markDistinct.error.message}</p>
          )}
          {undoMerge.error && (
            <p className="mt-3 text-xs text-red-500">{undoMerge.error.message}</p>
          )}
          {addRelation.error && (
            <p className="mt-3 text-xs text-red-500">{addRelation.error.message}</p>
          )}
          {relationNotice && (
            <p className="mt-3 text-xs text-emerald-600 dark:text-emerald-400">
              {relationNotice}
            </p>
          )}
        </Card>
      )}
      {isLoading ? (
        <p className="text-sm text-[var(--muted)]">正在读取 Wiki…</p>
      ) : indexError || totalPublished === 0 ? (
        <Card className="flex min-h-72 flex-col items-center justify-center p-8 text-center">
          <BookOpen className="mb-4 text-violet-500" />
          <h2 className="font-semibold">尚无已发布 Wiki</h2>
          <p className="mt-2 max-w-md text-sm leading-6 text-[var(--muted)]">
            管理员可以在文档索引完成后启动首次生成。生成中的候选页面不会泄露给读者。
          </p>
        </Card>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          <Card className="flex h-[min(720px,calc(100vh-10rem))] min-h-[560px] flex-col overflow-hidden p-0">
            <div className="border-b border-[var(--border)] p-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-semibold">节点目录</h2>
                  <p className="mt-1 text-xs text-[var(--muted)]">
                    共 {totalPublished} 个已发布节点
                    {isIndexFetching ? " · 更新中" : ""}
                  </p>
                </div>
                <span className="rounded-full bg-violet-500/10 px-2.5 py-1 text-xs font-semibold text-violet-600 dark:text-violet-300">
                  {filteredTotal}
                </span>
              </div>
              <div className="relative mt-3">
                <Search
                  size={14}
                  className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted)]"
                />
                <input
                  aria-label="搜索 Wiki 节点"
                  className="h-10 w-full rounded-xl border border-[var(--border)] bg-[var(--canvas)] pl-9 pr-3 text-sm outline-none transition focus:border-violet-500 focus:ring-2 focus:ring-violet-500/15"
                  placeholder="搜索节点…"
                  value={indexQuery}
                  onChange={(event) => setIndexQuery(event.target.value)}
                />
              </div>
              <div className="mt-3 flex gap-2 overflow-x-auto pb-1">
                <button
                  type="button"
                  className={`shrink-0 rounded-full px-2.5 py-1 text-xs transition ${
                    indexNodeType === ""
                      ? "bg-[var(--text)] text-[var(--surface)]"
                      : "bg-[var(--surface-hover)] text-[var(--muted)] hover:text-[var(--text)]"
                  }`}
                  onClick={() => setIndexNodeType("")}
                >
                  全部 {totalPublished}
                </button>
                {typeCounts.map(({ type, count }) => (
                  <button
                    key={type}
                    type="button"
                    className={`shrink-0 rounded-full px-2.5 py-1 text-xs transition ${
                      indexNodeType === type
                        ? "bg-[var(--text)] text-[var(--surface)]"
                        : "bg-[var(--surface-hover)] text-[var(--muted)] hover:text-[var(--text)]"
                    }`}
                    onClick={() => setIndexNodeType(type)}
                  >
                    {type} {count}
                  </button>
                ))}
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {pages.length ? (
                pages.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`w-full rounded-xl px-3 py-2.5 text-left text-sm transition ${
                      pageId === item.id
                        ? "bg-violet-500/10 font-semibold text-violet-700 dark:text-violet-200"
                        : "hover:bg-[var(--surface-hover)]"
                    }`}
                    onClick={() => {
                      setPageId(item.id);
                      requestAnimationFrame(() =>
                        contentRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
                      );
                    }}
                  >
                    <span className="line-clamp-2 leading-5">{item.title}</span>
                    <span className="mt-1 flex items-center justify-between gap-2 text-[11px] font-normal text-[var(--muted)]">
                      <span>{item.node_type || "页面"}</span>
                      <span className="truncate">
                        {item.source_time
                          ? new Date(item.source_time).toLocaleDateString("zh-CN")
                          : "时间未知"}
                      </span>
                    </span>
                  </button>
                ))
              ) : (
                <p className="p-5 text-center text-xs text-[var(--muted)]">没有匹配的节点</p>
              )}
            </div>
            <div className="flex h-14 shrink-0 items-center justify-between border-t border-[var(--border)] px-3">
              <Button
                aria-label="上一页"
                size="icon"
                variant="ghost"
                disabled={currentIndexPage <= 1}
                onClick={() => setIndexPage((value) => Math.max(1, value - 1))}
              >
                <ChevronLeft size={16} />
              </Button>
              <span className="text-xs tabular-nums text-[var(--muted)]">
                {currentIndexPage} / {indexPageCount}
              </span>
              <Button
                aria-label="下一页"
                size="icon"
                variant="ghost"
                disabled={currentIndexPage >= indexPageCount}
                onClick={() => setIndexPage((value) => Math.min(indexPageCount, value + 1))}
              >
                <ChevronRight size={16} />
              </Button>
            </div>
          </Card>
          <Card ref={contentRef} className="scroll-mt-6 p-7">
            <div className="flex items-start justify-between gap-3">
              <h1 className="text-2xl font-semibold">{page?.title}</h1>
              {user?.role === "admin" && page && (
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setShowVersions((value) => !value)}
                  >
                    历史
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => {
                      if (editing) {
                        if (window.confirm("确认发布这次手动编辑？")) save.mutate();
                      } else {
                        setEditing(true);
                      }
                    }}
                    disabled={save.isPending}
                  >
                    {editing ? "确认发布" : "编辑"}
                  </Button>
                </div>
              )}
            </div>
            <div className="mt-2 text-xs text-[var(--muted)]">
              版本 {page?.version_number} · source_time：
              {page?.source_time || "未知"}
            </div>
            {editing ? (
              <textarea
                className="mt-7 min-h-[520px] w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 font-mono text-sm leading-7"
                value={editContent}
                onChange={(event) => setEditContent(event.target.value)}
              />
            ) : (
              <div className="mt-7">
                <MarkdownContent>{page?.content ?? ""}</MarkdownContent>
              </div>
            )}
            {linkedNodes.length > 0 && (
              <section className="mt-8 border-t border-[var(--border)] pt-5">
                <div className="flex items-center gap-2">
                  <Network size={16} className="text-violet-500" />
                  <h2 className="text-sm font-semibold">
                    关联节点与双链（{linkedNodes.length}）
                  </h2>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {linkedNodes.map(({ edge, node }) => (
                    <div
                      key={edge.id}
                      className="rounded-xl border border-[var(--border)] p-3"
                    >
                      <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
                        {node.document_id ? <FileText size={13} /> : <Network size={13} />}
                        <span>{node.type}</span>
                        <span>·</span>
                        <span>{edge.type === "sourced_from" ? "来源于" : edge.type}</span>
                      </div>
                      <div className="mt-1 text-sm font-medium">{node.label}</div>
                      {edge.evidence && (
                        <p className="mt-1 line-clamp-2 text-xs leading-5 text-[var(--muted)]">
                          {edge.evidence}
                        </p>
                      )}
                      {node.page_id ? (
                        <Link
                          className="mt-2 inline-block text-xs font-medium text-violet-500"
                          to={`/wiki?kb=${knowledgeBaseId}&page=${node.page_id}`}
                        >
                          打开节点 Markdown
                        </Link>
                      ) : node.document_id ? (
                        <Link
                          className="mt-2 inline-block text-xs font-medium text-violet-500"
                          to={`/documents/${node.document_id}`}
                        >
                          查看来源文档
                        </Link>
                      ) : null}
                    </div>
                  ))}
                </div>
              </section>
            )}
            {showVersions && (
              <div className="mt-6 rounded-xl border border-[var(--border)] p-4">
                <h2 className="text-sm font-semibold">版本历史</h2>
                <div className="mt-3 space-y-2">
                  {versions.map((version) => (
                    <div
                      key={version.id}
                      className="flex items-center justify-between gap-3 text-xs"
                    >
                      <span>
                        v{version.version_number} · {version.change_summary} ·{" "}
                        {new Date(version.created_at).toLocaleString("zh-CN")}
                      </span>
                      {version.id !== page?.current_version_id && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            if (window.confirm(`确认回滚到 v${version.version_number}？`)) {
                              rollback.mutate(version.id);
                            }
                          }}
                        >
                          回滚
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
            {page && page.sources.length > 0 && (
              <details className="mt-8 border-t border-[var(--border)] pt-5">
                <summary className="cursor-pointer text-sm font-semibold">
                  页面来源（{page.sources.length}）
                </summary>
                <div className="mt-3 space-y-3">
                  {page.sources.map((source) => (
                    <div
                      key={`${source.document_id}-${source.paragraph_key}`}
                      className="rounded-xl bg-[var(--surface-hover)] p-3 text-xs leading-6"
                    >
                      <div className="font-medium">
                        {source.document_name || `文档 ${source.document_id}`} ·{" "}
                        {source.source_time || "时间未知"}
                      </div>
                      <p className="mt-1 text-[var(--muted)]">{source.evidence_text}</p>
                      <Link
                        className="mt-2 inline-block font-medium text-violet-500"
                        to={`/documents/${source.document_id}${
                          source.chunk_id ? `?chunk=${source.chunk_id}` : ""
                        }`}
                      >
                        定位到来源
                      </Link>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
