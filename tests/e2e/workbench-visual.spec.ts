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
    data: { name: "Task 10 合成视觉验收工作区" },
  });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<Workspace>;
}

async function enterWorkspace(page: Page, workspace: Workspace) {
  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(workspace.admin_code);
  await page.getByLabel("显示名称").fill("视觉验收管理员");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await page.waitForURL(
    new RegExp(`/workspaces/${workspace.workspace_id}/`),
  );
}

async function seedVisualData(page: Page, workspaceId: string) {
  return page.evaluate(async ({ apiUrl, targetWorkspaceId }) => {
    const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
    const createAccount = async (
      platform: "douyin" | "xiaohongshu",
      name: string,
    ) => {
      const response = await fetch(
        `${apiUrl}/v1/workspaces/${targetWorkspaceId}/accounts`,
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
        throw new Error(`visual account fixture failed (${response.status})`);
      }
      return response.json() as Promise<{ id: string }>;
    };
    const douyin = await createAccount("douyin", "视觉合成抖音账号");
    await createAccount("xiaohongshu", "视觉合成小红书账号");
    const contentResponse = await fetch(`${apiUrl}/v1/contents`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
      },
      body: JSON.stringify({
        workspace_id: targetWorkspaceId,
        account_id: douyin.id,
        platform: "douyin",
        content_type: "video",
        title: "视觉回归合成内容",
        body: "人工合成正文，仅用于自动化视觉回归。",
      }),
    });
    if (!contentResponse.ok) {
      throw new Error(`visual content fixture failed (${contentResponse.status})`);
    }
    const content = (await contentResponse.json()) as { id: string };
    return { accountId: douyin.id, contentId: content.id };
  }, { apiUrl: api, targetWorkspaceId: workspaceId });
}

async function prepareScreenshot(page: Page) {
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  await page.locator("nextjs-portal").evaluateAll((portals) => {
    for (const portal of portals) {
      (portal as HTMLElement).style.display = "none";
    }
  });
  await page.locator("body").evaluate((body) => {
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    const uuid =
      /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;
    let node = walker.nextNode();
    while (node) {
      node.textContent = node.textContent?.replace(
        uuid,
        "00000000-0000-0000-0000-000000000000",
      ) ?? "";
      node = walker.nextNode();
    }
  });
}

async function capture(page: Page, name: string) {
  await prepareScreenshot(page);
  await expect(page).toHaveScreenshot(name, {
    animations: "disabled",
    caret: "hide",
    fullPage: true,
    maxDiffPixelRatio: 0.001,
  });
}

test("canonical workbench routes retain stable synthetic visual baselines", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const workspace = await createWorkspace(request);
  await enterWorkspace(page, workspace);
  const fixture = await seedVisualData(page, workspace.workspace_id);
  const root = `/workspaces/${workspace.workspace_id}`;
  const scoped = `platform=douyin&account=${fixture.accountId}`;

  const routes = [
    ["overview", root],
    ["accounts", `${root}/accounts`],
    ["account-dashboard", `${root}/accounts/${fixture.accountId}`],
    ["columns", `${root}/columns?${scoped}`],
    ["contents", `${root}/contents?${scoped}`],
    ["imports", `${root}/imports?${scoped}`],
    ["analysis-queue", `${root}/analysis?${scoped}`],
    ["viral-library", `${root}/viral-library?${scoped}`],
    ["styles", `${root}/styles?${scoped}`],
    ["facts", `${root}/facts?${scoped}`],
    ["preflight", `${root}/preflight?${scoped}`],
    ["risk-knowledge", `${root}/risk-knowledge`],
    ["exports", `${root}/data-management/exports`],
    ["trash", `${root}/data-management/trash`],
    ["jobs", `${root}/settings/jobs`],
    ["settings", `${root}/settings`],
  ] as const;
  for (const [name, route] of routes) {
    await page.goto(route);
    if (name === "trash") {
      await expect(page.getByText("回收站为空")).toBeVisible();
      await expect(page.getByText("回收站请求失败")).toHaveCount(0);
      await expect(page.getByText("当前记录未提供").first()).toBeVisible();
    }
    await capture(page, `${name}.png`);
  }

  await page.goto(root);
  await page.getByRole("button", { name: "收起功能列表" }).click();
  await capture(page, "navigation-collapsed.png");
  await page.getByRole("button", { name: "展开功能列表" }).click();

  const detailTabs = [
    "overview",
    "snapshots",
    "analysis",
    "risk",
    "generation",
  ] as const;
  for (const tab of detailTabs) {
    await page.goto(
      `${root}/contents/${fixture.contentId}?tab=${tab}&${scoped}`,
    );
    await capture(page, `content-${tab}.png`);
  }

  await page.goto(`${root}/generation?${scoped}`);
  for (const step of [
    ["范围与目标", "generation-scope.png"],
    ["事实资料", "generation-facts.png"],
    ["风格与参考", "generation-references.png"],
    ["生成与编辑", "generation-edit.png"],
    ["复核与保存", "generation-review.png"],
  ] as const) {
    await page.getByRole("button", { name: step[0], exact: true }).click();
    await capture(page, step[1]);
  }

  await page.goto("/demo");
  await capture(page, "public-demo.png");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(root);
  await capture(page, "mobile-overview.png");
  await page.getByRole("button", { name: "打开主导航" }).click();
  await capture(page, "mobile-navigation-categories.png");
  await page.getByRole("button", { name: "资产", exact: true }).click();
  await capture(page, "mobile-navigation-assets.png");
  await page.goto(
    `${root}/contents/${fixture.contentId}?tab=overview&${scoped}`,
  );
  await capture(page, "mobile-content-detail.png");

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${root}/analysis?${scoped}`);
  await capture(page, "guidance-easy.png");

  await page.getByRole("radio", { name: "专业" }).click();
  await capture(page, "guidance-professional.png");

  await page.getByRole("radio", { name: "易懂" }).click();
  await page.getByRole("switch", { name: "页面引导" }).click();
  await capture(page, "guidance-off.png");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${root}/preflight?${scoped}`);
  await page.getByText("界面说明", { exact: true }).click();
  await page.getByRole("radio", { name: "专业" }).click();
  await expect(page.getByRole("switch", { name: "页面引导" })).not.toBeChecked();
  await expect(page.getByRole("button", { name: "查看操作说明" })).toHaveCount(0);
  await capture(page, "mobile-guidance.png");
});
