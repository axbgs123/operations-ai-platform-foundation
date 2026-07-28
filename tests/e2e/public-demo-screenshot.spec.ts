import { expect, test } from "@playwright/test";


test("synthetic public demo renders before screenshot capture", async ({ page }, testInfo) => {
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: "内容运营示例工作区" })).toBeVisible();
  await expect(page.getByText("公开体验区")).toBeVisible();
  await expect(page.getByText("抖音 · 城市穿搭研究所")).toBeVisible();
  await expect(page.getByText("小红书 · 通勤灵感簿")).toBeVisible();

  await page.screenshot({
    path: process.env.DEMO_SCREENSHOT_OUTPUT ?? testInfo.outputPath("public-demo-rendered.png"),
    fullPage: true,
  });
});
