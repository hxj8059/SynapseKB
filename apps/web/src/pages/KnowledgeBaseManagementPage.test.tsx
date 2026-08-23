import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import type {
  KnowledgeBaseDeletionJob,
  KnowledgeBaseManagementItem,
} from "../lib/types";
import { useAuthStore } from "../stores/auth";
import { KnowledgeBaseManagementPage } from "./KnowledgeBaseManagementPage";

const item: KnowledgeBaseManagementItem = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "产业研究",
  description: "产业链资料",
  visibility: "users",
  lifecycle_status: "active",
  document_count: 12,
  ready_document_count: 11,
  total_size_bytes: 1024 * 1024,
  created_at: "2026-08-20T08:00:00Z",
  updated_at: "2026-08-20T08:00:00Z",
  deletion_job: null,
};

const job: KnowledgeBaseDeletionJob = {
  id: "22222222-2222-4222-8222-222222222222",
  knowledge_base_id: item.id,
  knowledge_base_snapshot_id: item.id,
  knowledge_base_name: item.name,
  status: "queued",
  stage: "queued",
  progress: 0,
  document_count: 12,
  total_object_count: 24,
  deleted_object_count: 0,
  error_summary: null,
  created_at: "2026-08-23T08:00:00Z",
  updated_at: "2026-08-23T08:00:00Z",
  finished_at: null,
};

function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
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
        <KnowledgeBaseManagementPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("KnowledgeBaseManagementPage", () => {
  it("requires the exact knowledge-base name before scheduling deletion", async () => {
    useAuthStore.setState({ accessToken: "test-token", ready: true });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(
      async (_input, init) => {
        if (init?.method === "DELETE") return response(job, 202);
        return response([item]);
      },
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "删除" }));
    const confirmButton = screen.getByRole("button", { name: "确认永久删除" });
    expect(confirmButton).toBeDisabled();
    await user.type(screen.getByLabelText("输入知识库名称以确认"), item.name);
    expect(confirmButton).toBeEnabled();
    await user.click(confirmButton);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/v1/knowledge-bases/${item.id}`,
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    const request = fetchMock.mock.calls.find(([, init]) => init?.method === "DELETE");
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      confirmation_name: item.name,
    });
  });
});
