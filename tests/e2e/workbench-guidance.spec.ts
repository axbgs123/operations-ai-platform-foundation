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

async function createAccount(page: Page, workspaceId: string): Promise<string> {
  return page.evaluate(async ({ apiUrl, targetWorkspaceId }) => {
    const response = await fetch(
      `${apiUrl}/v1/workspaces/${targetWorkspaceId}/accounts`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
        },
        body: JSON.stringify({
          platform: "douyin",
          name: "引导验收合成账号",
          objectives: ["engagement"],
          metric_weights: { likes: 1 },
          benchmark_sample_size: 30,
        }),
      },
    );
    if (!response.ok) {
      throw new Error(`account fixture failed (${response.status})`);
    }
    return ((await response.json()) as { id: string }).id;
  }, { apiUrl: api, targetWorkspaceId: workspaceId });
}

async function stageManualImport(
  page: Page,
  workspaceId: string,
  accountId: string,
) {
  await page.evaluate(async ({ apiUrl, targetWorkspaceId, targetAccountId }) => {
    const response = await fetch(
      `${apiUrl}/v1/workspaces/${targetWorkspaceId}/imports/manual/preview`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
        },
        body: JSON.stringify({
          account_id: targetAccountId,
          platform: "douyin",
          content_type: "video",
          rows: [{
            platform_content_id: "GUIDANCE-VIEWER-IMPORT",
            title: "查看者导入引导合成记录",
            body: "仅用于查看者导入引导验收。",
            published_at: "2026-08-01T10:00:00+08:00",
            collected_at: "2026-08-01T11:00:00+08:00",
            metrics: { views: 100 },
          }],
        }),
      },
    );
    if (!response.ok) {
      throw new Error(`import fixture failed (${response.status})`);
    }
  }, { apiUrl: api, targetWorkspaceId: workspaceId, targetAccountId: accountId });
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

  const accountId = await createAccount(page, workspace.workspace_id);
  await stageManualImport(page, workspace.workspace_id, accountId);
  const viewerCode = await issueCode(page, workspace.workspace_id, "viewer");
  const viewer = await browser.newContext();
  const viewerPage = await viewer.newPage();
  await enterWorkspace(viewerPage, workspace, viewerCode, "文案查看者");
  await viewerPage.goto(`/workspaces/${workspace.workspace_id}/generation`);
  await expect(viewerPage.getByText("查看已保存的生成结果")).toBeVisible();
  await expect(
    viewerPage.getByText("选择平台、账号和栏目后开始生成"),
  ).toHaveCount(0);
  await expect(viewerPage.getByText(/开始生成/)).toHaveCount(0);
  await viewerPage.getByRole("button", { name: "查看操作说明" }).click();
  await expect(viewerPage.getByText("查看页面中已有的数据、状态和说明。")).toBeVisible();
  await expect(
    viewerPage.getByText("需要新增、修改或确认时，请联系管理员或编辑者。"),
  ).toBeVisible();
  await viewerPage.goto(
    `/workspaces/${workspace.workspace_id}/imports?platform=douyin&account=${accountId}`,
  );
  await viewerPage.getByRole("radio", { name: "专业" }).click();
  await expect(viewerPage.getByText(
    "Viewer 只读查看等待确认的导入记录；继续确认需要 Admin 或 Editor。",
  ).first()).toBeVisible();
  await expect(viewerPage.getByText("Viewer 只读继续确认")).toHaveCount(0);
  await viewer.close();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/workspaces/${workspace.workspace_id}`);
  await page.getByText("界面说明", { exact: true }).click();
  await expect(page.getByRole("radiogroup", { name: "文案模式" })).toBeVisible();
  await page.getByRole("radio", { name: "专业" }).click();
  await expect(page.getByRole("radio", { name: "专业" })).toBeChecked();
  await page.getByText("界面说明", { exact: true }).click();
  await expect(page.getByRole("radiogroup", { name: "文案模式" })).toBeHidden();
  await page.getByText("界面说明", { exact: true }).click();
  await page.getByRole("switch", { name: "页面引导" }).click();
  await expect(page.getByText("建议先做")).toBeVisible();
  await page.getByRole("switch", { name: "页面引导" }).click();
  await expect(page.getByText("建议先做")).toHaveCount(0);
  await page.getByRole("switch", { name: "页面引导" }).click();
  await page.getByRole("button", { name: "查看操作说明" }).click();
  await expect(page.getByRole("region", { name: /操作说明/ })).toBeVisible();
  await page.getByRole("button", { name: "收起操作说明" }).click();
  await expect(page.getByRole("region", { name: /操作说明/ })).toHaveCount(0);
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
});

test("guidance preferences preserve routes, drafts, roles, and Demo isolation", async ({
  browser,
  page,
  request,
}) => {
  const workspace = await createWorkspace(request, "引导偏好边界验收工作区");
  await enterWorkspace(page, workspace, workspace.admin_code, "引导管理员");
  const accountId = await createAccount(page, workspace.workspace_id);
  const editorCode = await issueCode(page, workspace.workspace_id, "editor");
  const root = `/workspaces/${workspace.workspace_id}`;
  const filteredAnalysis = `${root}/analysis?platform=douyin&account=${accountId}&status=failed&sort=oldest&page=2`;

  await page.goto(filteredAnalysis);
  await expect(page.getByRole("heading", { level: 1, name: "分析中心" })).toBeVisible();
  const businessRequests: string[] = [];
  page.on("request", (requestToInspect) => {
    if (requestToInspect.url().startsWith(api)) {
      businessRequests.push(`${requestToInspect.method()} ${requestToInspect.url()}`);
    }
  });
  await page.getByRole("radio", { name: "专业" }).click();
  await page.getByRole("switch", { name: "页面引导" }).click();
  await expect(page).toHaveURL(filteredAnalysis);
  await expect(page.getByText("建议先做")).toHaveCount(0);
  expect(businessRequests).toEqual([]);

  await page.reload();
  await expect(page.getByRole("radio", { name: "专业" })).toBeChecked();
  await expect(page.getByRole("switch", { name: "页面引导" })).not.toBeChecked();
  await expect(page).toHaveURL(filteredAnalysis);

  await page.getByRole("switch", { name: "页面引导" }).click();
  await page.goto(`${root}/generation?platform=douyin&account=${accountId}&step=scope`);
  await page.getByLabel("生成目标").fill("保留的生成草稿");
  await page.getByRole("button", { name: "风格与参考", exact: true }).click();
  await expect(page).toHaveURL(
    `${root}/generation?platform=douyin&account=${accountId}&step=references`,
  );
  await page.reload();
  await page.getByRole("button", { name: "范围与目标", exact: true }).click();
  await expect(page.getByLabel("生成目标")).toHaveValue("保留的生成草稿");
  await expect(page.getByRole("radio", { name: "专业" })).toBeChecked();
  await page.goBack();
  await expect(page).toHaveURL(filteredAnalysis);
  await page.goForward();
  await expect(page).toHaveURL(
    `${root}/generation?platform=douyin&account=${accountId}&step=scope`,
  );

  await page.goto("/demo");
  await expect(page.getByRole("radio", { name: "易懂" })).toBeChecked();
  await expect(page.getByRole("switch", { name: "页面引导" })).toBeChecked();
  await page.goto(`${root}/generation?platform=douyin&account=${accountId}&step=scope`);
  await expect(page.getByRole("radio", { name: "专业" })).toBeChecked();
  await expect(page.getByRole("switch", { name: "页面引导" })).toBeChecked();

  const pages = [
    ["", "看清各账号目前缺什么数据、有哪些待处理内容，以及现在最值得先做哪一件事。", "按账号分别查看数据完整度、风险和下一步，不混算不同平台的业务指标。"],
    ["/contents", "集中查看每条作品、发布状态、数据、分析和风险结果。", "按平台、账号、栏目和数据状态查找内容；平台数据始终分别展示。"],
    ["/imports", "把作品和发布后的运营数据录入系统；确认前不会写入正式记录。", "四种方式共享暂存、预览、修正和人工确认边界；确认前不会写入正式内容或快照。"],
    ["/generation", "根据已确认的事实、账号风格和参考内容，生成标题、文案和封面。", "范围、事实、风格与参考、生成编辑和发布前复核依次完成；仅恢复不含正文、图片或凭据的安全元数据。"],
    ["/preflight", "集中检查准备发布的内容，处理风险、图片文字识别和资料不足问题。", "标题、正文和封面 OCR 的确定性规则与 RAG 辅助判断分开展示；无证据不代表安全通过。"],
    ["/settings/jobs", "查看导入、分析、生成和备份等耗时任务有没有完成，失败后该怎么处理。", "只展示状态、阶段和安全错误码，不展示任务正文、截图或模型响应。"],
  ] as const;
  for (const [suffix, simple, professional] of pages) {
    await page.goto(`${root}${suffix}`);
    await page.getByRole("radio", { name: "易懂" }).click();
    await expect(page.getByText(simple)).toBeVisible();
    await page.getByRole("radio", { name: "专业" }).click();
    await expect(page.getByText(professional)).toBeVisible();
  }

  const editor = await browser.newContext();
  const editorPage = await editor.newPage();
  await enterWorkspace(editorPage, workspace, editorCode, "引导编辑者");
  await editorPage.goto(
    `${root}/generation?platform=douyin&account=${accountId}&step=scope`,
  );
  await expect(
    editorPage.getByText("选择平台、账号和栏目后开始生成"),
  ).toBeVisible();
  await expect(editorPage.getByRole("button", { name: "开始生成" })).toHaveCount(0);
  await editor.close();

});
