import { expect, test } from "@playwright/test";


test("content moves from draft to published, trash, restore, while viewer is read-only", async ({ browser, page, request }) => {
  const workspaceResponse = await request.post("http://127.0.0.1:8100/v1/workspaces", {
    data: { name: `内容 E2E ${Date.now()}` },
  });
  const workspace = await workspaceResponse.json() as { workspace_id: string; admin_code: string };

  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(workspace.admin_code);
  await page.getByLabel("显示名称").fill("内容管理员");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page).toHaveURL(`/workspaces/${workspace.workspace_id}/settings/members`);

  const account = await page.evaluate(async (workspaceId) => {
    const response = await fetch(`http://127.0.0.1:8100/v1/workspaces/${workspaceId}/accounts`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
      },
      body: JSON.stringify({
        platform: "douyin",
        name: "E2E 穿搭账号",
        objectives: ["engagement", "conversion"],
        metric_weights: { likes: 7, comments: 3 },
        benchmark_sample_size: 30,
      }),
    });
    return response.json();
  }, workspace.workspace_id) as { id: string };

  await page.goto(`/workspaces/${workspace.workspace_id}/contents/new?accountId=${account.id}&platform=douyin`);
  await page.getByLabel("标题").fill("E2E 发布前标题");
  await page.getByLabel("文案").fill("E2E 发布前文案");
  await page.getByRole("button", { name: "创建作品" }).click();
  await expect(page).toHaveURL(/\/contents\/[0-9a-f-]+$/);
  const contentUrl = page.url();

  await page.getByLabel("标题").fill("E2E 新草稿标题");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText("草稿已保存")).toBeVisible();
  await page.getByRole("button", { name: "发布作品" }).click();
  await expect(page.getByText("已发布并冻结最终版本")).toBeVisible();
  await expect(page.getByText("最终发布版")).toBeVisible();

  const viewerCode = await page.evaluate(async (workspaceId) => {
    const response = await fetch(`http://127.0.0.1:8100/v1/workspaces/${workspaceId}/members/codes`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
      },
      body: JSON.stringify({ role: "viewer" }),
    });
    return (await response.json()).code as string;
  }, workspace.workspace_id);

  const viewerContext = await browser.newContext();
  const viewerPage = await viewerContext.newPage();
  await viewerPage.goto("/enter");
  await viewerPage.getByLabel("邀请码").fill(viewerCode);
  await viewerPage.getByLabel("显示名称").fill("只读查看者");
  await viewerPage.getByRole("button", { name: "进入工作区" }).click();
  await expect(viewerPage).toHaveURL(`/workspaces/${workspace.workspace_id}/settings/members`);
  await viewerPage.goto(contentUrl);
  await viewerPage.getByLabel("标题").fill("越权标题");
  await viewerPage.getByRole("button", { name: "保存草稿" }).click();
  await expect(viewerPage.getByText("permission denied")).toBeVisible();
  await viewerContext.close();

  await page.getByRole("button", { name: "移入回收站" }).click();
  await expect(page.getByText("已移入回收站")).toBeVisible();
  await expect(page.getByText("回收站", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "从回收站恢复" }).click();
  await expect(page.getByText("已从回收站恢复")).toBeVisible();
  await expect(page.getByText("最终发布版")).toBeVisible();
});
