import { expect, type Page, type APIRequestContext, test } from "@playwright/test";

const api = process.env.WORKBENCH_E2E_API_URL
  ?? `http://127.0.0.1:${process.env.WORKBENCH_E2E_API_PORT ?? "8100"}`;

const routes = [
  ["工作台总览", ""],
  ["账号仪表盘", "/accounts"],
  ["栏目与活动", "/columns"],
  ["内容库", "/contents"],
  ["数据导入", "/imports"],
  ["分析中心", "/analysis"],
  ["爆款素材库", "/viral-library"],
  ["账号风格", "/styles"],
  ["事实资料", "/facts"],
  ["生成中心", "/generation"],
  ["发布前检查", "/preflight"],
  ["风控知识库", "/risk-knowledge"],
  ["导出与备份", "/data-management/exports"],
  ["回收站", "/data-management/trash"],
  ["后台任务", "/settings/jobs"],
  ["工作区设置", "/settings"],
] as const;

const editorLabels = routes
  .map(([label]) => label)
  .filter((label) => ![
    "风控知识库",
    "回收站",
    "工作区设置",
  ].includes(label));

const viewerLabels = [
  "工作台总览",
  "账号仪表盘",
  "内容库",
  "分析中心",
  "爆款素材库",
  "账号风格",
  "事实资料",
  "生成中心",
  "发布前检查",
] as const;

type Workspace = {
  workspace_id: string;
  admin_code: string;
};

async function createWorkspace(
  request: APIRequestContext,
  name: string,
): Promise<Workspace> {
  const response = await request.post(`${api}/v1/workspaces`, {
    data: { name },
  });
  expect(response.ok()).toBeTruthy();
  return response.json() as Promise<Workspace>;
}

async function enterWorkspace(
  page: Page,
  workspace: Workspace,
  code: string,
  displayName: string,
) {
  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(code);
  await page.getByLabel("显示名称").fill(displayName);
  await page.getByRole("button", { name: "进入工作区" }).click();
  await page.waitForURL(
    new RegExp(`/workspaces/${workspace.workspace_id}/`),
  );
}

async function issueCode(
  page: Page,
  workspaceId: string,
  role: "editor" | "viewer",
): Promise<string> {
  return page.evaluate(async ({ apiUrl, roleName, targetWorkspaceId }) => {
    const response = await fetch(
      `${apiUrl}/v1/workspaces/${targetWorkspaceId}/members/codes`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
        },
        body: JSON.stringify({ role: roleName }),
      },
    );
    if (!response.ok) {
      throw new Error(`member code failed (${response.status})`);
    }
    return ((await response.json()) as { code: string }).code;
  }, {
    apiUrl: api,
    roleName: role,
    targetWorkspaceId: workspaceId,
  });
}

async function assertNavigationLabels(
  page: Page,
  expected: readonly string[],
) {
  const navigation = page.getByRole("navigation", { name: "主导航" });
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole("link")).toHaveCount(expected.length);
  for (const label of expected) {
    await expect(
      navigation.getByRole("link", { name: label, exact: true }),
    ).toBeVisible();
  }
}

test("admin reaches all 16 formal modules through visible primary navigation", async ({
  page,
  request,
}) => {
  const workspace = await createWorkspace(
    request,
    "Task 10 路由验收工作区",
  );
  await enterWorkspace(page, workspace, workspace.admin_code, "路由管理员");
  await page.goto(`/workspaces/${workspace.workspace_id}`);

  await assertNavigationLabels(page, routes.map(([label]) => label));

  for (const [label, suffix] of routes) {
    const link = page
      .getByRole("navigation", { name: "主导航" })
      .getByRole("link", { name: label, exact: true });
    await link.click();
    await expect(page).toHaveURL(
      new RegExp(`/workspaces/${workspace.workspace_id}${suffix}(?:\\?.*)?$`),
    );
    await expect(link).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(
      page.getByRole("navigation", { name: "面包屑" }),
    ).toBeVisible();
    await expect(page.getByText("This page could not be found")).toHaveCount(0);
  }

  const accountId = await page.evaluate(
    async ({ apiUrl, workspaceId }) => {
      const response = await fetch(
        `${apiUrl}/v1/workspaces/${workspaceId}/accounts`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
          },
          body: JSON.stringify({
            platform: "douyin",
            name: "旧路由兼容合成账号",
            objectives: ["engagement"],
            metric_weights: { likes: 1 },
            benchmark_sample_size: 30,
          }),
        },
      );
      if (!response.ok) {
        throw new Error(`legacy account fixture failed (${response.status})`);
      }
      return ((await response.json()) as { id: string }).id;
    },
    { apiUrl: api, workspaceId: workspace.workspace_id },
  );
  await page.goto(
    `/workspaces/${workspace.workspace_id}/accounts/${accountId}/settings`
      + `?platform=douyin&account=${accountId}`
      + "&returnTo=https%3A%2F%2Fevil.example",
  );
  await expect(page).toHaveURL(
    `/workspaces/${workspace.workspace_id}/accounts/${accountId}`
      + `?platform=douyin&account=${accountId}`,
  );
  await expect(page.getByRole("main")).toHaveCount(1);

  for (const [legacyPath, heading] of [
    ["settings/members", "成员与邀请码"],
    ["settings/models", "模型配置"],
  ] as const) {
    await page.goto(`/workspaces/${workspace.workspace_id}/${legacyPath}`);
    await expect(
      page.getByRole("heading", { level: 1, name: heading }),
    ).toBeVisible();
    await expect(page.getByRole("main")).toHaveCount(1);
    await expect(
      page.getByRole("navigation", { name: "主导航" }),
    ).toBeVisible();
  }
});

test("editor and viewer receive the approved 13 and 9 item navigation matrices", async ({
  browser,
  page,
  request,
}) => {
  const workspace = await createWorkspace(
    request,
    "Task 10 角色验收工作区",
  );
  const otherWorkspace = await createWorkspace(
    request,
    "Task 10 隔离反例工作区",
  );
  await enterWorkspace(page, workspace, workspace.admin_code, "权限管理员");
  const editorCode = await issueCode(page, workspace.workspace_id, "editor");
  const viewerCode = await issueCode(page, workspace.workspace_id, "viewer");

  const editorContext = await browser.newContext();
  const editorPage = await editorContext.newPage();
  await enterWorkspace(editorPage, workspace, editorCode, "权限编辑者");
  await editorPage.goto(`/workspaces/${workspace.workspace_id}`);
  await assertNavigationLabels(editorPage, editorLabels);
  await expect(
    editorPage.getByRole("link", { name: "工作区设置", exact: true }),
  ).toHaveCount(0);
  await editorPage.goto(`/workspaces/${workspace.workspace_id}/settings/jobs`);
  await expect(
    editorPage.getByRole("button", { name: /重试|取消|补偿/ }),
  ).toHaveCount(0);

  const viewerContext = await browser.newContext();
  const viewerPage = await viewerContext.newPage();
  await enterWorkspace(viewerPage, workspace, viewerCode, "权限查看者");
  await viewerPage.goto(`/workspaces/${workspace.workspace_id}`);
  await assertNavigationLabels(viewerPage, viewerLabels);
  await expect(
    viewerPage.getByRole("link", { name: "栏目与活动", exact: true }),
  ).toHaveCount(0);
  await expect(
    viewerPage.getByRole("link", { name: "数据导入", exact: true }),
  ).toHaveCount(0);

  const permissionResults = await viewerPage.evaluate(
    async ({ apiUrl, otherId, workspaceId }) => {
      const ownMembers = await fetch(
        `${apiUrl}/v1/workspaces/${workspaceId}/members`,
        { credentials: "include" },
      );
      const otherContext = await fetch(
        `${apiUrl}/v1/workspaces/${otherId}/workbench/context`,
        { credentials: "include" },
      );
      return {
        ownMembers: ownMembers.status,
        otherContext: otherContext.status,
      };
    },
    {
      apiUrl: api,
      otherId: otherWorkspace.workspace_id,
      workspaceId: workspace.workspace_id,
    },
  );
  expect(permissionResults).toEqual({
    ownMembers: 403,
    otherContext: 404,
  });

  await editorContext.close();
  await viewerContext.close();
});

test("public Demo remains read-only and outside the private WorkspaceShell", async ({
  page,
}) => {
  await page.goto("/demo");
  await expect(page.getByText("示例工作区 · 只读")).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "主导航" }),
  ).toHaveCount(0);
  await expect(page.getByRole("link", { name: /进入私有工作区/ })).toHaveAttribute(
    "href",
    "/enter",
  );
  await expect(page.getByText(/API Key|邀请码|工作区删除/)).toHaveCount(0);
});
