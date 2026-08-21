import {
  BookOpenCheck,
  Check,
  Copy,
  Download,
  KeyRound,
  Network,
  PackageOpen,
  Search,
  TimerReset,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { download } from "../lib/api";

const skills = [
  {
    name: "synapsekb-shared",
    description: "认证、知识库选择、权限边界、错误处理与写操作确认。",
    icon: Network,
  },
  {
    name: "synapsekb-rag-search",
    description: "原始检索与 RAG 选择、结构化过滤以及可核验引用。",
    icon: Search,
  },
  {
    name: "synapsekb-temporal-research",
    description: "相对时间解析、时间线检索和跨时期独立比较。",
    icon: TimerReset,
  },
  {
    name: "synapsekb-wiki",
    description: "Wiki 页面、来源、反向链接和局部时间关系图读取。",
    icon: BookOpenCheck,
  },
] as const;

function CodeBlock({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="overflow-hidden rounded-xl border border-white/8 bg-[#15151d] text-white">
      <div className="flex items-center justify-between border-b border-white/8 px-4 py-2 text-[11px] text-zinc-400">
        <span>{label}</span>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-zinc-300 transition hover:bg-white/8 hover:text-white"
          onClick={copy}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 text-xs leading-6 text-cyan-100">
        <code>{value}</code>
      </pre>
    </div>
  );
}

function Step({ number, title, children }: { number: number; title: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-3 sm:grid-cols-[34px_minmax(0,1fr)]">
      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-violet-500/10 text-sm font-semibold text-violet-600 dark:text-violet-300">
        {number}
      </div>
      <div>
        <h3 className="pt-1 text-sm font-semibold">{title}</h3>
        <div className="mt-3 text-sm leading-6 text-[var(--muted)]">{children}</div>
      </div>
    </div>
  );
}

export function SkillsPage() {
  const [platform, setPlatform] = useState<"codex" | "workbuddy">("codex");
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const mcpUrl = useMemo(() => `${window.location.origin}/mcp`, []);
  const codexConfig = `[mcp_servers.synapsekb]\nurl = "${mcpUrl}"\nbearer_token_env_var = "SYNAPSEKB_TOKEN"\ntool_timeout_sec = 120`;

  async function downloadPackage(path: string, filename: string) {
    setDownloadError(null);
    try {
      await download(path, filename);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "Skill 下载失败");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="External Knowledge Skills"
        title="Skill 安装"
        description="让 Codex、WorkBuddy 等外部工具按 SynapseKB 的权限、时间和引用规则使用知识。"
      />

      <Card className="overflow-hidden">
        <div className="flex flex-col gap-5 border-b border-[var(--border)] p-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-base font-semibold">
              <PackageOpen className="text-violet-500" size={20} />
              SynapseKB Skills
            </div>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">
              Skill 只提供工作流规则，不保存 Token，也不能替代 MCP。请同时配置下方的
              Streamable HTTP MCP 连接。
            </p>
          </div>
          <Button onClick={() => downloadPackage("/skills/bundle", "synapsekb-skills.zip")}>
            <Download size={16} />
            下载全部
          </Button>
        </div>
        <div className="grid gap-px bg-[var(--border)] md:grid-cols-2 xl:grid-cols-4">
          {skills.map((skill) => (
            <div key={skill.name} className="bg-[var(--surface)] p-5">
              <skill.icon className="text-cyan-500" size={19} />
              <div className="mt-4 break-all font-mono text-[11px] font-semibold tracking-tight">
                {skill.name}
              </div>
              <p className="mt-2 min-h-12 text-xs leading-5 text-[var(--muted)]">
                {skill.description}
              </p>
              <Button
                className="mt-4"
                variant="secondary"
                size="sm"
                onClick={() =>
                  downloadPackage(`/skills/${skill.name}/download`, `${skill.name}.zip`)
                }
              >
                <Download size={14} />
                单独下载
              </Button>
            </div>
          ))}
        </div>
      </Card>
      {downloadError && <p className="mt-3 text-sm text-red-500">{downloadError}</p>}

      <div className="mt-6 flex w-fit rounded-xl border border-[var(--border)] bg-[var(--surface)] p-1">
        {(["codex", "workbuddy"] as const).map((item) => (
          <button
            key={item}
            type="button"
            className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
              platform === item
                ? "bg-[var(--text)] text-[var(--surface)] shadow-sm"
                : "text-[var(--muted)] hover:text-[var(--text)]"
            }`}
            onClick={() => setPlatform(item)}
          >
            {item === "codex" ? "Codex" : "WorkBuddy"}
          </button>
        ))}
      </div>

      <Card className="mt-4 p-6 sm:p-7">
        <div className="space-y-8">
          <Step number={1} title="创建只读访问令牌">
            <p>
              前往 <Link className="font-medium text-violet-600 hover:underline dark:text-violet-300" to="/tokens">访问令牌</Link>
              ，保留默认只读 Scope。Token 创建后只显示一次，请存入客户端的环境变量或安全凭据区。
            </p>
          </Step>

          <Step number={2} title={platform === "codex" ? "安装四个 Skill" : "上传本地 Skill 包"}>
            {platform === "codex" ? (
              <div className="space-y-3">
                <p>下载全部后，将四个目录解压到用户级 Skill 目录：</p>
                <CodeBlock
                  label="macOS / Linux"
                  value={'mkdir -p "$HOME/.agents/skills"\nunzip synapsekb-skills.zip -d "$HOME/.agents/skills"'}
                />
                <CodeBlock
                  label="Windows PowerShell"
                  value={'New-Item -ItemType Directory -Force "$HOME\\.agents\\skills"\nExpand-Archive .\\synapsekb-skills.zip "$HOME\\.agents\\skills" -Force'}
                />
              </div>
            ) : (
              <div className="space-y-3">
                <p>
                  分别下载上方四个独立 ZIP。在 WorkBuddy 左侧打开“专家・技能・连接器”，选择
                  “添加技能 → 上传技能”，逐个上传并启用。
                </p>
                <p className="rounded-xl bg-amber-500/10 px-4 py-3 text-xs text-amber-700 dark:text-amber-300">
                  WorkBuddy 按单个 Skill 包导入，请使用“单独下载”，不要直接上传合集 ZIP。
                </p>
              </div>
            )}
          </Step>

          <Step number={3} title="配置 Streamable HTTP MCP">
            <div className="space-y-3">
              <p>
                MCP 地址已按当前页面自动生成。认证方式选择 Bearer Token，值使用第 1 步创建的
                <code className="mx-1 rounded bg-[var(--surface-hover)] px-1.5 py-0.5 text-xs">skbp_...</code>
                令牌。
              </p>
              <CodeBlock label="MCP URL" value={mcpUrl} />
              {platform === "codex" ? (
                <>
                  <p>
                    也可以把以下内容加入
                    <code className="mx-1 rounded bg-[var(--surface-hover)] px-1.5 py-0.5 text-xs">~/.codex/config.toml</code>
                    ，并在启动 Codex 的环境中设置
                    <code className="mx-1 rounded bg-[var(--surface-hover)] px-1.5 py-0.5 text-xs">SYNAPSEKB_TOKEN</code>。
                  </p>
                  <CodeBlock label="Codex config.toml" value={codexConfig} />
                </>
              ) : (
                <p>
                  在 WorkBuddy 的连接器/MCP 管理中新增服务，传输方式选择 Streamable HTTP，
                  填入上面的 URL 和 Bearer Token。
                </p>
              )}
            </div>
          </Step>

          <Step number={4} title="重启并验证">
            <p>
              重启客户端后，先调用 <code className="rounded bg-[var(--surface-hover)] px-1.5 py-0.5 text-xs">kb_list</code>
              确认可见知识库，再尝试“在指定知识库中检索并保留引用”。如果返回 403，请检查 App
              知识库权限与 Token Scope，不要通过扩大 Scope 绕过权限。
            </p>
          </Step>
        </div>
      </Card>

      <div className="mt-5 flex items-start gap-3 rounded-2xl border border-cyan-500/20 bg-cyan-500/5 p-4 text-sm leading-6 text-[var(--muted)]">
        <KeyRound className="mt-0.5 shrink-0 text-cyan-500" size={18} />
        <p>
          当前地址为 <span className="font-mono text-xs text-[var(--text)]">{mcpUrl}</span>。
          公网部署应使用 HTTPS；普通 HTTP 会明文传输 Bearer Token，不适合作为正式生产连接。
        </p>
      </div>
    </>
  );
}
