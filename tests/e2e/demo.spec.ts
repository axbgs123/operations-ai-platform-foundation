import { expect, test } from "@playwright/test";


test("anonymous visitor can explore synthetic data and receives limited mock output", async ({ page }) => {
  await page.goto("/demo");

  await expect(page.getByRole("heading", { name: "AI 内容实验室（合成示例）" })).toBeVisible();
  await expect(page.getByText("公开体验区")).toBeVisible();
  await expect(page.getByText("示例数据").first()).toBeVisible();
  await expect(page.getByText("抖音 · 合成 AI 科技抖音账号")).toBeVisible();
  await expect(page.getByText("小红书 · 合成 AI 科技小红书账号")).toBeVisible();

  await page.getByRole("button", { name: "生成 Mock 标题" }).click();
  await expect(page.getByText("Mock 输出")).toBeVisible();
  await expect(page.getByText(/剩余 2 次/)).toBeVisible();
});
