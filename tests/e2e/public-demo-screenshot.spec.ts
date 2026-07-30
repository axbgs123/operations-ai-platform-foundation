import { expect, test } from "@playwright/test";


test("synthetic public demo renders before screenshot capture", async ({ page }, testInfo) => {
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "AI 内容实验室（合成示例）" })).toBeVisible();
  await expect(page.getByText("示例工作区 · 只读")).toBeVisible();
  await expect(page.getByText("抖音 · 合成 AI 科技抖音账号")).toBeVisible();
  await expect(page.getByText("小红书 · 合成 AI 科技小红书账号")).toBeVisible();

  await page.screenshot({
    path: process.env.DEMO_SCREENSHOT_OUTPUT ?? testInfo.outputPath("public-demo-rendered.png"),
    fullPage: true,
  });
});
