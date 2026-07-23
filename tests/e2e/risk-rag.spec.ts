import { expect, test } from "@playwright/test";

const api = "http://127.0.0.1:8100";

test("管理后台隔离展示知识生命周期与评估门槛", async ({ page, request }) => {
  const workspaceResponse = await request.post(`${api}/v1/workspaces`, {
    data: { name: "合成工作区A" },
  });
  expect(workspaceResponse.ok()).toBeTruthy();
  const workspace = await workspaceResponse.json();
  const workspaceBResponse = await request.post(`${api}/v1/workspaces`, {
    data: { name: "合成工作区B" },
  });
  expect(workspaceBResponse.ok()).toBeTruthy();
  const workspaceB = await workspaceBResponse.json();

  const loginResponse = await request.post(`${api}/v1/sessions/invite`, {
    data: { code: workspace.admin_code, display_name: "合成管理员" },
  });
  expect(loginResponse.ok()).toBeTruthy();
  const session = await loginResponse.json();
  const cookies = await request.storageState();
  const headers = { "X-CSRF-Token": session.csrf_token };

  const createDocument = await request.post(
    `${api}/v1/workspaces/${workspace.workspace_id}/risk-documents`,
    {
      data: {
        platform: "douyin",
        source_level: "S2",
        title: "合成平台提示文档",
        private_document_id: "synthetic-douyin-001",
        authorization_status: "authorized",
      },
      headers,
    },
  );
  expect(createDocument.status()).toBe(201);
  const document = await createDocument.json();

  const parse = await request.post(
    `${api}/v1/workspaces/${workspace.workspace_id}/risk-documents/${document.id}/parse`,
    {
      data: {
        text: "人工合成的抖音风控提示，仅用于隔离测试。",
        source_location: "synthetic://risk-rag/e2e",
      },
      headers,
    },
  );
  expect(parse.ok()).toBeTruthy();
  const review = await request.post(
    `${api}/v1/workspaces/${workspace.workspace_id}/risk-documents/${document.id}/submit-review`,
    { headers },
  );
  expect(review.ok()).toBeTruthy();
  const activate = await request.post(
    `${api}/v1/workspaces/${workspace.workspace_id}/risk-documents/${document.id}/activate`,
    { headers },
  );
  expect(activate.ok()).toBeTruthy();

  await page.context().addCookies(cookies.cookies);
  await page.goto(
    `/workspaces/${workspace.workspace_id}/risk-knowledge`,
  );
  await expect(page.getByText("合成平台提示文档")).toBeVisible();
  await expect(page.getByText("工程回归门槛，不是生产准确率")).toBeVisible();
  await expect(
    page.getByText("辅助判断，不保证通过平台审核"),
  ).toBeVisible();

  const xhsResponse = await request.get(
    `${api}/v1/workspaces/${workspace.workspace_id}/risk-documents?platform=xiaohongshu`,
  );
  expect(xhsResponse.ok()).toBeTruthy();
  expect(await xhsResponse.json()).toEqual([]);

  const crossWorkspaceResponse = await request.get(
    `${api}/v1/workspaces/${workspaceB.workspace_id}/risk-documents`,
  );
  expect(crossWorkspaceResponse.status()).toBe(404);
});
