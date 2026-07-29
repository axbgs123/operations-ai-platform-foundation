import { expect, test } from "@playwright/test";

const api = "http://127.0.0.1:8100";

test("千问配置、预算和未授权受控验证保持安全", async ({ page, request }) => {
  const workspaceResponse = await request.post(`${api}/v1/workspaces`, {
    data: { name: "千问配置 E2E 合成工作区" },
  });
  expect(workspaceResponse.status()).toBe(201);
  const workspace = await workspaceResponse.json();
  const loginResponse = await request.post(`${api}/v1/sessions/invite`, {
    data: {
      code: workspace.admin_code,
      display_name: "千问配置 E2E 管理员",
    },
  });
  expect(loginResponse.status()).toBe(201);
  const login = await loginResponse.json();
  const headers = { "X-CSRF-Token": login.csrf_token };

  const configResponse = await request.post(
    `${api}/v1/workspaces/${workspace.workspace_id}/model-configs`,
    {
      headers,
      data: {
        provider: "qianwen",
        model_id: "qwen3.5-plus-2026-04-20",
        region: "cn-beijing",
        provider_workspace_id: "llm-synthetic1234",
        capabilities: ["text"],
        status: "experimental",
        api_key: "synthetic-e2e-key-never-real",
      },
    },
  );
  expect(configResponse.status()).toBe(201);
  const config = await configResponse.json();
  expect(JSON.stringify(config)).not.toContain("synthetic-e2e-key-never-real");
  expect(JSON.stringify(config)).not.toContain("llm-synthetic1234");

  const policyResponse = await request.put(
    `${api}/v1/workspaces/${workspace.workspace_id}/model-usage/policy`,
    {
      headers,
      data: {
        capability: "text",
        enabled: true,
        max_concurrent_calls: 1,
        max_calls_per_minute: 2,
        daily_request_limit: 2,
        daily_input_token_limit: 1000,
        daily_output_token_limit: 500,
        daily_embedding_token_limit: 0,
        daily_ocr_image_limit: 0,
        daily_generated_image_limit: 0,
        daily_cost_limit_microunits: 10000,
        currency: "CNY",
      },
    },
  );
  expect(policyResponse.status()).toBe(200);

  const validationResponse = await request.post(
    `${api}/v1/workspaces/${workspace.workspace_id}/model-validations`,
    {
      headers,
      data: {
        model_config_id: config.id,
        region: "cn-beijing",
        capability: "text",
        model_id: "qwen3.5-plus-2026-04-20",
        max_calls: 1,
        max_input_tokens: 100,
        max_output_tokens: 100,
        max_images: 0,
        max_cost_microunits: 1000,
        confirm_real_call: true,
      },
    },
  );
  expect(validationResponse.status()).toBe(201);
  const validation = await validationResponse.json();
  expect(validation.result).toBe("not_run");
  expect(validation.safe_error_code).toBe(
    "explicit_user_authorization_missing",
  );
  expect(validation.evidence.external_network_accessed).toBe(false);
  expect(validation.evidence.cost_microunits).toBe(0);

  const storage = await request.storageState();
  await page.context().addCookies(storage.cookies);
  await page.goto(
    `/workspaces/${workspace.workspace_id}/settings/models`,
  );
  await expect(page.getByText("千问模型配置")).toBeVisible();
  await expect(page.getByText("experimental").first()).toBeVisible();
  await expect(
    page.getByText(/数据将发送到所选地域/),
  ).toBeVisible();
});
