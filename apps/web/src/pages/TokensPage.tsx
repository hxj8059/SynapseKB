import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Trash2 } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "../components/PageHeader";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { DateTimePicker } from "../components/ui/date-time-picker";
import { Input } from "../components/ui/input";
import { api } from "../lib/api";
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
                size="icon"
                onClick={() => navigator.clipboard.writeText(create.data.token)}
              >
                <Copy size={16} />
              </Button>
            </div>
          </div>
        )}
      </Card>
      <Card className="mt-6 overflow-hidden">
        <div className="border-b border-[var(--border)] px-5 py-4 text-sm font-semibold">
          已创建令牌
        </div>
        <div className="divide-y divide-[var(--border)]">
          {tokens.map((token) => (
            <div
              key={token.id}
              className="grid gap-3 px-5 py-4 md:grid-cols-[1fr_1fr_auto] md:items-center"
            >
              <div>
                <div className="text-sm font-semibold">{token.name}</div>
                <div className="mt-1 font-mono text-xs text-[var(--muted)]">
                  {token.token_prefix}…
                </div>
              </div>
              <div className="text-xs leading-5 text-[var(--muted)]">
                {token.scopes.join(" · ")}
                <br />
                最近使用：{token.last_used_at || "从未"}
              </div>
              {!token.revoked_at && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="撤销令牌"
                  onClick={() => {
                    if (window.confirm(`确认撤销令牌“${token.name}”？`)) {
                      revoke.mutate(token.id);
                    }
                  }}
                >
                  <Trash2 size={16} />
                </Button>
              )}
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
