import { expect, test } from "@playwright/test";

const api = "http://127.0.0.1:8100";

test("脱敏支持页完成暂存、Mock识别、轮询与Web人工确认", async ({ page, request }) => {
  await page.setContent(`
    <main>
      <h1 data-page-version="douyin-creator-v1">Synthetic Douyin detail</h1>
      <button id="preview">预览采集区域</button>
      <p id="status">需要人工确认</p>
    </main>
  `);
  await page.locator("#preview").click();
  await expect(page.locator("#status")).toHaveText("需要人工确认");
  expect(await page.locator("h1").getAttribute("data-page-version")).toBe(
    "douyin-creator-v1",
  );

  const workspaceResponse = await request.post(`${api}/v1/workspaces`, {
    data: { name: "扩展E2E合成工作区" },
  });
  const workspace = await workspaceResponse.json();
  const otherResponse = await request.post(`${api}/v1/workspaces`, {
    data: { name: "扩展E2E隔离工作区" },
  });
  const other = await otherResponse.json();
  const loginResponse = await request.post(`${api}/v1/sessions/invite`, {
    data: { code: workspace.admin_code, display_name: "扩展E2E管理员" },
  });
  const login = await loginResponse.json();
  const accountResponse = await request.post(
    `${api}/v1/workspaces/${workspace.workspace_id}/accounts`,
    {
      headers: { "X-CSRF-Token": login.csrf_token },
      data: {
        platform: "douyin",
        name: "扩展E2E合成账号",
        objectives: ["reach"],
        metric_weights: { views: 1 },
        benchmark_sample_size: 30,
      },
    },
  );
  expect(accountResponse.status()).toBe(201);
  const extensionCodeResponse = await request.post(
    `${api}/v1/workspaces/${workspace.workspace_id}/members/codes`,
    {
      headers: { "X-CSRF-Token": login.csrf_token },
      data: { role: "editor" },
    },
  );
  expect(extensionCodeResponse.status()).toBe(201);
  const extensionCode = await extensionCodeResponse.json();
  const bindingResponse = await request.post(`${api}/v1/extension/bind`, {
    headers: {
      "Idempotency-Key": `extension-e2e-bind-${Date.now()}`,
      "X-Extension-Client": "extension-e2e",
    },
    data: { invite_code: extensionCode.code, client_id: "extension-e2e" },
  });
  expect(bindingResponse.status()).toBe(201);
  const binding = await bindingResponse.json();
  const captureHeaders = {
    Authorization: `Bearer ${binding.access_token}`,
    "Idempotency-Key": "extension-e2e-capture",
  };
  const captureData = {
    platform: "douyin",
    page_version: "douyin-creator-v1",
    page_identifier: "synthetic-e2e-detail",
    collected_at: "2026-07-23T08:00:00Z",
    screenshot_data_url: "data:image/png;base64,U1lOVEhFVElD",
  };
  const captureResponse = await request.post(
    `${api}/v1/extension/workspaces/${workspace.workspace_id}/capture-tasks`,
    { headers: captureHeaders, data: captureData },
  );
  expect(captureResponse.status()).toBe(202);
  const capture = await captureResponse.json();
  expect(capture.status).toBe("succeeded");

  const duplicate = await request.post(
    `${api}/v1/extension/workspaces/${workspace.workspace_id}/capture-tasks`,
    { headers: captureHeaders, data: captureData },
  );
  expect((await duplicate.json()).task_id).toBe(capture.task_id);
  const isolated = await request.get(
    `${api}/v1/extension/workspaces/${other.workspace_id}/capture-tasks/${capture.task_id}`,
    { headers: { Authorization: `Bearer ${binding.access_token}` } },
  );
  expect(isolated.status()).toBe(404);

  const storage = await request.storageState();
  await page.context().addCookies(storage.cookies);
  await page.goto(`/workspaces/${workspace.workspace_id}/imports?capture_task_id=${capture.task_id}`);
  await page.evaluate((csrf) => sessionStorage.setItem("workspace_csrf", csrf), login.csrf_token);
  await page.reload();
  await expect(page.getByText("扩展识别结果待确认")).toBeVisible();
  await page.getByLabel("修正 views").fill("1200");
  await page.getByRole("button", { name: "人工确认并写入快照" }).click();
  await expect(page.getByText("已写入 1 条正式快照。")).toBeVisible();
});
