import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type { Agent, AgentRun } from "../lib/types";
import { useAuthStore } from "../stores/auth";
import { AgentsPage } from "./AgentsPage";

const agent: Agent = {
  id: "agent-1",
  name: "产业研究 Agent",
  avatar: null,
  description: "读取产业知识库",
  system_prompt: "仅依据知识库回答",
  chat_model_id: "model-1",
  visibility: "all",
  max_steps: 8,
  max_tokens: 12000,
  tool_decision_max_tokens: 4000,
  timeout_seconds: 300,
  recommended_questions: [],
  is_enabled: true,
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
};

const run: AgentRun = {
  id: "run-1",
  agent_id: agent.id,
  user_id: "user-1",
  session_id: null,
  status: "completed",
  query: "分析 AI 服务器产业链",
  resolved_time_summary: null,
  result: "## 结论\n\n产业链保持增长。[1]",
  citations: [],
  error_summary: null,
  started_at: "2026-08-20T09:00:00Z",
  finished_at: "2026-08-20T09:01:00Z",
  created_at: "2026-08-20T09:00:00Z",
  updated_at: "2026-08-20T09:01:00Z",
};

function response(data: unknown) {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AgentsPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentsPage history", () => {
  it("lists prior runs and reopens the full answer", async () => {
    useAuthStore.setState({
      accessToken: "test-token",
      ready: true,
      user: {
        id: "user-1",
        email: "user@example.com",
        display_name: "测试用户",
        role: "user",
        is_active: true,
        timezone: "Asia/Shanghai",
        created_at: "2026-01-01T00:00:00Z",
      },
    });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/agents/agent-1/runs?")) {
        return response({
          items: [
            {
              id: run.id,
              agent_id: run.agent_id,
              status: run.status,
              query: run.query,
              error_summary: null,
              started_at: run.started_at,
              finished_at: run.finished_at,
              created_at: run.created_at,
              updated_at: run.updated_at,
            },
          ],
          total: 1,
          limit: 12,
          offset: 0,
        });
      }
      if (url.endsWith("/agents/runs/run-1")) return response(run);
      if (url.endsWith("/agents")) return response([agent]);
      if (url.endsWith("/knowledge-bases")) return response([]);
      throw new Error(`Unexpected request: ${url}`);
    });

    renderPage();
    const historyItem = await screen.findByRole("button", {
      name: `打开历史：${run.query}`,
    });
    await userEvent.click(historyItem);

    expect(await screen.findByRole("heading", { name: "结论" })).toBeInTheDocument();
    expect(screen.getAllByText(run.query).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("产业链保持增长。[1]")).toBeInTheDocument();
  });
});
