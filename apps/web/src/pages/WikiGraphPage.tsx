import { useMutation, useQuery } from "@tanstack/react-query";
import cytoscape, { type Core } from "cytoscape";
import { Focus, Network, Search, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { DateTimePicker } from "../components/ui/date-time-picker";
import { Input } from "../components/ui/input";
import { Select } from "../components/ui/select";
import { api } from "../lib/api";
import type { KnowledgeBase, WikiGraph } from "../lib/types";
import { filterWikiGraphByNodeTypes } from "../lib/wikiGraph";

const palette = ["#8b5cf6", "#06b6d4", "#f59e0b", "#ec4899", "#22c55e", "#3b82f6"];

type GraphMode = "overview" | "local";

function colorForType(type: string) {
  if (type === "document") return "#06b6d4";
  let hash = 0;
  for (const character of type) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length] ?? "#8b5cf6";
}

function relationLabel(type: string) {
  const labels: Record<string, string> = {
    sourced_from: "来源于",
    related_to: "关联",
    replaces: "替代",
  };
  return labels[type] ?? type.replaceAll("_", " ");
}

export function WikiGraphPage() {
  const navigate = useNavigate();
  const container = useRef<HTMLDivElement>(null);
  const graph = useRef<Core | null>(null);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState("");
  const [query, setQuery] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [timeField, setTimeField] = useState("source_time");
  const [viewMode, setViewMode] = useState<GraphMode>("overview");
  const [graphLimit, setGraphLimit] = useState("160");
  const [activeMode, setActiveMode] = useState<GraphMode>("overview");
  const [includeUnknown, setIncludeUnknown] = useState(false);
  const [nodeTypes, setNodeTypes] = useState<string[]>([]);
  const [selected, setSelected] = useState<WikiGraph["nodes"][number] | null>(
    null,
  );
  const [selectedEdge, setSelectedEdge] = useState<
    WikiGraph["edges"][number] | null
  >(null);
  const { data: knowledgeBases = [] } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api<KnowledgeBase[]>("/knowledge-bases"),
  });
  useEffect(() => {
    if (!knowledgeBaseId && knowledgeBases[0]) {
      setKnowledgeBaseId(knowledgeBases[0].id);
    }
  }, [knowledgeBaseId, knowledgeBases]);
  const selectedKnowledgeBase = knowledgeBases.find(
    (knowledgeBase) => knowledgeBase.id === knowledgeBaseId,
  );
  const availableNodeTypes = Array.from(
    new Set(["document", ...(selectedKnowledgeBase?.wiki_node_types ?? [])]),
  );
  const availableNodeTypesKey = availableNodeTypes.join("\u001f");
  useEffect(() => {
    setNodeTypes(availableNodeTypes);
  }, [availableNodeTypesKey]);
  const search = useMutation({
    mutationFn: ({
      mode,
      requestedNodeTypes = nodeTypes,
    }: {
      mode: GraphMode;
      requestedNodeTypes?: string[];
    }) =>
      api<WikiGraph>(`/wiki/${knowledgeBaseId}/graph/search`, {
        method: "POST",
        body: JSON.stringify({
          query: mode === "local" ? query.trim() : "",
          mode,
          node_types: requestedNodeTypes,
          time_filter:
            from || to
              ? {
                  field: timeField,
                  from: from ? new Date(from).toISOString() : null,
                  to: to ? new Date(to).toISOString() : null,
                  include_unknown: includeUnknown,
                }
              : null,
          limit: Number(graphLimit),
        }),
      }),
    onSuccess: (_data, variables) => setActiveMode(variables.mode),
  });
  const autoLoadedKnowledgeBase = useRef("");
  useEffect(() => {
    if (
      !knowledgeBaseId ||
      availableNodeTypes.length === 0 ||
      autoLoadedKnowledgeBase.current === knowledgeBaseId
    ) {
      return;
    }
    autoLoadedKnowledgeBase.current = knowledgeBaseId;
    setViewMode("overview");
    search.mutate({ mode: "overview", requestedNodeTypes: availableNodeTypes });
  }, [availableNodeTypesKey, knowledgeBaseId]);
  const visibleGraph = useMemo(
    () =>
      search.data
        ? filterWikiGraphByNodeTypes(search.data, nodeTypes)
        : null,
    [nodeTypes, search.data],
  );

  useEffect(() => {
    if (!container.current || !visibleGraph) return;
    graph.current?.destroy();
    const dense =
      visibleGraph.nodes.length > 120 || visibleGraph.edges.length > 180;
    const overview = visibleGraph.meta?.mode === "overview";
    const degree = new Map<string, number>();
    for (const edge of visibleGraph.edges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }
    graph.current = cytoscape({
      container: container.current,
      elements: [
        ...visibleGraph.nodes.map((node) => ({
          data: {
            id: node.id,
            label: node.label,
            node,
            color: colorForType(node.type),
            size: Math.min(56, 30 + (degree.get(node.id) ?? 0) * 3),
          },
          classes: [
            node.type === "document" ? "document" : "knowledge-node",
            dense ? "dense" : "",
          ]
            .filter(Boolean)
            .join(" "),
        })),
        ...visibleGraph.edges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: relationLabel(edge.type),
            edge,
          },
          classes: dense ? "dense" : "",
        })),
      ],
      layout: {
        name: "cose",
        animate: !dense && !overview,
        animationDuration: 420,
        fit: true,
        padding: 64,
        nodeRepulsion: dense ? 14_000 : 9500,
        idealEdgeLength: overview ? 84 : dense ? 90 : 120,
        edgeElasticity: 90,
        componentSpacing: overview ? 72 : 54,
      },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "font-size": 11,
            "font-weight": 600,
            color: "#d7d7e2",
            "text-valign": "bottom",
            "text-margin-y": 10,
            "text-wrap": "ellipsis",
            "text-max-width": "150px",
            "text-background-color": "#171721",
            "text-background-opacity": 0.88,
            "text-background-padding": "4px",
            "min-zoomed-font-size": 8,
            "background-color": "data(color)",
            "border-color": "data(color)",
            "border-width": 5,
            "border-opacity": 0.2,
            width: "data(size)",
            height: "data(size)",
            "overlay-opacity": 0,
          },
        },
        {
          selector: "node.document",
          style: { shape: "round-rectangle", width: 42, height: 30 },
        },
        {
          selector: "node.dense",
          style: {
            label: "",
            "border-width": 3,
            "text-background-opacity": 0,
          },
        },
        {
          selector: "node.dense:selected, node.dense.hovered",
          style: {
            label: "data(label)",
            "text-background-opacity": 0.92,
          },
        },
        {
          selector: "edge",
          style: {
            label: "data(label)",
            "font-size": 8,
            color: "#8d8da1",
            "text-background-color": "#12121a",
            "text-background-opacity": 0.8,
            "text-background-padding": "2px",
            width: 1.3,
            "line-color": "#56566c",
            "target-arrow-color": "#77778d",
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.7,
            "curve-style": "unbundled-bezier",
            "control-point-distances": 28,
            "control-point-weights": 0.5,
            opacity: 0.58,
            "overlay-opacity": 0,
          },
        },
        {
          selector: "edge.dense",
          style: {
            label: "",
            width: 0.8,
            opacity: 0.44,
            "line-color": "#66667e",
            "curve-style": "haystack",
            "target-arrow-shape": "none",
          },
        },
        {
          selector: "edge.dense:selected",
          style: {
            label: "data(label)",
            width: 2,
            opacity: 0.9,
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
          },
        },
        {
          selector: ":selected",
          style: {
            "border-width": 4,
            "border-color": "#ffffff",
            "border-opacity": 0.9,
            opacity: 1,
          },
        },
      ],
    });
    graph.current.on("tap", "node", (event) => {
      const node = event.target.data("node") as WikiGraph["nodes"][number];
      setSelected(node);
      setSelectedEdge(null);
      if (node.page_id) {
        navigate(`/wiki?kb=${knowledgeBaseId}&page=${node.page_id}`);
      }
    });
    graph.current.on("mouseover", "node", (event) => {
      event.target.addClass("hovered");
    });
    graph.current.on("mouseout", "node", (event) => {
      event.target.removeClass("hovered");
    });
    graph.current.on("tap", "edge", (event) => {
      setSelectedEdge(event.target.data("edge") as WikiGraph["edges"][number]);
      setSelected(null);
    });
    return () => graph.current?.destroy();
  }, [knowledgeBaseId, navigate, visibleGraph]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (
      knowledgeBaseId &&
      (viewMode === "overview" || query.trim().length > 0)
    ) {
      search.mutate({ mode: viewMode });
    }
  }

  const graphMeta = visibleGraph?.meta;
  const graphModeLabel = activeMode === "overview" ? "全局概览" : "局部探索";

  return (
    <>
      <PageHeader
        eyebrow="Temporal Graph"
        title="Wiki 关系图"
        description="默认按连接度加载全局骨架；搜索时进入局部子图。时间和节点类型过滤直接在图查询阶段执行。"
      />
      <Card className="mb-5 p-4">
        <form onSubmit={submit}>
          <div className="grid gap-3 lg:grid-cols-[minmax(190px,240px)_170px_minmax(260px,1fr)_160px_auto]">
            <Select
              ariaLabel="关系图知识库"
              value={knowledgeBaseId}
              onValueChange={(value) => {
                setKnowledgeBaseId(value);
                setSelected(null);
                setSelectedEdge(null);
                search.reset();
              }}
              placeholder="选择知识库"
              options={knowledgeBases.map((knowledgeBase) => ({
                value: knowledgeBase.id,
                label: knowledgeBase.name,
              }))}
            />
            <Select
              ariaLabel="关系图浏览模式"
              value={viewMode}
              onValueChange={(value) => setViewMode(value as GraphMode)}
              options={[
                {
                  value: "overview",
                  label: "全局概览",
                  description: "按连接度显示核心骨架",
                },
                {
                  value: "local",
                  label: "局部探索",
                  description: "从搜索命中向外展开",
                },
              ]}
            />
            <Input
              placeholder={
                viewMode === "overview"
                  ? "可直接加载概览，输入关键词会切换到局部探索"
                  : "搜索行业、公司、产品或文档"
              }
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                if (event.target.value.trim()) setViewMode("local");
              }}
            />
            <Select
              ariaLabel="关系图显示密度"
              value={graphLimit}
              onValueChange={setGraphLimit}
              options={[
                { value: "80", label: "精简 · 80 节点" },
                { value: "160", label: "标准 · 160 节点" },
                { value: "300", label: "详细 · 300 节点" },
              ]}
            />
            <Button
              type="submit"
              disabled={
                search.isPending ||
                !knowledgeBaseId ||
                (viewMode === "local" && !query.trim())
              }
            >
              <Search size={15} />
              {viewMode === "overview" ? "加载概览" : "探索"}
            </Button>
          </div>
          <div className="mt-3 grid gap-3 lg:grid-cols-[160px_200px_200px_1fr]">
            <Select
              ariaLabel="时间字段"
              value={timeField}
              onValueChange={setTimeField}
              options={[
                { value: "source_time", label: "source_time" },
                { value: "created_at", label: "created_at" },
                { value: "updated_at", label: "updated_at" },
              ]}
            />
            <DateTimePicker
              ariaLabel="开始时间"
              placeholder="开始时间"
              value={from}
              onValueChange={setFrom}
            />
            <DateTimePicker
              ariaLabel="结束时间"
              placeholder="结束时间"
              value={to}
              onValueChange={setTo}
            />
            <div className="flex min-h-11 flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3.5 text-xs text-[var(--muted)]">
              {availableNodeTypes.map((value) => (
                <label key={value} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={nodeTypes.includes(value)}
                    onChange={(event) =>
                      setNodeTypes((current) =>
                        event.target.checked
                          ? [...current, value]
                          : current.filter((item) => item !== value),
                      )
                    }
                  />
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ backgroundColor: colorForType(value) }}
                  />
                  {value === "document" ? "来源文档" : value}
                </label>
              ))}
              <label className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={includeUnknown}
                  onChange={(event) => setIncludeUnknown(event.target.checked)}
                />
                包含未知时间
              </label>
            </div>
          </div>
        </form>
      </Card>
      {search.error && (
        <p className="mb-5 rounded-xl bg-red-500/10 p-3 text-sm text-red-500">
          {search.error.message}
        </p>
      )}
      <div className="grid gap-5 xl:grid-cols-[1fr_300px]">
        <Card className="relative overflow-hidden border-violet-500/15 bg-[#111119] shadow-[0_24px_80px_rgba(20,12,45,.22)]">
          {!search.data && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-sm text-[var(--muted)]">
              <Network className="mb-3 text-violet-500" />
              选择知识库后会自动加载全局概览
            </div>
          )}
          {visibleGraph && (
            <div className="absolute left-4 top-4 z-10 flex max-w-[calc(100%-10rem)] flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-black/45 px-3 py-2 text-[11px] text-zinc-300 backdrop-blur">
              <span className="font-semibold text-violet-300">
                {graphModeLabel}
              </span>
              <span className="text-zinc-600">·</span>
              <span>
                当前 {visibleGraph.nodes.length}
                {graphMeta ? ` / ${graphMeta.total_nodes}` : ""} 节点
              </span>
              <span className="text-zinc-600">·</span>
              <span>
                当前 {visibleGraph.edges.length}
                {graphMeta ? ` / ${graphMeta.total_edges}` : ""} 关系
              </span>
            </div>
          )}
          <div className="absolute right-4 top-4 z-10 flex gap-1 rounded-xl border border-white/10 bg-black/40 p-1 backdrop-blur">
            <button
              aria-label="放大"
              className="rounded-lg p-2 text-zinc-300 hover:bg-white/10"
              onClick={() => graph.current?.zoom(graph.current.zoom() * 1.2)}
            >
              <ZoomIn size={15} />
            </button>
            <button
              aria-label="缩小"
              className="rounded-lg p-2 text-zinc-300 hover:bg-white/10"
              onClick={() => graph.current?.zoom(graph.current.zoom() / 1.2)}
            >
              <ZoomOut size={15} />
            </button>
            <button
              aria-label="适应画布"
              className="rounded-lg p-2 text-zinc-300 hover:bg-white/10"
              onClick={() => graph.current?.fit(undefined, 56)}
            >
              <Focus size={15} />
            </button>
          </div>
          {graphMeta?.truncated && (
            <div className="absolute bottom-4 left-4 z-10 max-w-[min(38rem,calc(100%-2rem))] rounded-xl border border-white/10 bg-black/45 px-3 py-2 text-[11px] leading-5 text-zinc-400 backdrop-blur">
              {activeMode === "overview"
                ? "当前为核心骨架视图，并未删除其余节点。可提高显示密度，或搜索关键词进入局部探索。"
                : `本次找到 ${graphMeta.matched_nodes} 个直接匹配节点，并展示其相关邻居；可缩小关键词或调整筛选条件。`}
            </div>
          )}
          <div ref={container} className="h-[620px] w-full" />
        </Card>
        <Card className="h-fit p-5">
          <h2 className="text-sm font-semibold">节点详情</h2>
          {selected ? (
            <div className="mt-4 space-y-2 text-sm">
              <p className="font-semibold">{selected.label}</p>
              <p className="text-xs text-[var(--muted)]">类型：{selected.type}</p>
              <p className="text-xs text-[var(--muted)]">
                source_time：{selected.source_time || "未知"}
              </p>
              <p className="break-all text-xs text-[var(--muted)]">
                {selected.page_id
                  ? `Wiki 页面 ${selected.page_id}`
                  : selected.document_id
                    ? `文档 ${selected.document_id}`
                    : "主题节点"}
              </p>
              {selected.page_id && (
                <Link
                  className="text-xs font-medium text-violet-500"
                  to={`/wiki?kb=${knowledgeBaseId}&page=${selected.page_id}`}
                >
                  在 Wiki 中查看
                </Link>
              )}
              {selected.document_id && (
                <Link
                  className="block text-xs font-medium text-violet-500"
                  to={`/documents/${selected.document_id}`}
                >
                  查看来源文档
                </Link>
              )}
            </div>
          ) : selectedEdge ? (
            <div className="mt-4 space-y-2 text-sm">
              <p className="font-semibold">{selectedEdge.type}</p>
              <p className="text-xs leading-6 text-[var(--muted)]">
                {selectedEdge.evidence}
              </p>
              <p className="text-xs text-[var(--muted)]">
                source_time：{selectedEdge.source_time || "未知"}
              </p>
              {selectedEdge.source_document_id && (
                <Link
                  className="text-xs font-medium text-violet-500"
                  to={`/documents/${selectedEdge.source_document_id}`}
                >
                  查看关系证据文档
                </Link>
              )}
            </div>
          ) : (
            <p className="mt-4 text-sm text-[var(--muted)]">
              点击节点或关系查看来源信息。
            </p>
          )}
        </Card>
      </div>
    </>
  );
}
