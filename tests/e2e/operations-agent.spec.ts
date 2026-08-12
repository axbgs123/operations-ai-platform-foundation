import {
  APIRequestContext,
  expect,
  request as playwrightRequest,
  test,
} from "@playwright/test";


const api =
  process.env.FRESH_INSTALL_API_URL ?? "http://127.0.0.1:8100";

type Json = Record<string, any>;

async function json(response: Awaited<ReturnType<APIRequestContext["get"]>>) {
  const body = await response.json();
  expect(response.ok(), JSON.stringify(body)).toBeTruthy();
  return body as Json;
}

test("editor completes the governed optimization loop", async ({ page, request }) => {
  test.setTimeout(90_000);
  const workspace = await json(
    await request.post(`${api}/v1/workspaces`, {
      data: { name: "Task 8 智能体验收工作区" },
    }),
  );
  const admin = await json(
    await request.post(`${api}/v1/sessions/invite`, {
      data: {
        code: workspace.admin_code,
        display_name: "Task 8 合成管理员",
      },
    }),
  );
  const adminHeaders = { "X-CSRF-Token": admin.csrf_token };
  const account = await json(
    await request.post(
      `${api}/v1/workspaces/${workspace.workspace_id}/accounts`,
      {
        headers: adminHeaders,
        data: {
          platform: "douyin",
          name: "Task 8 合成运营账号",
          objectives: ["reach", "engagement", "growth", "conversion"],
          metric_weights: { views: 0.6, completion_rate: 0.4 },
          benchmark_sample_size: 30,
        },
      },
    ),
  );
  await json(
    await request.post(
      `${api}/v1/workspaces/${workspace.workspace_id}/model-configs`,
      {
        headers: adminHeaders,
        data: {
          provider: "mock",
          model_id: "mock-v1",
          capabilities: ["text"],
          status: "verified",
          api_key: "synthetic-task8-key-never-real",
        },
      },
    ),
  );
  const createdContent = await json(
    await request.post(`${api}/v1/contents`, {
      headers: adminHeaders,
      data: {
        workspace_id: workspace.workspace_id,
        account_id: account.id,
        platform: "douyin",
        content_type: "video",
        title: "Task 8 人工合成待优化内容",
        body: "纯合成 E2E 数据，不包含真实运营或个人信息。",
        work_url: "https://example.invalid/task8-agent",
      },
    }),
  );
  const content = await json(
    await request.patch(`${api}/v1/contents/${createdContent.id}`, {
      headers: adminHeaders,
      data: { status: "published" },
    }),
  );
  const snapshot = await json(
    await request.post(`${api}/v1/contents/${content.id}/snapshots`, {
      headers: adminHeaders,
      data: {
        collected_at: new Date(
          new Date(content.published_at).getTime() + 60 * 60 * 1000,
        ).toISOString(),
        source: "manual",
        metrics: [
          { key: "views", raw_value: 120 },
          { key: "completion_rate", raw_value: 0.42 },
        ],
      },
    }),
  );
  await json(
    await request.post(
      `${api}/v1/contents/${content.id}/snapshots/${snapshot.id}/confirm`,
      { headers: adminHeaders },
    ),
  );
  const invite = await json(
    await request.post(
      `${api}/v1/workspaces/${workspace.workspace_id}/members/codes`,
      { headers: adminHeaders, data: { role: "editor" } },
    ),
  );

  const editorContext = await playwrightRequest.newContext();
  try {
    const editor = await json(
      await editorContext.post(`${api}/v1/sessions/invite`, {
        data: {
          code: invite.code,
          display_name: "Task 8 独立编辑者",
        },
      }),
    );
    const storage = await editorContext.storageState();
    await page.context().addCookies(storage.cookies);
    await page.addInitScript((csrfToken) => {
      sessionStorage.setItem("workspace_csrf", csrfToken);
    }, editor.csrf_token);

    await page.goto(`/workspaces/${workspace.workspace_id}/agent`);
    await expect(
      page.getByRole("heading", { name: "今天想解决什么运营问题？" }),
    ).toBeVisible();
    await page.getByRole("textbox", { name: "给运营智能体发消息" }).fill("你好");
    await page.getByRole("button", { name: "发送" }).click();
    await expect(
      page.getByText(/你好，我可以帮你分析账号表现/),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("button", { name: "打开会话：你好" }),
    ).toBeVisible();
    await expect(
      page.getByText(/你好，我可以帮你分析账号表现/),
    ).toBeVisible();
    await page.getByRole("button", { name: "任务与执行" }).click();
    await expect(
      page.getByRole("heading", { name: "今天建议先处理" }),
    ).toBeVisible();
    await expect(page.getByLabel("执行账号")).toHaveValue(account.id);
    await expect(
      page.getByLabel("执行账号").getByRole("option", {
        name: "抖音 · Task 8 合成运营账号",
      }),
    ).toHaveCount(1);
    await page.getByRole("button", { name: "生成处理计划" }).click();
    await expect(
      page.getByRole("button", { name: "批准计划" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "批准计划" }).click();

    await expect(
      page
        .getByLabel("优化结果")
        .getByText("优化草稿已完成风控扫描，仍需人工复核后使用。"),
    ).toBeVisible({ timeout: 75_000 });
    await expect(
      page.getByText("辅助判断，不保证通过平台审核"),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "发布" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /支付/ })).toHaveCount(0);

    const runs = await json(
      await editorContext.get(
        `${api}/v1/workspaces/${workspace.workspace_id}/agent/runs`,
      ),
    );
    expect(runs.items).toHaveLength(1);
    expect(runs.items[0].status).toBe("succeeded");
    const run = await json(
      await editorContext.get(
        `${api}/v1/workspaces/${workspace.workspace_id}/agent/runs/${runs.items[0].id}`,
      ),
    );
    expect(run.steps).toHaveLength(9);
    expect(run.steps.every((step: Json) => step.status === "succeeded")).toBeTruthy();
    expect(JSON.stringify(run)).not.toContain("synthetic-task8-key-never-real");
  } finally {
    await editorContext.dispose();
  }
});
