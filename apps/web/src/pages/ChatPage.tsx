import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Download, Pencil, Plus, Send, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { MarkdownContent } from "../components/MarkdownContent";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { authenticatedFetch, api, download } from "../lib/api";
import type {
  ChatSession,
  ChatSessionDetail,
  KnowledgeBase,
  SearchCitation,
} from "../lib/types";

type TurnCitation = {
  citation_number: number;
  chunk_id: string | null;
  document_id: string | null;
  document_name: string;
  page_from: number | null;
  page_to: number | null;
  section: string | null;
  original_text: string;
  source_time: string | null;
};

type Turn = {
  id: string;
  query: string;
  answer: string;
  citations: TurnCitation[];
  status: "streaming" | "completed" | "error" | "stopped";
  error?: string;
};

function parseEvent(block: string): { event: string; data: unknown } | null {
  const event = block.match(/^event:\s*(.+)$/m)?.[1];
  const data = block.match(/^data:\s*(.+)$/m)?.[1];
  if (!event || !data) return null;
  return { event, data: JSON.parse(data) as unknown };
}

export function ChatPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [knowledgeBaseIds, setKnowledgeBaseIds] = useState<string[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const { data: knowledgeBases = [] } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api<KnowledgeBase[]>("/knowledge-bases"),
  });
  const { data: sessions = [] } = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => api<ChatSession[]>("/chat-sessions"),
  });
  const { data: selectedSession } = useQuery({
    queryKey: ["chat-session", sessionId],
    queryFn: () => api<ChatSessionDetail>(`/chat-sessions/${sessionId}`),
    enabled: sessionId !== null && !isStreaming,
  });

  useEffect(() => {
    if (!selectedSession || selectedSession.id !== sessionId) return;
    const restored: Turn[] = [];
    for (const message of selectedSession.messages) {
      if (message.role === "user") {
        restored.push({
          id: message.id,
          query: message.content,
          answer: "",
          citations: [],
          status: "completed",
        });
      } else if (message.role === "assistant") {
        const turn = restored.at(-1);
        const citations = message.citations.map((citation) => ({
          ...citation,
          document_name: citation.document_title,
        }));
        if (turn && !turn.answer) {
          turn.answer = message.content;
          turn.citations = citations;
        } else {
          restored.push({
            id: message.id,
            query: "续答",
            answer: message.content,
            citations,
            status: "completed",
          });
        }
      }
    }
    setTurns(restored);
  }, [selectedSession, sessionId]);

  function patchTurn(id: string, update: Partial<Turn>) {
    setTurns((items) =>
      items.map((item) => (item.id === id ? { ...item, ...update } : item)),
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = query.trim();
    if (!text || knowledgeBaseIds.length === 0 || abort.current) return;
    setQuery("");
    const turnId = crypto.randomUUID();
    setTurns((items) => [
      ...items,
      {
        id: turnId,
        query: text,
        answer: "",
        citations: [],
        status: "streaming",
      },
    ]);
    const controller = new AbortController();
    abort.current = controller;
    setIsStreaming(true);
    try {
      const response = await authenticatedFetch("/rag/stream", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          query: text,
          session_id: sessionId,
          knowledge_base_ids: knowledgeBaseIds,
          document_ids: [],
          tag_ids: [],
          top_k: 12,
        }),
      });
      if (!response.ok || !response.body) {
        throw new Error(`问答请求失败（${response.status}）`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answer = "";
      let citations: SearchCitation[] = [];
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const message = parseEvent(block);
          if (!message) continue;
          if (message.event === "assistant.delta") {
            answer += (message.data as { delta: string }).delta;
            patchTurn(turnId, { answer });
          } else if (message.event === "citation") {
            citations = [...citations, message.data as SearchCitation];
            patchTurn(turnId, {
              citations: citations.map((citation) => ({
                ...citation,
                chunk_id: citation.chunk_id,
              })),
            });
          } else if (message.event === "completed") {
            setSessionId((message.data as { session_id: string }).session_id);
            patchTurn(turnId, { status: "completed" });
            void queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
          } else if (message.event === "error") {
            throw new Error((message.data as { message: string }).message);
          }
        }
        if (done) break;
      }
    } catch (error) {
      if (controller.signal.aborted) {
        patchTurn(turnId, { status: "stopped" });
      } else {
        patchTurn(turnId, {
          status: "error",
          error: error instanceof Error ? error.message : "问答失败",
        });
      }
    } finally {
      abort.current = null;
      setIsStreaming(false);
    }
  }

  async function renameSession(item: ChatSession) {
    const title = window.prompt("新的对话名称", item.title)?.trim();
    if (!title || title === item.title) return;
    await api(`/chat-sessions/${item.id}`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    });
    await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
  }

  async function removeSession(item: ChatSession) {
    if (!window.confirm(`确认删除对话“${item.title}”？此操作不可恢复。`)) return;
    await api(`/chat-sessions/${item.id}`, { method: "DELETE" });
    if (sessionId === item.id) {
      setSessionId(null);
      setTurns([]);
    }
    await queryClient.invalidateQueries({ queryKey: ["chat-sessions"] });
  }

  return (
    <>
      <PageHeader
        eyebrow="Grounded Chat"
        title="知识问答"
        description="多轮上下文、结构化时间理解和逐条引用都由服务端执行。"
      />
      <div className="grid gap-5 xl:grid-cols-[230px_minmax(0,1fr)_260px]">
        <Card className="h-fit max-h-[calc(100vh-12rem)] overflow-auto p-3">
          <Button
            className="w-full"
            variant="secondary"
            onClick={() => {
              setSessionId(null);
              setTurns([]);
            }}
          >
            <Plus size={15} />
            新建对话
          </Button>
          <div className="mt-3 space-y-1">
            {sessions.map((item) => (
              <div
                key={item.id}
                className={`group rounded-xl p-2 ${
                  item.id === sessionId ? "bg-violet-500/10" : "hover:bg-[var(--surface-hover)]"
                }`}
              >
                <button
                  className="w-full truncate text-left text-sm"
                  onClick={() => setSessionId(item.id)}
                  type="button"
                >
                  {item.title}
                </button>
                <div className="mt-1 hidden gap-1 group-hover:flex">
                  <button
                    aria-label="重命名对话"
                    className="rounded p-1 text-[var(--muted)] hover:text-[var(--ink)]"
                    onClick={() => void renameSession(item)}
                    type="button"
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    aria-label="导出对话"
                    className="rounded p-1 text-[var(--muted)] hover:text-[var(--ink)]"
                    onClick={() =>
                      void download(`/chat-sessions/${item.id}/export`, `${item.title}.md`)
                    }
                    type="button"
                  >
                    <Download size={13} />
                  </button>
                  <button
                    aria-label="删除对话"
                    className="rounded p-1 text-[var(--muted)] hover:text-red-500"
                    onClick={() => void removeSession(item)}
                    type="button"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Card>
        <section className="space-y-5">
          {turns.length === 0 && (
            <Card className="flex min-h-80 flex-col items-center justify-center p-8 text-center">
              <BookOpen className="mb-4 text-violet-500" />
              <h2 className="font-semibold">从知识中得到可验证的回答</h2>
              <p className="mt-2 text-sm text-[var(--muted)]">
                提问中包含时间时，系统会解析为 source_time 过滤条件。
              </p>
            </Card>
          )}
          {turns.map((turn) => (
            <div key={turn.id} className="space-y-3">
              <div className="ml-auto max-w-3xl rounded-2xl bg-violet-600 px-5 py-3 text-sm text-white">
                {turn.query}
              </div>
              <Card className="max-w-4xl p-6">
                <MarkdownContent>
                  {turn.answer ||
                    (turn.status === "streaming" ? "正在检索与生成…" : "")}
                </MarkdownContent>
                {turn.error && <p className="mt-3 text-sm text-red-500">{turn.error}</p>}
                {turn.citations.length > 0 && (
                  <details className="mt-5 border-t border-[var(--border)] pt-4">
                    <summary className="cursor-pointer text-sm font-medium">
                      {turn.citations.length} 条引用
                    </summary>
                    <div className="mt-3 space-y-3">
                      {turn.citations.map((citation) => (
                        <div
                          key={`${citation.citation_number}-${citation.chunk_id ?? "deleted"}`}
                          className="rounded-xl bg-[var(--surface-hover)] p-3 text-xs leading-6"
                        >
                          <div className="font-semibold">
                            [{citation.citation_number}] {citation.document_name}
                          </div>
                          <div className="text-[var(--muted)]">
                            {citation.section || "未标注章节"} ·{" "}
                            {citation.source_time || "时间未知"}
                          </div>
                          <p className="mt-1 text-[var(--muted)]">
                            {citation.original_text}
                          </p>
                          {citation.document_id && (
                            <Link
                              className="mt-2 inline-block font-medium text-violet-500"
                              to={`/documents/${citation.document_id}${
                                citation.chunk_id ? `?chunk=${citation.chunk_id}` : ""
                              }`}
                            >
                              定位到原文
                            </Link>
                          )}
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </Card>
            </div>
          ))}
          <Card className="sticky bottom-4 p-2 shadow-xl">
            <form className="flex items-end gap-2" onSubmit={submit}>
              <textarea
                aria-label="问题"
                className="min-h-11 flex-1 resize-none rounded-xl border-0 bg-transparent px-4 py-3 text-sm outline-none focus:ring-0"
                placeholder="询问知识库，例如：比较 2023 年和 2025 年的政策变化"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              {isStreaming ? (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => abort.current?.abort()}
                >
                  <Square size={15} />
                  停止
                </Button>
              ) : (
                <Button
                  type="submit"
                  aria-label="发送问题"
                  disabled={knowledgeBaseIds.length === 0 || !query.trim()}
                >
                  <Send size={15} />
                  发送
                </Button>
              )}
            </form>
          </Card>
        </section>
        <Card className="h-fit p-5">
          <h2 className="text-sm font-semibold">知识范围</h2>
          <div className="mt-4 space-y-2">
            {knowledgeBases.map((knowledgeBase) => (
              <label key={knowledgeBase.id} className="flex gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={knowledgeBaseIds.includes(knowledgeBase.id)}
                  onChange={(event) =>
                    setKnowledgeBaseIds((items) =>
                      event.target.checked
                        ? [...items, knowledgeBase.id]
                        : items.filter((id) => id !== knowledgeBase.id),
                    )
                  }
                />
                {knowledgeBase.name}
              </label>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
