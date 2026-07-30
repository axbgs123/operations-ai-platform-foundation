import { expect, test } from "@playwright/test";

const api = process.env.CONTENT_DETAIL_E2E_API_URL
  ?? `http://127.0.0.1:${process.env.CONTENT_DETAIL_E2E_API_PORT ?? "18100"}`;

test("content library and five-tab detail preserve scope, access, and legacy links", async ({
  browser,
  page,
  request,
}) => {
  const workspaceResponse = await request.post(
    `${api}/v1/workspaces`,
    { data: { name: `内容工作流 E2E ${Date.now()}` } },
  );
  const workspace = await workspaceResponse.json() as {
    workspace_id: string;
    admin_code: string;
  };

  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(workspace.admin_code);
  await page.getByLabel("显示名称").fill("内容管理员");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await page.waitForURL(
    new RegExp(`/workspaces/${workspace.workspace_id}/settings/members$`),
  );

  const fixtures = await page.evaluate(async ({ workspaceId, apiUrl }) => {
    const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
    const createAccount = async (
      platform: "douyin" | "xiaohongshu",
      name: string,
    ) => {
      const response = await fetch(
        `${apiUrl}/v1/workspaces/${workspaceId}/accounts`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          body: JSON.stringify({
            platform,
            name,
            objectives: ["engagement"],
            metric_weights: platform === "douyin"
              ? { likes: 1 }
              : { favorites: 1 },
            benchmark_sample_size: 30,
          }),
        },
      );
      if (!response.ok) {
        throw new Error(`account fixture creation failed (${response.status})`);
      }
      return response.json();
    };
    const douyin = await createAccount("douyin", "E2E 抖音账号");
    await createAccount("xiaohongshu", "E2E 小红书账号");
    const contentResponse = await fetch(`${apiUrl}/v1/contents`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      body: JSON.stringify({
        workspace_id: workspaceId,
        account_id: douyin.id,
        platform: "douyin",
        content_type: "video",
        title: "E2E AI 内容详情",
        body: "人工合成内容，不含真实运营数据。",
      }),
    });
    if (!contentResponse.ok) {
      throw new Error(`content fixture creation failed (${contentResponse.status})`);
    }
    return {
      accountId: douyin.id as string,
      content: await contentResponse.json() as { id: string },
    };
  }, { workspaceId: workspace.workspace_id, apiUrl: api });

  await page.goto(
    `/workspaces/${workspace.workspace_id}/contents`
      + `?platform=douyin&account=${fixtures.accountId}`
      + "&contentType=video&status=draft&sort=newest&page=1",
  );
  await expect(page.getByRole("heading", { name: "内容库" })).toBeVisible();
  await expect(page.getByLabel("栏目/活动")).toBeVisible();
  await expect(page.getByLabel("生命周期")).toHaveValue("draft");
  await expect(page.getByText("E2E AI 内容详情").first()).toBeVisible();

  await page.getByLabel("生命周期").selectOption("published");
  await expect(page).toHaveURL(/status=published/);
  await expect(page.getByText("没有符合条件的内容")).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("生命周期")).toHaveValue("draft");
  await expect(page.getByText("E2E AI 内容详情").first()).toBeVisible();

  await page.getByRole("link", { name: "查看内容" }).first().click();
  await expect(page).toHaveURL(new RegExp(`/contents/${fixtures.content.id}`));
  await expect(page.getByRole("tab")).toHaveCount(5);
  await expect(page.getByRole("tab", { name: "概览" })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  await page.getByRole("tab", { name: "数据快照" }).click();
  await expect(page).toHaveURL(/tab=snapshots/);
  await expect(page.getByText("还没有数据快照")).toBeVisible();
  await page.getByRole("tab", { name: "风控" }).click();
  await expect(page.getByText("尚未扫描").first()).toBeVisible();
  await expect(
    page.getByText("辅助判断，不保证通过平台审核"),
  ).toBeVisible();

  await page.goto(
    `/workspaces/${workspace.workspace_id}/contents/${fixtures.content.id}`
      + "?tab=not-a-tab",
  );
  await expect(page.getByRole("tab", { name: "概览" })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  const safeReturn = (
    `/workspaces/${workspace.workspace_id}/contents`
    + `?platform=douyin&account=${fixtures.accountId}&page=3`
  );
  await page.goto(
    `/workspaces/${workspace.workspace_id}/contents/${fixtures.content.id}/analysis`
      + `?returnTo=${encodeURIComponent(safeReturn)}`,
  );
  await expect(page).toHaveURL(/tab=analysis/);
  await expect(page.getByRole("tab", { name: "分析" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("link", { name: "返回内容库" })).toHaveAttribute(
    "href",
    safeReturn,
  );

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(
    `/workspaces/${workspace.workspace_id}/contents`
      + `?platform=douyin&account=${fixtures.accountId}`
      + "&contentType=video&status=draft&sort=newest&page=1",
  );
  await expect(
    page.getByRole("list", { name: "内容库移动卡片" }),
  ).toBeVisible();
  await expect(
    page.getByRole("table", { name: "内容库桌面列表" }),
  ).toBeHidden();

  const viewerCode = await page.evaluate(async ({ workspaceId, apiUrl }) => {
    const response = await fetch(
      `${apiUrl}/v1/workspaces/${workspaceId}/members/codes`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
        },
        body: JSON.stringify({ role: "viewer" }),
      },
    );
    return (await response.json()).code as string;
  }, { workspaceId: workspace.workspace_id, apiUrl: api });

  const viewerContext = await browser.newContext();
  const viewerPage = await viewerContext.newPage();
  await viewerPage.goto("/enter");
  await viewerPage.getByLabel("邀请码").fill(viewerCode);
  await viewerPage.getByLabel("显示名称").fill("只读查看者");
  await viewerPage.getByRole("button", { name: "进入工作区" }).click();
  await viewerPage.waitForURL(
    new RegExp(`/workspaces/${workspace.workspace_id}/settings/members$`),
  );
  await viewerPage.goto(
    `/workspaces/${workspace.workspace_id}/contents/${fixtures.content.id}`,
  );
  await expect(
    viewerPage.getByRole("link", { name: "生成同类内容" }),
  ).toHaveCount(0);
  await expect(viewerPage.getByRole("tab")).toHaveCount(5);
  await viewerContext.close();
});
