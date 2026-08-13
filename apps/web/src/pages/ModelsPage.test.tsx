import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import type { ProviderModel } from "../lib/types";
import { useAuthStore } from "../stores/auth";
import { ModelsPage } from "./ModelsPage";

const model: ProviderModel = {
  id: "model-1",
  name: "产业链 Rerank",
  kind: "rerank",
  provider: "dashscope",
  base_url: "https://dashscope.aliyuncs.com/compatible-api/v1",
  model_name: "qwen3-rerank",
  timeout_seconds: 60,
  max_concurrency: 5,
  embedding_dimensions: null,
  config: {},
  is_enabled: true,
  has_api_key: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function jsonResponse(data: unknown, status = 200) {
  return new Response(status === 204 ? null : JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ModelsPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ModelsPage management", () => {
  it("edits a model without replacing its saved API key", async () => {
    useAuthStore.setState({ accessToken: "test-token", ready: true });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (_input, init) => {
        if (init?.method === "PATCH") return jsonResponse({ ...model, name: "新名称" });
        return jsonResponse([model]);
      },
    );

    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /编辑/ }));
    expect(screen.getByRole("heading", { name: "编辑模型" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("新 API Key（留空保留）")).toHaveValue("");

    const name = screen.getByLabelText("配置名称");
    await user.clear(name);
    await user.type(name, "新名称");
    await user.click(screen.getByRole("button", { name: "保存修改" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/models/model-1",
        expect.objectContaining({ method: "PATCH" }),
      ),
    );
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    const body = JSON.parse(String(patchCall?.[1]?.body)) as Record<string, unknown>;
    expect(body.name).toBe("新名称");
    expect(body.api_key).toBeNull();
    expect(body.clear_api_key).toBe(false);
  });

  it("requires confirmation before deleting a model", async () => {
    useAuthStore.setState({ accessToken: "test-token", ready: true });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (_input, init) => {
        if (init?.method === "DELETE") return jsonResponse(null, 204);
        return jsonResponse([model]);
      },
    );

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /删除/ }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/models/model-1",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
  });

  it("shows safe provider diagnostics when a connection test fails", async () => {
    useAuthStore.setState({ accessToken: "test-token", ready: true });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        return jsonResponse({
          ok: false,
          kind: "rerank",
          latency_ms: 321,
          details: {
            message_zh: "不支持 dimensions 参数",
            message: "dimensions is not supported",
            http_status: 400,
            provider_code: "400001",
            endpoint: "https://tokenhub.tencentmaas.com/v1/embeddings",
            provider_request_id: "vendor-request-id",
          },
        });
      }
      return jsonResponse([model]);
    });

    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "连接测试" }));

    expect(await screen.findByText("不支持 dimensions 参数")).toBeInTheDocument();
    expect(screen.getByText("HTTP 400 · 厂商错误码 400001")).toBeInTheDocument();
    expect(
      screen.getByText("请求地址：https://tokenhub.tencentmaas.com/v1/embeddings"),
    ).toBeInTheDocument();
    expect(screen.getByText("厂商 Request ID：vendor-request-id")).toBeInTheDocument();
  });
});
