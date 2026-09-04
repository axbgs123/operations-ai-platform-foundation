import { APIRequestContext, expect, test } from "@playwright/test";


const api = process.env.FRESH_INSTALL_API_URL ?? "http://127.0.0.1:8100";

type Json = Record<string, any>;
type Platform = "douyin" | "xiaohongshu";

async function json(response: Awaited<ReturnType<APIRequestContext["get"]>>) {
  const body = await response.json();
  expect(response.ok(), JSON.stringify(body)).toBeTruthy();
  return body as Json;
}

async function createAccount(
  context: APIRequestContext,
  workspaceId: string,
  csrf: string,
  platform: Platform,
) {
  return json(
    await context.post(`${api}/v1/workspaces/${workspaceId}/accounts`, {
      headers: { "X-CSRF-Token": csrf },
      data: {
        platform,
        name: `TikHub 合成${platform === "douyin" ? "抖音" : "小红书"}账号`,
        objectives: ["reach", "engagement"],
        metric_weights:
          platform === "douyin"
            ? { views: 0.6, completion_rate: 0.4 }
            : { impressions: 0.6, cover_click_rate: 0.4 },
        benchmark_sample_size: 30,
      },
    }),
  );
}

async function createPublishedContent(
  context: APIRequestContext,
  workspaceId: string,
  csrf: string,
  accountId: string,
  platform: Platform,
) {
  const created = await json(
    await context.post(`${api}/v1/contents`, {
      headers: { "X-CSRF-Token": csrf },
      data: {
        workspace_id: workspaceId,
        account_id: accountId,
        platform,
        content_type: platform === "douyin" ? "video" : "image_text",
        title: `TikHub ${platform} 公开数据回收验收`,
        body: "人工合成 E2E 内容，不包含真实账号或运营数据。",
      },
    }),
  );
  return json(
    await context.patch(`${api}/v1/contents/${created.id}`, {
      headers: { "X-CSRF-Token": csrf },
      data: { status: "published" },
    }),
  );
}

async function bindAndCollect(
  context: APIRequestContext,
  workspaceId: string,
  csrf: string,
  content: Json,
  publicUrl: string,
  platformContentId: string,
) {
  const bound = await json(
    await context.put(
      `${api}/v1/workspaces/${workspaceId}/public-data/contents/${content.id}/binding`,
      {
        headers: { "X-CSRF-Token": csrf },
        data: {
          public_url: publicUrl,
          platform_content_id: platformContentId,
          published_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
        },
      },
    ),
  );
  expect(bound.jobs.map((job: Json) => job.target_window)).toEqual([
    "1h",
    "24h",
    "72h",
    "7d",
  ]);
  const manual = await json(
    await context.post(
      `${api}/v1/workspaces/${workspaceId}/public-data/contents/${content.id}/collect-now`,
      { headers: { "X-CSRF-Token": csrf } },
    ),
  );
  expect(manual.target_window).toMatch(/^manual-/);
}

test("admin completes the two-platform public intelligence loop with Mock TikHub", async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);

  const workspace = await json(
    await request.post(`${api}/v1/workspaces`, {
      data: { name: `TikHub Mock 验收-${Date.now()}` },
    }),
  );
  const session = await json(
    await request.post(`${api}/v1/sessions/invite`, {
      data: {
        code: workspace.admin_code,
        display_name: "TikHub 合成管理员",
      },
    }),
  );
  const workspaceId = workspace.workspace_id as string;
  const csrf = session.csrf_token as string;
  const headers = { "X-CSRF-Token": csrf };

  await test.step("连接 Mock TikHub 并建立双平台作品回收计划", async () => {
    await json(
      await request.put(`${api}/v1/workspaces/${workspaceId}/public-data/provider`, {
        headers,
        data: {
          api_key: "synthetic-tikhub-e2e-key-never-real",
          endpoint_region: "china",
          daily_request_limit: 100,
        },
      }),
    );
    const connection = await json(
      await request.post(
        `${api}/v1/workspaces/${workspaceId}/public-data/provider/test`,
        { headers },
      ),
    );
    expect(connection.connected).toBeTruthy();

    const douyin = await createAccount(request, workspaceId, csrf, "douyin");
    const xiaohongshu = await createAccount(
      request,
      workspaceId,
      csrf,
      "xiaohongshu",
    );
    const douyinContent = await createPublishedContent(
      request,
      workspaceId,
      csrf,
      douyin.id,
      "douyin",
    );
    const xiaohongshuContent = await createPublishedContent(
      request,
      workspaceId,
      csrf,
      xiaohongshu.id,
      "xiaohongshu",
    );
    await bindAndCollect(
      request,
      workspaceId,
      csrf,
      douyinContent,
      "https://www.douyin.com/video/7300012345678901",
      "7300012345678901",
    );
    await bindAndCollect(
      request,
      workspaceId,
      csrf,
      xiaohongshuContent,
      "https://www.xiaohongshu.com/explore/64e1234567890abc",
      "64e1234567890abc",
    );
  });

  const state = await request.storageState();
  await page.context().addCookies(state.cookies);
  await page.addInitScript((token) => {
    sessionStorage.setItem("workspace_csrf", token);
  }, csrf);

  await test.step("在设置页确认 TikHub 已连接", async () => {
    await page.goto(`/workspaces/${workspaceId}/settings/public-data`);
    await expect(page.getByRole("heading", { name: "公开数据采集" })).toBeVisible();
    await expect(page.getByText("连接正常")).toBeVisible();
    await expect(page.getByText("不会自动发布内容")).toBeVisible();
  });

  await test.step("在热点创作页完成双平台搜索、对标和评论分析", async () => {
    await page.goto(`/workspaces/${workspaceId}/hotspots`);
    await page.getByRole("button", { name: "对标、评论与日报" }).click();
    await expect(page.getByRole("heading", { name: "今日运营简报" })).toBeVisible();

    const searchForm = page
      .getByRole("button", { name: "搜索公开内容" })
      .locator("xpath=ancestor::form");
    await searchForm.getByLabel("平台").selectOption("douyin");
    await searchForm.getByLabel("想搜索什么").fill("AI 运营");
    await searchForm.getByRole("button", { name: "搜索公开内容" }).click();
    await expect(page.getByText("搜索完成。相同关键词 10 分钟内再次查询会直接使用已有结果，避免重复调用。"))
      .toBeVisible();
    await expect(page.getByRole("heading", { name: "“AI 运营”的公开内容" })).toBeVisible();
    await expect(searchForm.getByRole("button", { name: "搜索公开内容" })).toBeEnabled();

    await searchForm.getByLabel("平台").selectOption("xiaohongshu");
    await searchForm.getByLabel("想搜索什么").fill("内容提效");
    await searchForm.getByRole("button", { name: "搜索公开内容" }).click();
    await expect(page.getByRole("heading", { name: "“内容提效”的公开内容" })).toBeVisible();

    const competitorForm = page
      .getByRole("button", { name: "添加并采集" })
      .locator("xpath=ancestor::form");
    await competitorForm.getByLabel("平台").selectOption("douyin");
    await competitorForm.getByLabel("账号备注名").fill("抖音同赛道样本");
    await competitorForm
      .getByLabel("公开主页链接")
      .fill("https://www.douyin.com/user/sec-e2e-douyin");
    await competitorForm.getByRole("button", { name: "添加并采集" }).click();
    await expect(page.getByText("抖音同赛道样本")).toBeVisible();

    await competitorForm.getByLabel("平台").selectOption("xiaohongshu");
    await competitorForm.getByLabel("账号备注名").fill("小红书同赛道样本");
    await competitorForm
      .getByLabel("公开主页链接")
      .fill("https://www.xiaohongshu.com/user/profile/e2e-xhs-user");
    await competitorForm.getByRole("button", { name: "添加并采集" }).click();
    await expect(page.getByText("小红书同赛道样本")).toBeVisible();

    const commentsForm = page
      .getByRole("button", { name: "分析评论" })
      .locator("xpath=ancestor::form");
    await commentsForm.getByLabel("平台").selectOption("douyin");
    await commentsForm
      .getByLabel("公开作品链接")
      .fill("https://www.douyin.com/video/7300012345678901");
    await commentsForm.getByLabel("作品 ID（可选）").fill("7300012345678901");
    await commentsForm.getByRole("button", { name: "分析评论" }).click();
    await expect(page.getByText("评论分析完成，结果已加入今日简报。这里使用规则归类，不额外消耗文字模型额度。"))
      .toBeVisible();

    await commentsForm.getByLabel("平台").selectOption("xiaohongshu");
    await commentsForm
      .getByLabel("公开作品链接")
      .fill("https://www.xiaohongshu.com/explore/64e1234567890abc");
    await commentsForm.getByLabel("作品 ID（可选）").fill("64e1234567890abc");
    await commentsForm.getByRole("button", { name: "分析评论" }).click();

    await expect(
      page.locator("dt", { hasText: /^正在监测的账号$/ }).locator("..").locator("dd"),
    ).toHaveText("2");
    await expect(
      page.locator("dt", { hasText: /^评论分析$/ }).locator("..").locator("dd"),
    ).toHaveText("2");
    await expect(page.getByRole("heading", { name: "爆款预警" })).toBeVisible();
    await expect(page.getByText("价格与购买（1）").first()).toBeVisible();
    await expect(page.getByText("教程与使用（2）").first()).toBeVisible();
  });

  await test.step("接口结果保持平台与工作区隔离", async () => {
    const report = await json(
      await request.get(`${api}/v1/workspaces/${workspaceId}/public-data/daily-report`),
    );
    expect(report.monitored_accounts).toBe(2);
    expect(report.comment_analyses_24h).toBe(2);
    const searches = await json(
      await request.get(`${api}/v1/workspaces/${workspaceId}/public-data/trend-searches`),
    );
    expect(new Set(searches.map((item: Json) => item.platform))).toEqual(
      new Set(["douyin", "xiaohongshu"]),
    );
  });
});
