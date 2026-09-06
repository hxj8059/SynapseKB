import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import type { User } from "../lib/types";
import { useAuthStore } from "../stores/auth";
import { UsersPage } from "./UsersPage";

const root: User = { id: "root", email: "root@example.com", display_name: "超级管理员", role: "super_admin", is_active: true, approval_status: "approved", timezone: "Asia/Shanghai", created_at: "2026-09-01T00:00:00Z" };
const admin: User = { ...root, id: "admin", email: "admin@example.com", display_name: "管理员", role: "admin" };
const pending: User = { ...root, id: "member", email: "member@example.com", display_name: "待审批员工", role: "user", is_active: false, approval_status: "pending" };
const approved: User = { ...pending, is_active: true, approval_status: "approved" };

function setup(user: User) {
  useAuthStore.setState({ user, accessToken: "test-token", ready: true });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = String(input);
    let data: unknown = {};
    if (init?.method === "POST") data = pending;
    else if (path.endsWith("/users/approvals")) data = [{ id: "approval", user_id: pending.id, requested_by_id: admin.id, status: "pending", created_at: root.created_at }];
    else if (path.endsWith("/users/knowledge-base-permissions")) data = [{ id: "kb", name: "研发资料", visibility: "users", member_ids: [] }];
    else if (path.endsWith("/users")) data = [root, admin, user.role === "super_admin" ? pending : approved];
    return new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } });
  });
  render(<QueryClientProvider client={client}><UsersPage /></QueryClientProvider>);
  return fetchMock;
}

afterEach(() => vi.restoreAllMocks());

describe("account approvals and membership", () => {
  it("lets the super administrator review an account request", async () => {
    const fetchMock = setup(root);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: /账号审批/ }));
    await user.click(await screen.findByRole("button", { name: "批准" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/users/approvals/approval/review",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ decision: "approved" }) }),
    ));
  });

  it("shows administrators application submission instead of direct approval", async () => {
    const fetchMock = setup(admin);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "申请添加用户" }));
    await user.type(screen.getByLabelText("邮箱"), "new@example.com");
    await user.type(screen.getByLabelText("显示名称"), "新同事");
    await user.type(screen.getByLabelText("初始密码"), "test-only-password");
    expect(screen.queryByLabelText("用户角色")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "提交审批" }));
    expect(await screen.findByText("申请已提交，超级管理员批准后账号才能登录。")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/users", expect.objectContaining({ method: "POST" }));
    await user.click(screen.getByRole("tab", { name: /账号审批/ }));
    expect(screen.queryByRole("button", { name: "批准" })).not.toBeInTheDocument();
  });

  it("saves an empty member selection as private, never implicitly public", async () => {
    const fetchMock = setup(admin);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "知识库权限" }));
    await user.click(await screen.findByRole("button", { name: "保存权限" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/users/knowledge-base-permissions/kb",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ visibility: "users", member_ids: [] }) }),
    ));
  });
});
