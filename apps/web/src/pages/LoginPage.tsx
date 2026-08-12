import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { Logo } from "../components/Logo";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Input } from "../components/ui/input";
import type { AuthResponse } from "../lib/types";
import { useAuthStore } from "../stores/auth";

export function LoginPage() {
  const user = useAuthStore((state) => state.user);
  const setSession = useAuthStore((state) => state.setSession);
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to="/" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        const detail = (await response.json().catch(() => null)) as
          | { detail?: string }
          | null;
        throw new Error(detail?.detail ?? "登录失败");
      }
      const data = (await response.json()) as AuthResponse;
      setSession(data.access_token, data.user);
      navigate("/", { replace: true });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen bg-[var(--canvas)] lg:grid-cols-[1.08fr_.92fr]">
      <section className="relative hidden overflow-hidden bg-[#111118] p-16 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -right-40 top-1/4 h-96 w-96 rounded-full bg-violet-600/25 blur-3xl" />
        <div className="absolute bottom-8 left-1/4 h-72 w-72 rounded-full bg-cyan-400/15 blur-3xl" />
        <Logo className="[--text:white] [--muted:#a2a2b4]" />
        <div className="relative max-w-xl">
          <p className="mb-5 text-sm font-medium tracking-[.2em] text-cyan-300">
            PRIVATE KNOWLEDGE, CONNECTED.
          </p>
          <h1 className="text-5xl font-semibold leading-[1.08] tracking-[-.045em]">
            让知识之间的连接，
            <br />
            真正产生触发。
          </h1>
          <p className="mt-7 max-w-lg text-base leading-7 text-zinc-400">
            触智把文档、时间、引用和洞察组织成一套可追溯的私有知识系统。
          </p>
        </div>
        <div className="relative text-xs text-zinc-500">SynapseKB · 触智</div>
      </section>
      <section className="flex items-center justify-center px-6 py-12">
        <Card className="w-full max-w-md border-0 bg-transparent p-2 shadow-none sm:p-8">
          <Logo className="mb-12 lg:hidden" />
          <div className="mb-8">
            <h2 className="text-3xl font-semibold tracking-[-.035em]">欢迎回来</h2>
            <p className="mt-2 text-sm text-[var(--muted)]">登录你的私有知识空间</p>
          </div>
          <form className="space-y-5" onSubmit={submit}>
            <label className="block">
              <span className="mb-2 block text-sm font-medium">邮箱</span>
              <Input
                autoComplete="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label className="block">
              <span className="mb-2 block text-sm font-medium">密码</span>
              <Input
                autoComplete="current-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            {error && (
              <p role="alert" className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-600">
                {error}
              </p>
            )}
            <Button className="mt-2 w-full" disabled={loading} type="submit">
              {loading ? "正在登录…" : "登录"}
            </Button>
          </form>
        </Card>
      </section>
    </main>
  );
}
