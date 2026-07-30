import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

const api = process.env.WORKBENCH_E2E_API_URL
  ?? `http://127.0.0.1:${process.env.WORKBENCH_E2E_API_PORT ?? "8100"}`;

type Workspace = {
  workspace_id: string;
  admin_code: string;
};

async function createWorkspace(
  request: APIRequestContext,
): Promise<Workspace> {
  const response = await request.post(`${api}/v1/workspaces`, {
    data: { name: "Task 10 手机验收工作区" },
  });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<Workspace>;
}

async function enterWorkspace(page: Page, workspace: Workspace) {
  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(workspace.admin_code);
  await page.getByLabel("显示名称").fill("手机验收管理员");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await page.waitForURL(
    new RegExp(`/workspaces/${workspace.workspace_id}/`),
  );
}

async function seedContent(page: Page, workspaceId: string) {
  return page.evaluate(async ({ apiUrl, targetWorkspaceId }) => {
    const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
    const accountResponse = await fetch(
      `${apiUrl}/v1/workspaces/${targetWorkspaceId}/accounts`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
        body: JSON.stringify({
          platform: "douyin",
          name: "手机合成抖音账号",
          objectives: ["engagement"],
          metric_weights: { likes: 1 },
          benchmark_sample_size: 30,
        }),
      },
    );
    if (!accountResponse.ok) {
      throw new Error(`account fixture failed (${accountResponse.status})`);
    }
    const account = (await accountResponse.json()) as { id: string };
    const contentResponse = await fetch(`${apiUrl}/v1/contents`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      body: JSON.stringify({
        workspace_id: targetWorkspaceId,
        account_id: account.id,
        platform: "douyin",
        content_type: "video",
        title: "手机端合成内容卡片",
        body: "仅用于Task 10移动端验收的人工合成正文。",
      }),
    });
    if (!contentResponse.ok) {
      throw new Error(`content fixture failed (${contentResponse.status})`);
    }
    const content = (await contentResponse.json()) as { id: string };
    return { accountId: account.id, contentId: content.id };
  }, { apiUrl: api, targetWorkspaceId: workspaceId });
}

async function expectNoHorizontalOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
});

test("390px navigation drawer traps focus, closes safely, and closes after navigation", async ({
  page,
  request,
}) => {
  const workspace = await createWorkspace(request);
  await enterWorkspace(page, workspace);
  await page.goto(`/workspaces/${workspace.workspace_id}`);

  const trigger = page.getByRole("button", { name: "打开主导航" });
  await trigger.click();
  const drawer = page.getByRole("dialog", { name: "主导航" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute("aria-modal", "true");
  await expect(
    page.getByTestId("workspace-shell-background"),
  ).toHaveAttribute("inert");
  await expect(page.getByRole("button", { name: "关闭主导航" })).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await trigger.click();
  await drawer.getByRole("link", { name: "内容库", exact: true }).click();
  await expect(page).toHaveURL(
    `/workspaces/${workspace.workspace_id}/contents`,
  );
  await expect(drawer).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("390px workbench keeps key states readable and explains desktop-only operations", async ({
  page,
  request,
}) => {
  const workspace = await createWorkspace(request);
  await enterWorkspace(page, workspace);
  const fixture = await seedContent(page, workspace.workspace_id);

  await page.goto(`/workspaces/${workspace.workspace_id}`);
  await expect(
    page.getByRole("heading", { name: "手机合成抖音账号" }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(`/workspaces/${workspace.workspace_id}/accounts`);
  await expect(
    page.getByRole("list", { name: "账号仪表盘列表" }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/workspaces/${workspace.workspace_id}/contents`
      + `?platform=douyin&account=${fixture.accountId}`,
  );
  const mobileContentList = page.getByRole("list", {
    name: "内容库移动卡片",
  });
  await expect(mobileContentList).toBeVisible();
  await expect(
    mobileContentList.getByText("手机端合成内容卡片"),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/workspaces/${workspace.workspace_id}/contents/${fixture.contentId}`
      + "?tab=risk",
  );
  await expect(page.getByText("辅助判断，不保证通过平台审核")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/workspaces/${workspace.workspace_id}/analysis`
      + `?platform=douyin&account=${fixture.accountId}`,
  );
  await expect(
    page.getByRole("list", { name: "分析队列移动卡片" }).or(
      page.getByText("当前范围没有分析事项"),
    ),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/workspaces/${workspace.workspace_id}/preflight`
      + `?platform=douyin&account=${fixture.accountId}`,
  );
  await expect(
    page.getByRole("list", { name: "发布前检查移动卡片" }).or(
      page.getByText("当前范围没有发布前事项"),
    ),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/workspaces/${workspace.workspace_id}/viral-library`
      + `?platform=douyin&account=${fixture.accountId}`,
  );
  await expect(page.getByRole("region", { name: "爆款候选" })).toBeVisible();
  await expect(page.getByRole("region", { name: "已确认素材" })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/workspaces/${workspace.workspace_id}/styles`
      + `?platform=douyin&account=${fixture.accountId}`,
  );
  await expect(
    page.getByRole("heading", { name: "手机合成抖音账号" }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/workspaces/${workspace.workspace_id}/facts`
      + `?platform=douyin&account=${fixture.accountId}`,
  );
  await expect(
    page.getByRole("region", { name: "事实来源等级说明" }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.goto(
    `/workspaces/${workspace.workspace_id}/imports`
      + `?platform=douyin&account=${fixture.accountId}`,
  );
  await page.getByRole("button", { name: "Excel / CSV", exact: true }).click();
  await expect(
    page.getByText(/电脑端继续大型 Excel 字段映射和批量修正/),
  ).toBeVisible();

  await page.goto(
    `/workspaces/${workspace.workspace_id}/generation`
      + `?platform=douyin&account=${fixture.accountId}`,
  );
  await page.getByRole("button", { name: "生成与编辑", exact: true }).click();
  await expect(page.getByText(/电脑端继续复杂封面编辑/)).toBeVisible();

  const desktopOnlyRoutes = [
    ["/risk-knowledge", "复杂知识库审核"],
    ["/data-management/exports", "ZIP 完整恢复"],
    ["/settings", "模型密钥和预算配置"],
    ["/settings", "工作区删除和二次确认"],
  ] as const;
  for (const [suffix, action] of desktopOnlyRoutes) {
    await page.goto(`/workspaces/${workspace.workspace_id}${suffix}`);
    await expect(page.getByText(new RegExp(`电脑端继续${action}`))).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }

  for (const [suffix, heading] of [
    ["/risk-knowledge", "风控知识治理"],
    ["/data-management/exports", "导出、备份与恢复"],
    ["/data-management/trash", "内容回收站"],
    ["/settings/jobs", "后台任务运维"],
  ] as const) {
    await page.goto(`/workspaces/${workspace.workspace_id}${suffix}`);
    await expect(
      page.getByRole("heading", { level: 1, name: heading }),
    ).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
});
