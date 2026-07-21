import { expect, test } from "@playwright/test";


test("foundation demo covers public preview, dual-platform accounts, and content detail", async ({ page, request }) => {
  await page.goto("/demo");
  await expect(page.getByText("公开体验区")).toBeVisible();
  await expect(page.getByText("抖音 · 城市穿搭研究所")).toBeVisible();
  await expect(page.getByText("小红书 · 通勤灵感簿")).toBeVisible();

  const workspaceResponse = await request.post("http://127.0.0.1:8100/v1/workspaces", {
    data: { name: `Foundation Smoke ${Date.now()}` },
  });
  const workspace = await workspaceResponse.json() as { workspace_id: string; admin_code: string };
  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(workspace.admin_code);
  await page.getByLabel("显示名称").fill("验收管理员");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page).toHaveURL(`/workspaces/${workspace.workspace_id}/settings/members`);

  const result = await page.evaluate(async (workspaceId) => {
    const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
    const createAccount = async (platform: "douyin" | "xiaohongshu", name: string) => {
      const response = await fetch(`http://127.0.0.1:8100/v1/workspaces/${workspaceId}/accounts`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({
          platform,
          name,
          objectives: ["engagement", "conversion"],
          metric_weights: { likes: 7, comments: 3 },
          benchmark_sample_size: 30,
        }),
      });
      return response.json();
    };
    const douyin = await createAccount("douyin", "验收抖音号");
    const xiaohongshu = await createAccount("xiaohongshu", "验收小红书号");
    const contentResponse = await fetch("http://127.0.0.1:8100/v1/contents", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({
        workspace_id: workspaceId,
        account_id: douyin.id,
        platform: "douyin",
        title: "基础验收作品",
        body: "用于 Gate A 的作品详情。",
      }),
    });
    return { douyin, xiaohongshu, content: await contentResponse.json() };
  }, workspace.workspace_id) as {
    douyin: { platform: string };
    xiaohongshu: { platform: string };
    content: { id: string };
  };
  expect(result.douyin.platform).toBe("douyin");
  expect(result.xiaohongshu.platform).toBe("xiaohongshu");

  await page.goto(`/workspaces/${workspace.workspace_id}/contents/${result.content.id}`);
  await expect(page.getByRole("heading", { name: "基础验收作品" })).toBeVisible();
  await expect(page.getByText("抖音 · 验收抖音号")).toBeVisible();
});
