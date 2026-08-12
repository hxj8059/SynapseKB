import { expect, test } from "@playwright/test";

test("login page exposes the real authentication form", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveTitle(/SynapseKB/);
  await expect(page.getByRole("heading", { name: "欢迎回来" })).toBeVisible();
  await expect(page.getByLabel("邮箱")).toBeVisible();
  await expect(page.getByLabel("密码")).toBeVisible();
  await expect(page.getByRole("button", { name: "登录" })).toBeVisible();
});
