import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, Copy, KeyRound, Trash2 } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { DateTimePicker } from "../components/ui/date-time-picker";
import { Input } from "../components/ui/input";
import { api } from "../lib/api";
import { copyText } from "../lib/clipboard";
import { useAuthStore } from "../stores/auth";

const defaultScopes = [
  "kb:read",
  "document:read",
  "search:read",
  "agent:run",
  "wiki:read",
];
const allScopes = [...defaultScopes, "document:write", "wiki:admin"];

type CreatedToken = {
  id: string;
  name: string;
  token: string;
  scopes: string[];
  expires_at: string | null;
};

type StoredToken = {
  id: string;
  name: string;
  token_prefix: string;
  scopes: string[];
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
};

export function TokensPage() {
  const user = useAuthStore((state) => state.user);
  const client = useQueryClient();
  const [name, setName] = useState("我的只读工具");
  const [expiresAt, setExpiresAt] = useState("");
  const [scopes, setScopes] = useState(defaultScopes);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "error">("idle");
  const { data: tokens = [] } = useQuery({
    queryKey: ["tokens"],
    queryFn: () => api<StoredToken[]>("/tokens"),
  });
  const create = useMutation({
    mutationFn: () =>
      api<CreatedToken>("/tokens", {
        method: "POST",
        body: JSON.stringify({
          name,
          scopes,
          expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        }),
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["tokens"] }),
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api<void>(`/tokens/${id}`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["tokens"] }),
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      api<void>(`/tokens/${id}/record`, { method: "DELETE" }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["tokens"] }),
  });

  async function copyCreatedToken() {
    if (!create.data) return;
    try {
      await copyText(create.data.token);
      setCopyStatus("copied");
      window.setTimeout(() => setCopyStatus("idle"), 1800);
    } catch {
      setCopyStatus("error");
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="MCP Access"
        title="访问令牌"
        description="令牌只在创建时展示一次。Scope 不会绕过你在 App 中的知识库权限。"
      />
      <Card className="max-w-2xl p-6">
        <KeyRound className="mb-6 text-violet-500" />
        <div className="grid gap-3 sm:grid-cols-[1fr_220px_auto]">
          <Input value={name} onChange={(event) => setName(event.target.value)} />
          <DateTimePicker
            ariaLabel="令牌过期时间"
            value={expiresAt}
            onValueChange={setExpiresAt}
            placeholder="过期时间（可选）"
          />
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            创建令牌
          </Button>
        </div>
        <div className="mt-4 flex flex-wrap gap-3 text-xs text-[var(--muted)]">
          {allScopes.map((scope) => {
            const writeScope = ["document:write", "wiki:admin"].includes(scope);
            return (
              <label key={scope} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={scopes.includes(scope)}
                  disabled={writeScope && user?.role !== "admin"}
                  onChange={(event) =>
                    setScopes((current) =>
                      event.target.checked
                        ? [...current, scope]
                        : current.filter((item) => item !== scope),
                    )
                  }
                />
                {scope}
              </label>
            );
          })}
        </div>
        {scopes.some((scope) => ["document:write", "wiki:admin"].includes(scope)) && (
          <p className="mt-3 rounded-lg bg-amber-500/10 p-2 text-xs text-amber-700 dark:text-amber-300">
            该令牌包含写 Scope；实际写操作仍要求管理员身份和资源权限。
          </p>
        )}
        {create.error && <p className="mt-3 text-sm text-red-500">{create.error.message}</p>}
        {create.data && (
          <div className="mt-6 rounded-xl bg-[#15151d] p-4 text-white">
            <div className="mb-2 text-xs text-zinc-400">请现在复制，关闭后无法再次查看</div>
            <div className="flex items-center gap-3">
              <code className="min-w-0 flex-1 break-all text-xs text-cyan-300">
                {create.data.token}
              </code>
              <Button
                variant="ghost"
                size="sm"
                className="text-zinc-200 hover:bg-white/10 hover:text-white"
                aria-label="复制访问令牌"
                onClick={copyCreatedToken}
              >
                {copyStatus === "copied" ? <Check size={16} /> : <Copy size={16} />}
                {copyStatus === "copied" ? "已复制" : "复制"}
              </Button>
            </div>
            {copyStatus === "error" && (
              <p className="mt-3 text-xs text-red-300">
                自动复制失败，请手动选择上方令牌并复制。生产环境建议使用 HTTPS。
              </p>
            )}
          </div>
        )}
      </Card>
      <Card className="mt-6 overflow-hidden">
        <div className="border-b border-[var(--border)] px-5 py-4 text-sm font-semibold">
          已创建令牌
        </div>
        <div className="divide-y divide-[var(--border)]">
          {tokens.map((token) => {
            const expired = Boolean(
              token.expires_at && new Date(token.expires_at).getTime() <= Date.now(),
            );
            const inactive = Boolean(token.revoked_at) || expired;
            return (
              <div
                key={token.id}
                className="grid gap-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-center"
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">{token.name}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        token.revoked_at
                          ? "bg-zinc-500/10 text-zinc-500"
                          : expired
                            ? "bg-amber-500/10 text-amber-600 dark:text-amber-300"
                            : "bg-emerald-500/10 text-emerald-600 dark:text-emerald-300"
                      }`}
                    >
                      {token.revoked_at ? "已撤销" : expired ? "已过期" : "有效"}
                    </span>
                  </div>
                  <div className="mt-1 font-mono text-xs text-[var(--muted)]">
                    {token.token_prefix}…
                  </div>
                </div>
                <div className="text-xs leading-5 text-[var(--muted)]">
                  {token.scopes.join(" · ")}
                  <br />
                  最近使用：{token.last_used_at || "从未"}
                </div>
                {!inactive ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={revoke.isPending}
                    onClick={() => {
                      if (window.confirm(`确认撤销令牌“${token.name}”？撤销后立即失效。`)) {
                        revoke.mutate(token.id);
                      }
                    }}
                  >
                    <Ban size={15} />
                    撤销
                  </Button>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-red-500 hover:text-red-600"
                    disabled={remove.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `确认删除令牌“${token.name}”的记录？审计日志仍会保留。`,
                        )
                      ) {
                        remove.mutate(token.id);
                      }
                    }}
                  >
                    <Trash2 size={15} />
                    删除记录
                  </Button>
                )}
              </div>
            );
          })}
        </div>
        {(revoke.error || remove.error) && (
          <p className="border-t border-[var(--border)] px-5 py-3 text-sm text-red-500">
            {(revoke.error || remove.error)?.message}
          </p>
        )}
      </Card>
    </>
  );
}
