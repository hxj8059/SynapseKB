import {
  BookOpen,
  Bot,
  Boxes,
  KeyRound,
  LibraryBig,
  MessageSquareText,
  LogOut,
  Moon,
  Network,
  Search,
  ScanText,
  Cloud,
  Settings2,
  Sun,
  ListChecks,
  Users,
} from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { api } from "../lib/api";
import { cn } from "../lib/cn";
import { useAuthStore } from "../stores/auth";
import { usePreferences } from "../stores/preferences";
import { Logo } from "./Logo";
import { Button } from "./ui/button";

const primary = [
  { to: "/", label: "概览", icon: Boxes },
  { to: "/knowledge-bases", label: "知识库", icon: LibraryBig },
  { to: "/search", label: "知识检索", icon: Search },
  { to: "/chat", label: "知识问答", icon: MessageSquareText },
  { to: "/agents", label: "分析 Agent", icon: Bot },
  { to: "/wiki", label: "Wiki", icon: BookOpen },
  { to: "/wiki/graph", label: "Wiki 关系图", icon: Network },
];

const admin = [
  { to: "/admin/models", label: "模型设置", icon: Settings2 },
  { to: "/admin/ocr", label: "OCR 设置", icon: ScanText },
  { to: "/admin/storage", label: "对象存储", icon: Cloud },
  { to: "/admin/users", label: "用户管理", icon: Users },
  { to: "/admin/tasks", label: "任务中心", icon: ListChecks },
];

export function AppShell() {
  const user = useAuthStore((state) => state.user);
  const clear = useAuthStore((state) => state.clear);
  const { theme, toggleTheme } = usePreferences();
  const navigate = useNavigate();

  async function logout() {
    await api<void>("/auth/logout", { method: "POST" }).catch(() => undefined);
    clear();
    navigate("/login", { replace: true });
  }

  return (
    <div className="min-h-screen bg-[var(--canvas)] text-[var(--text)]">
      <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--sidebar)]/95 px-4 py-3 backdrop-blur lg:hidden">
        <div className="flex items-center justify-between">
          <Logo />
          <div className="flex items-center gap-1">
            <Button
              aria-label="切换主题"
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
            >
              {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            </Button>
            <Button aria-label="退出登录" variant="ghost" size="icon" onClick={logout}>
              <LogOut size={17} />
            </Button>
          </div>
        </div>
        <nav className="mt-3 flex gap-1 overflow-x-auto pb-1">
          {[...primary, ...(user?.role === "admin" ? admin : [])].map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/" || item.to === "/wiki"}
              className={({ isActive }) =>
                cn(
                  "flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium",
                  isActive
                    ? "bg-violet-500/10 text-violet-600 dark:text-violet-300"
                    : "text-[var(--muted)]",
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
          <NavLink
            to="/tokens"
            className="flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs text-[var(--muted)]"
          >
            <KeyRound className="h-4 w-4" />
            访问令牌
          </NavLink>
        </nav>
      </header>
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-[var(--border)] bg-[var(--sidebar)] px-4 py-5 lg:block">
        <Logo className="px-2" />
        <nav className="mt-10 space-y-1">
          {[...primary, ...(user?.role === "admin" ? admin : [])].map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/" || item.to === "/wiki"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                  isActive
                    ? "bg-violet-500/10 text-violet-600 dark:text-violet-300"
                    : "text-[var(--muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
                )
              }
            >
              <item.icon className="h-4.5 w-4.5" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute inset-x-4 bottom-5 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="mb-3 min-w-0 px-1">
            <div className="truncate text-sm font-medium">{user?.display_name}</div>
            <div className="mt-0.5 truncate text-xs text-[var(--muted)]">{user?.email}</div>
          </div>
          <div className="flex items-center justify-between">
            <Button
              aria-label="切换主题"
              variant="ghost"
              size="icon"
              onClick={toggleTheme}
            >
              {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            </Button>
            <NavLink to="/tokens">
              <Button aria-label="MCP Token" variant="ghost" size="icon">
                <KeyRound size={17} />
              </Button>
            </NavLink>
            <Button aria-label="退出登录" variant="ghost" size="icon" onClick={logout}>
              <LogOut size={17} />
            </Button>
          </div>
        </div>
      </aside>
      <main className="min-h-screen lg:pl-64">
        <div className="mx-auto max-w-[1440px] px-5 py-6 sm:px-8 lg:px-10 lg:py-9">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
