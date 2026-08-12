import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, LibraryBig, Search, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { Card } from "../components/ui/card";
import { api } from "../lib/api";
import type { KnowledgeBase } from "../lib/types";
import { useAuthStore } from "../stores/auth";

export function HomePage() {
  const user = useAuthStore((state) => state.user);
  const { data = [] } = useQuery({
    queryKey: ["knowledge-bases"],
    queryFn: () => api<KnowledgeBase[]>("/knowledge-bases"),
  });

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title={`你好，${user?.display_name ?? ""}`}
        description="从一条可验证的答案开始，沿着引用回到知识本身。"
      />
      <section className="grid gap-5 lg:grid-cols-[1.35fr_.65fr]">
        <Card className="relative min-h-72 overflow-hidden bg-[#14141c] p-8 text-white">
          <div className="absolute right-[-8%] top-[-24%] h-72 w-72 rounded-full bg-violet-500/25 blur-3xl" />
          <div className="absolute bottom-[-35%] left-[38%] h-64 w-64 rounded-full bg-cyan-400/15 blur-3xl" />
          <div className="relative flex h-full flex-col justify-between">
            <Sparkles className="h-6 w-6 text-cyan-300" />
            <div>
              <h2 className="max-w-lg text-3xl font-semibold tracking-[-.04em]">
                问一个带时间的问题，
                <br />
                得到一份有出处的答案。
              </h2>
              <Link
                to="/search"
                className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-cyan-300"
              >
                开始检索 <ArrowUpRight size={16} />
              </Link>
            </div>
          </div>
        </Card>
        <div className="grid gap-5">
          <Card className="p-6">
            <LibraryBig className="mb-8 h-5 w-5 text-violet-500" />
            <div className="text-4xl font-semibold tracking-[-.04em]">{data.length}</div>
            <div className="mt-1 text-sm text-[var(--muted)]">可访问知识库</div>
          </Card>
          <Card className="p-6">
            <Search className="mb-8 h-5 w-5 text-cyan-500" />
            <div className="text-sm font-medium">时间检索默认字段</div>
            <div className="mt-2 font-mono text-sm text-[var(--muted)]">source_time</div>
          </Card>
        </div>
      </section>
      <section className="mt-9">
        <h2 className="mb-4 text-sm font-semibold">最近知识库</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.slice(0, 6).map((knowledgeBase) => (
            <Link key={knowledgeBase.id} to={`/knowledge-bases/${knowledgeBase.id}`}>
              <Card className="group h-full p-5 transition hover:-translate-y-0.5 hover:border-violet-400/50">
                <div className="mb-8 flex items-start justify-between">
                  <div className="rounded-xl bg-violet-500/10 p-2.5 text-violet-500">
                    <LibraryBig size={18} />
                  </div>
                  <ArrowUpRight
                    size={16}
                    className="text-[var(--muted)] transition group-hover:text-violet-500"
                  />
                </div>
                <h3 className="font-semibold">{knowledgeBase.name}</h3>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-[var(--muted)]">
                  {knowledgeBase.description || "暂无描述"}
                </p>
              </Card>
            </Link>
          ))}
        </div>
      </section>
    </>
  );
}
