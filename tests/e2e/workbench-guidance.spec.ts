import {
  expect,
  type APIRequestContext,
  type Page,
  test,
} from "@playwright/test";

const api = process.env.WORKBENCH_E2E_API_URL
  ?? `http://127.0.0.1:${process.env.WORKBENCH_E2E_API_PORT ?? "8100"}`;

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
  return page.evaluate(async ({ apiUrl, targetWorkspaceId, targetRole }) => {
    const response = await fetch(
      `${apiUrl}/v1/workspaces/${targetWorkspaceId}/members/codes`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
        },
        body: JSON.stringify({ role: targetRole }),
      },
    );
    if (!response.ok) {
      throw new Error(`member code failed (${response.status})`);
    }
    return ((await response.json()) as { code: string }).code;
  }, {
    apiUrl: api,
    targetWorkspaceId: workspaceId,
    targetRole: role,
  });
}

test("operator copy and guidance persist without changing business state", async ({
  browser,
  page,
  request,
}) => {
  const workspace = await createWorkspace(request, "运营文案验收工作区");
  await enterWorkspace(page, workspace, workspace.admin_code, "文案管理员");
  await page.goto(`/workspaces/${workspace.workspace_id}/analysis`);

  await expect(page.getByRole("radio", { name: "易懂" })).toBeChecked();
  await expect(page.getByRole("switch", { name: "页面引导" })).toBeChecked();
  await expect(page.getByText(
    "找出还没分析或分析失败的作品，并查看问题和改进建议。",
  )).toBeVisible();

  const urlBefore = page.url();
  await page.getByRole("radio", { name: "专业" }).click();
  await expect(page.getByText(/Evidence 和置信度/)).toBeVisible();
  expect(page.url()).toBe(urlBefore);

  await page.reload();
  await expect(page.getByRole("radio", { name: "专业" })).toBeChecked();
  await page.getByRole("switch", { name: "页面引导" }).click();
  await expect(page.getByText(/Evidence 和置信度/)).toBeVisible();
  await expect(page.getByText("建议先做")).toHaveCount(0);

  await page.goto(`/workspaces/${workspace.workspace_id}/generation`);
  await page.getByLabel("生成目标").fill("测试发布目标");
  await page.getByRole("radio", { name: "易懂" }).click();
  await expect(page.getByLabel("生成目标")).toHaveValue("测试发布目标");
  await expect(page).toHaveURL(
    `/workspaces/${workspace.workspace_id}/generation`,
  );

  const viewerCode = await issueCode(page, workspace.workspace_id, "viewer");
  const viewer = await browser.newContext();
  const viewerPage = await viewer.newPage();
  await enterWorkspace(viewerPage, workspace, viewerCode, "文案查看者");
  await viewerPage.goto(`/workspaces/${workspace.workspace_id}/generation`);
  await expect(viewerPage.getByText("查看已保存的生成结果")).toBeVisible();
  await expect(viewerPage.getByText(/开始生成/)).toHaveCount(0);
  await viewer.close();
});

test("390px keeps controls and expandable help accessible", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const workspace = await createWorkspace(request, "移动引导验收工作区");
  await enterWorkspace(page, workspace, workspace.admin_code, "移动验收管理员");
  await page.goto(`/workspaces/${workspace.workspace_id}`);
  await page.getByText("界面说明", { exact: true }).click();
  await expect(page.getByRole("radiogroup", { name: "文案模式" })).toBeVisible();
  await page.getByText("界面说明", { exact: true }).click();
  await page.getByRole("button", { name: "查看操作说明" }).click();
  await expect(page.getByRole("region", { name: /操作说明/ })).toBeVisible();
  await expect(page.getByRole("main")).toHaveCount(1);
});
