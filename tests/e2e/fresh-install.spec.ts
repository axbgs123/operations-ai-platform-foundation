import { expect, test } from "@playwright/test";

test("fresh Docker install exposes the persisted synthetic Mock demo", async ({ page }) => {
  await page.goto("/demo");
  await expect(page.getByText("示例数据").first()).toBeVisible();
  await expect(page.getByText(/抖音/)).toBeVisible();
  await expect(page.getByText(/小红书/)).toBeVisible();
  await expect(page.getByText("生成 Mock 标题")).toBeVisible();
  await expect(page.getByText(/Mock 不等于生产模型效果/)).toBeVisible();
  for (const label of ["已发布内容", "正式确认数据快照", "动态基准 / 图表", "Mock 分析", "建议", "风格样本", "已确认事实", "合成风控知识", "生成草稿"]) {
    await expect(page.getByRole("heading", { name: label })).toBeVisible();
  }
  await expect(page.getByText("Mock 分析：内容结构清晰。")).toBeVisible();
  const apiUrl = process.env.FRESH_INSTALL_API_URL ?? "http://127.0.0.1:8000";
  const api = await page.request.get(`${apiUrl}/v1/demo/workspace`);
  expect(api.ok()).toBeTruthy();
  const demo = await api.json();
  expect(demo.confirmed_snapshot.confirmed).toBeTruthy();
  expect(demo.analysis.mock).toBeTruthy();
  expect(demo.risk_knowledge.synthetic).toBeTruthy();
  expect((await page.request.post(`${apiUrl}/v1/demo/uploads`)).status()).toBe(403);
  expect((await page.request.patch(`${apiUrl}/v1/demo/workspace`, { data: { name: "blocked" } })).status()).toBe(403);
});
