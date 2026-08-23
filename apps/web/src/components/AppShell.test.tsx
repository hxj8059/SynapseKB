import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { useAuthStore } from "../stores/auth";
import { AppShell } from "./AppShell";

describe("AppShell navigation", () => {
  it("highlights only the graph entry on the Wiki graph route", () => {
    useAuthStore.setState({
      accessToken: "test-token",
      ready: true,
      user: {
        id: "user-1",
        email: "admin@example.test",
        display_name: "Admin",
        role: "admin",
        is_active: true,
        timezone: "Asia/Shanghai",
        created_at: "2026-01-01T00:00:00Z",
      },
    });

    render(
      <MemoryRouter initialEntries={["/wiki/graph"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/wiki/graph" element={<div>Graph</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    for (const link of screen.getAllByRole("link", { name: "Wiki" })) {
      expect(link).not.toHaveAttribute("aria-current");
    }
    for (const link of screen.getAllByRole("link", { name: "Wiki 关系图" })) {
      expect(link).toHaveAttribute("aria-current", "page");
    }
  });

  it("places Skill installation after the token entry in the account panel", () => {
    useAuthStore.setState({
      accessToken: "test-token",
      ready: true,
      user: {
        id: "user-1",
        email: "admin@example.test",
        display_name: "Admin",
        role: "admin",
        is_active: true,
        timezone: "Asia/Shanghai",
        created_at: "2026-01-01T00:00:00Z",
      },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>Home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    const tokenButton = screen.getByRole("button", { name: "MCP Token" });
    const skillButton = screen.getByRole("button", { name: "Skill 安装" });
    expect(tokenButton.closest("a")?.nextElementSibling).toBe(skillButton.closest("a"));
  });

  it("shows knowledge-base management only to administrators", () => {
    useAuthStore.setState({
      accessToken: "test-token",
      ready: true,
      user: {
        id: "user-1",
        email: "admin@example.test",
        display_name: "Admin",
        role: "admin",
        is_active: true,
        timezone: "Asia/Shanghai",
        created_at: "2026-01-01T00:00:00Z",
      },
    });
    const { unmount } = render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>Home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getAllByRole("link", { name: "知识库管理" }).length).toBeGreaterThan(0);
    unmount();

    useAuthStore.setState({
      user: {
        id: "user-2",
        email: "user@example.test",
        display_name: "User",
        role: "user",
        is_active: true,
        timezone: "Asia/Shanghai",
        created_at: "2026-01-01T00:00:00Z",
      },
    });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<div>Home</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.queryByRole("link", { name: "知识库管理" })).not.toBeInTheDocument();
  });
});
