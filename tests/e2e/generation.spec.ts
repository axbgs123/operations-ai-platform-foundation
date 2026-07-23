import { expect, Page, test } from "@playwright/test";


type GenerationFixtures = {
  accountId: string;
  columnCampaignId: string;
  modelConfigId: string;
  styleProfileId: string;
  viralLibraryItemId: string;
};

async function createGenerationFixtures(
  page: Page,
  workspaceId: string,
): Promise<GenerationFixtures> {
  return page.evaluate(async ({ workspaceId }) => {
    const apiRoot = "http://127.0.0.1:8100";
    const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
    async function api<T>(
      path: string,
      method = "GET",
      body?: object,
    ): Promise<T> {
      const response = await fetch(`${apiRoot}${path}`, {
        method,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(method === "GET" ? {} : { "X-CSRF-Token": csrf }),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) {
        throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`);
      }
      return response.json() as Promise<T>;
    }

    const account = await api<{ id: string }>(
      `/v1/workspaces/${workspaceId}/accounts`,
      "POST",
      {
        platform: "douyin",
        name: "合成服装运营账号",
        objectives: ["reach", "engagement", "growth", "conversion"],
        metric_weights: {
          views: 0.4,
          likes: 0.2,
          followers_gained: 0.2,
          profile_visits: 0.2,
        },
        benchmark_sample_size: 10,
      },
    );
    const column = await api<{ id: string }>(
      `/v1/workspaces/${workspaceId}/accounts/${account.id}/columns-campaigns`,
      "POST",
      { name: "夏日通勤穿搭", kind: "column" },
    );
    const model = await api<{ id: string }>(
      `/v1/workspaces/${workspaceId}/model-configs`,
      "POST",
      {
        provider: "mock-contract",
        model_id: "mock-text-v1",
        capabilities: ["text"],
        status: "experimental",
        api_key: "synthetic-e2e-key-not-real",
      },
    );
    await api(
      `/v1/workspaces/${workspaceId}/accounts/${account.id}/viral-thresholds`,
      "PUT",
      {
        rules: [
          {
            category: "traffic",
            metric_key: "views",
            minimum_value: 950,
          },
        ],
      },
    );

    let topContentId = "";
    for (let index = 0; index < 10; index += 1) {
      const content = await api<{ id: string }>(
        "/v1/contents",
        "POST",
        {
          workspace_id: workspaceId,
          account_id: account.id,
          platform: "douyin",
          content_type: "video",
          title: `合成穿搭样本 ${index + 1}`,
          body: "合成 E2E 数据，不包含真实运营内容。",
        },
      );
      const published = await api<{ published_at: string }>(
        `/v1/contents/${content.id}`,
        "PATCH",
        { status: "published" },
      );
      const collectedAt = new Date(
        new Date(published.published_at).getTime() + 24 * 60 * 60 * 1000,
      ).toISOString();
      const snapshot = await api<{ id: string }>(
        `/v1/contents/${content.id}/snapshots`,
        "POST",
        {
          collected_at: collectedAt,
          source: "manual",
          metrics: [
            { key: "views", raw_value: (index + 1) * 100 },
            { key: "likes", raw_value: (index + 1) * 10 },
            { key: "followers_gained", raw_value: index + 1 },
            { key: "profile_visits", raw_value: (index + 1) * 5 },
          ],
        },
      );
      await api(
        `/v1/contents/${content.id}/snapshots/${snapshot.id}/confirm`,
        "POST",
      );
      if (index === 9) topContentId = content.id;
    }

    await api(
      `/v1/workspaces/${workspaceId}/accounts/${account.id}/style-samples`,
      "POST",
      { content_id: topContentId, column_campaign_id: null },
    );
    const pendingStyle = await api<{ id: string }>(
      `/v1/workspaces/${workspaceId}/accounts/${account.id}/style-profiles/extract`,
      "POST",
      { column_campaign_id: null },
    );
    const style = await api<{ id: string }>(
      `/v1/workspaces/${workspaceId}/style-profiles/${pendingStyle.id}/confirm`,
      "POST",
    );
    const candidates = await api<Array<{ id: string }>>(
      `/v1/workspaces/${workspaceId}/accounts/${account.id}/viral-candidates/evaluate`,
      "POST",
      { content_type: "video", maturity_bucket: "24h" },
    );
    const viral = await api<{ id: string }>(
      `/v1/workspaces/${workspaceId}/viral-candidates/${candidates[0].id}/confirm`,
      "POST",
      {
        strategy_tags: ["结果前置", "穿搭拆解"],
        applicable_scenarios: ["新品讲解"],
        structure_summary: "痛点开场—面料说明—搭配建议—行动引导",
      },
    );

    return {
      accountId: account.id,
      columnCampaignId: column.id,
      modelConfigId: model.id,
      styleProfileId: style.id,
      viralLibraryItemId: viral.id,
    };
  }, { workspaceId });
}

async function factContext(
  page: Page,
  workspaceId: string,
): Promise<{
  sourceId: string;
  confirmedItemIds: string[];
}> {
  return page.evaluate(async ({ workspaceId }) => {
    const root = "http://127.0.0.1:8100";
    const [sourcesResponse, contextResponse] = await Promise.all([
      fetch(`${root}/v1/workspaces/${workspaceId}/fact-sources`, {
        credentials: "include",
      }),
      fetch(`${root}/v1/workspaces/${workspaceId}/fact-context`, {
        credentials: "include",
      }),
    ]);
    const sources = await sourcesResponse.json() as Array<{ id: string }>;
    const context = await contextResponse.json() as {
      confirmed_items: Array<{ id: string }>;
    };
    return {
      sourceId: sources.at(-1)?.id ?? "",
      confirmedItemIds: context.confirmed_items.map((item) => item.id),
    };
  }, { workspaceId });
}

test("governed generation saves a checked draft and explains degraded paths", async ({
  page,
  request,
}) => {
  const workspaceResponse = await request.post(
    "http://127.0.0.1:8100/v1/workspaces",
    { data: { name: `Generation E2E ${Date.now()}` } },
  );
  const workspace = await workspaceResponse.json() as {
    workspace_id: string;
    admin_code: string;
  };

  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(workspace.admin_code);
  await page.getByLabel("显示名称").fill("生成流程管理员");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page).toHaveURL(
    `/workspaces/${workspace.workspace_id}/settings/members`,
  );
  const fixtures = await createGenerationFixtures(page, workspace.workspace_id);

  await page.goto(`/workspaces/${workspace.workspace_id}/facts`);
  await page.getByLabel("上传标题").fill("合成服装规格");
  await page.getByLabel("选择资料文件").setInputFiles({
    name: "synthetic-clothing.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("面料：100% 棉\n颜色：深蓝"),
  });
  await page.getByRole("button", { name: "上传并解析" }).click();
  await expect(page.getByText("文件已保存；可解析字段会作为候选事实显示")).toBeVisible();
  await page.getByRole("button", { name: "确认面料" }).click();
  await expect(page.getByText("已确认：面料")).toBeVisible();
  const facts = await factContext(page, workspace.workspace_id);

  await page.goto(`/workspaces/${workspace.workspace_id}/generation`);
  await expect(
    page.getByLabel("沿用已确认历史风格（默认开启）"),
  ).toBeChecked();
  await page.getByLabel("账号 ID").fill(fixtures.accountId);
  await page.getByLabel("模型配置 ID").fill(fixtures.modelConfigId);
  await page.getByLabel("栏目或活动 ID").fill(fixtures.columnCampaignId);
  await page.getByLabel("风格档案 ID").fill(fixtures.styleProfileId);
  await page
    .getByLabel("爆款引用 ID（最多 3 条）")
    .fill(fixtures.viralLibraryItemId);
  await page.getByLabel("生成目标").fill("夏日通勤新品");
  await page
    .getByLabel("已确认事实 ID（逗号分隔）")
    .fill(facts.confirmedItemIds.join(","));
  await page.getByLabel("资料来源 ID（逗号分隔）").fill(facts.sourceId);
  await page.getByRole("button", { name: "生成标题与文案" }).click();
  await expect(page.getByText("执行成功")).toBeVisible();
  await page.getByLabel("人工最终标题").fill("人工编辑：夏日棉质通勤穿搭");
  await page.getByRole("button", { name: "复检并保存草稿" }).click();
  await expect(page.getByText("复检完成，草稿已保存")).toBeVisible();
  await expect(
    page.getByText("未检索到有效风控证据；草稿已保存，但不能进入待发布"),
  ).toBeVisible();

  await page.goto(`/workspaces/${workspace.workspace_id}/generation`);
  await page.getByLabel("沿用已确认历史风格（默认开启）").uncheck();
  await page.getByLabel("账号 ID").fill(fixtures.accountId);
  await page.getByLabel("模型配置 ID").fill(fixtures.modelConfigId);
  await page.getByLabel("生成目标").fill("无资料创意草稿");
  await page.getByRole("button", { name: "生成标题与文案" }).click();
  await expect(
    page.getByText("未提供已确认事实或资料，输出仅可作为创意草稿。"),
  ).toBeVisible();

  const conflictIds = await page.evaluate(async ({ workspaceId }) => {
    const root = "http://127.0.0.1:8100";
    const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
    async function create(value: string) {
      const sourceResponse = await fetch(
        `${root}/v1/workspaces/${workspaceId}/fact-sources`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          body: JSON.stringify({
            kind: "text",
            level: "L2",
            title: `合成冲突价格 ${value}`,
            content: `价格：${value}`,
          }),
        },
      );
      const source = await sourceResponse.json() as {
        items: Array<{ id: string }>;
      };
      await fetch(
        `${root}/v1/workspaces/${workspaceId}/fact-items/${source.items[0].id}/confirm`,
        {
          method: "POST",
          credentials: "include",
          headers: { "X-CSRF-Token": csrf },
        },
      );
      return source.items[0].id;
    }
    return [await create("99 元"), await create("199 元")];
  }, { workspaceId: workspace.workspace_id });

  await page.goto(`/workspaces/${workspace.workspace_id}/generation`);
  await page.getByLabel("沿用已确认历史风格（默认开启）").uncheck();
  await page.getByLabel("账号 ID").fill(fixtures.accountId);
  await page.getByLabel("模型配置 ID").fill(fixtures.modelConfigId);
  await page.getByLabel("生成目标").fill("冲突事实解释");
  await page
    .getByLabel("已确认事实 ID（逗号分隔）")
    .fill(conflictIds.join(","));
  await page.getByRole("button", { name: "生成标题与文案" }).click();
  await expect(
    page.getByText("selected fact is not generation eligible"),
  ).toBeVisible();
});
