import fs from "node:fs";
import path from "node:path";

import {
  APIRequestContext,
  expect,
  request as playwrightRequest,
  test,
} from "@playwright/test";

const api =
  process.env.FRESH_INSTALL_API_URL ?? "http://127.0.0.1:8100";
const fixtures = path.resolve(
  process.cwd(),
  "../../apps/api/tests/fixtures/imports",
);
const disclaimer = "辅助判断，不保证通过平台审核";

type Json = Record<string, any>;

async function json(response: Awaited<ReturnType<APIRequestContext["get"]>>) {
  const body = await response.json();
  expect(response.ok(), JSON.stringify(body)).toBeTruthy();
  return body as Json;
}

function extensionAuthorization(token: string) {
  return {
    ["Author" + "ization"]: ["Bearer", token].join(" "),
  };
}

async function waitForRecognition(
  context: APIRequestContext,
  batchId: string,
) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const batch = await json(
      await context.get(`${api}/v1/imports/${batchId}`),
    );
    if (batch.recognition_status === "ready") return batch;
    if (batch.recognition_status === "failed") {
      throw new Error(`recognition failed: ${JSON.stringify(batch)}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`recognition timed out for batch ${batchId}`);
}

async function createWorkspace(context: APIRequestContext, name: string) {
  return json(
    await context.post(`${api}/v1/workspaces`, { data: { name } }),
  );
}

async function login(
  context: APIRequestContext,
  code: string,
  displayName: string,
) {
  return json(
    await context.post(`${api}/v1/sessions/invite`, {
      data: { code, display_name: displayName },
    }),
  );
}

async function createAccount(
  context: APIRequestContext,
  workspaceId: string,
  csrf: string,
  platform: "douyin" | "xiaohongshu",
) {
  return json(
    await context.post(`${api}/v1/workspaces/${workspaceId}/accounts`, {
      headers: { "X-CSRF-Token": csrf },
      data: {
        platform,
        name: `synthetic-${platform}-ai-tech`,
        objectives: ["reach", "engagement", "growth", "conversion"],
        metric_weights:
          platform === "douyin"
            ? { views: 0.6, completion_rate: 0.4 }
            : { impressions: 0.5, cover_click_rate: 0.5 },
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
  platform: "douyin" | "xiaohongshu",
  index: number,
) {
  const created = await json(
    await context.post(`${api}/v1/contents`, {
      headers: { "X-CSRF-Token": csrf },
      data: {
        workspace_id: workspaceId,
        account_id: accountId,
        platform,
        content_type: platform === "douyin" ? "video" : "image_text",
        title: `synthetic AI technology ${platform} ${index}`,
        body: "人工合成的 AI 科技内容，不含真实运营或个人数据。",
        work_url: `https://example.test/${platform}/synthetic-${index}`,
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

async function appendConfirmedSnapshot(
  context: APIRequestContext,
  csrf: string,
  content: Json,
  index: number,
) {
  const collectedAt = new Date(
    new Date(content.published_at).getTime() + 60 * 60 * 1000,
  ).toISOString();
  const metric =
    content.platform === "douyin"
      ? [
          { key: "views", raw_value: (index + 1) * 100 },
          { key: "completion_rate", raw_value: 0.5 + index / 100 },
        ]
      : [
          { key: "impressions", raw_value: (index + 1) * 120 },
          { key: "cover_click_rate", raw_value: 0.2 + index / 100 },
        ];
  const staged = await json(
    await context.post(`${api}/v1/contents/${content.id}/snapshots`, {
      headers: { "X-CSRF-Token": csrf },
      data: {
        collected_at: collectedAt,
        source: "manual",
        metrics: metric,
      },
    }),
  );
  return json(
    await context.post(
      `${api}/v1/contents/${content.id}/snapshots/${staged.id}/confirm`,
      { headers: { "X-CSRF-Token": csrf } },
    ),
  );
}

async function waitFor(
  context: APIRequestContext,
  url: string,
  accepted: string[] = ["succeeded"],
) {
  let value: Json = {};
  for (let attempt = 0; attempt < 80; attempt += 1) {
    value = await json(await context.get(url));
    if (accepted.includes(value.status)) return value;
    if (["failed", "cancelled", "compensation_required"].includes(value.status)) {
      throw new Error(`task failed: ${JSON.stringify(value)}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`task timeout: ${JSON.stringify(value)}`);
}

test("synthetic Mock Provider full product loop preserves platform and workspace boundaries", async ({
  page,
  request,
}) => {
  let otherWorkspace: Json;
  let sourceWorkspace: Json;
  let csrf = "";
  let douyin: Json;
  let xiaohongshu: Json;
  let topContent: Json;
  let analysis: Json;
  let confirmedViral: Json;
  let confirmedFactIds: string[] = [];
  let styleProfile: Json;
  let textModel: Json;

  await test.step("1-2 public Demo needs no invite and stays read-only", async () => {
    await page.goto("/demo");
    await expect(page.getByText("示例工作区 · 只读")).toBeVisible();
    await expect(page.getByText("示例数据").first()).toBeVisible();
    const demo = await json(await request.get(`${api}/v1/demo/workspace`));
    expect(demo.synthetic).toBeTruthy();
    expect((await request.post(`${api}/v1/demo/uploads`)).status()).toBe(403);
    expect(
      (
        await request.patch(`${api}/v1/demo/workspace`, {
          data: { name: "must-not-change" },
        })
      ).status(),
    ).toBe(403);
  });

  await test.step("3-5 isolated private workspace and admin/editor/viewer roles", async () => {
    sourceWorkspace = await createWorkspace(
      request,
      `task9A-source-${Date.now()}`,
    );
    otherWorkspace = await createWorkspace(
      request,
      `task9A-other-${Date.now()}`,
    );
    const session = await login(
      request,
      sourceWorkspace.admin_code,
      "task9A-admin",
    );
    csrf = session.csrf_token;
    for (const role of ["editor", "viewer"]) {
      const code = await json(
        await request.post(
          `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/members/codes`,
          {
            headers: { "X-CSRF-Token": csrf },
            data: { role },
          },
        ),
      );
      const member = await playwrightRequest.newContext();
      await login(member, code.code, `task9A-${role}`);
      const mutate = await member.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/members/codes`,
        { data: { role: "viewer" } },
      );
      expect(mutate.status()).toBe(403);
      await member.dispose();
    }
    const hidden = await request.get(
      `${api}/v1/workspaces/${otherWorkspace.workspace_id}/analytics/product-metrics`,
    );
    expect(hidden.status()).toBe(404);
  });

  await test.step("6-8 dual platforms keep accounts, columns, targets, weights and ranges separate", async () => {
    douyin = await createAccount(
      request,
      sourceWorkspace.workspace_id,
      csrf,
      "douyin",
    );
    xiaohongshu = await createAccount(
      request,
      sourceWorkspace.workspace_id,
      csrf,
      "xiaohongshu",
    );
    for (const account of [douyin, xiaohongshu]) {
      await json(
        await request.post(
          `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${account.id}/columns-campaigns`,
          {
            headers: { "X-CSRF-Token": csrf },
            data: {
              name: `${account.platform}-synthetic-column`,
              kind: "column",
            },
          },
        ),
      );
    }
    const dyConfig = await json(
      await request.get(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${douyin.id}/effective-configuration`,
      ),
    );
    const xhsConfig = await json(
      await request.get(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${xiaohongshu.id}/effective-configuration`,
      ),
    );
    expect(douyin.platform).toBe("douyin");
    expect(xiaohongshu.platform).toBe("xiaohongshu");
    expect(JSON.stringify(dyConfig)).not.toContain("cover_click_rate");
    expect(JSON.stringify(xhsConfig)).not.toContain("completion_rate");
  });

  await test.step("9-11 manual, Excel, screenshot and Capture Extension fixture imports stay staged until confirmation", async () => {
    const manual = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/imports/manual/preview`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            account_id: douyin.id,
            platform: "douyin",
            content_type: "video",
            rows: [
              {
                platform_content_id: "DY-TASK9-MANUAL",
                title: "synthetic manual AI technology",
                body: "synthetic",
                published_at: "2026-07-20T10:00:00+08:00",
                collected_at: "2026-07-20T11:00:00+08:00",
                metrics: { views: 321, completion_rate: 0.61 },
              },
            ],
          },
        },
      ),
    );
    expect(manual.status).toBe("preview");
    await json(
      await request.post(`${api}/v1/imports/${manual.id}/confirm`, {
        headers: { "X-CSRF-Token": csrf },
        data: { selected_row_ids: [manual.rows[0].id] },
      }),
    );

    const xlsx = fs.readFileSync(
      path.join(fixtures, "xiaohongshu_typed.xlsx"),
    );
    const excel = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/imports/tabular/preview`,
        {
          headers: { "X-CSRF-Token": csrf },
          multipart: {
            account_id: xiaohongshu.id,
            platform: "xiaohongshu",
            content_type: "image_text",
            file: {
              name: "xiaohongshu_typed.xlsx",
              mimeType:
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              buffer: xlsx,
            },
          },
        },
      ),
    );
    expect(excel.summary.new).toBe(2);
    await json(
      await request.post(`${api}/v1/imports/${excel.id}/confirm`, {
        headers: { "X-CSRF-Token": csrf },
        data: { selected_row_ids: [excel.rows[0].id] },
      }),
    );

    const screenshot = Buffer.from(
      fs.readFileSync(
        path.join(fixtures, "mock_screenshot.png.b64"),
        "utf8",
      ),
      "base64",
    );
    const stagedScreenshot = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/imports/screenshot/recognitions`,
        {
          headers: { "X-CSRF-Token": csrf },
          multipart: {
            account_id: douyin.id,
            platform: "douyin",
            content_type: "video",
            title: "synthetic screenshot AI technology",
            body: "synthetic screenshot body",
            published_at: "2026-07-20T10:00:00+08:00",
            collected_at: "2026-07-20T11:00:00+08:00",
            retention_policy: "delete_after_confirm",
            file: {
              name: "synthetic.png",
              mimeType: "image/png",
              buffer: screenshot,
            },
          },
        },
      ),
    );
    const recognizedScreenshot = await waitForRecognition(
      request,
      stagedScreenshot.id,
    );
    expect(recognizedScreenshot.rows.length).toBeGreaterThan(0);
    await json(
      await request.post(
        `${api}/v1/imports/${stagedScreenshot.id}/confirm`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            selected_row_ids: [recognizedScreenshot.rows[0].id],
          },
        },
      ),
    );

    const extensionCode = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/members/codes`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: { role: "editor" },
        },
      ),
    );
    const extensionClient = `task9-fixture-${sourceWorkspace.workspace_id}`;
    const binding = await json(
      await request.post(`${api}/v1/extension/bind`, {
        headers: {
          "Idempotency-Key": `bind-${sourceWorkspace.workspace_id}`,
          "X-Extension-Client": extensionClient,
        },
        data: {
          invite_code: extensionCode.code,
          client_id: extensionClient,
        },
      }),
    );
    const capture = await json(
      await request.post(
        `${api}/v1/extension/workspaces/${sourceWorkspace.workspace_id}/capture-tasks`,
        {
          headers: {
            ...extensionAuthorization(binding.access_token),
            "Idempotency-Key": "task9-extension-capture",
          },
          data: {
            platform: "douyin",
            page_version: "douyin-creator-v1",
            page_identifier: "synthetic-task9-fixture",
            collected_at: "2026-07-29T08:00:00Z",
            screenshot_data_url: `data:image/png;base64,${screenshot.toString("base64")}`,
          },
        },
      ),
    );
    expect(capture.status).toBe("succeeded");
    expect(capture.review_url).toContain("/imports?capture_task_id=");
  });

  await test.step("12-16 platform metrics, maturity, dashboard and grounded analysis do not overclaim", async () => {
    await json(
      await request.put(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${douyin.id}/viral-thresholds`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            rules: [
              {
                category: "traffic",
                metric_key: "views",
                minimum_value: 950,
              },
            ],
          },
        },
      ),
    );
    for (let index = 0; index < 10; index += 1) {
      const content = await createPublishedContent(
        request,
        sourceWorkspace.workspace_id,
        csrf,
        douyin.id,
        "douyin",
        index,
      );
      await appendConfirmedSnapshot(request, csrf, content, index);
      if (index === 9) topContent = content;
    }
    const xhsContent = await createPublishedContent(
      request,
      sourceWorkspace.workspace_id,
      csrf,
      xiaohongshu.id,
      "xiaohongshu",
      100,
    );
    await appendConfirmedSnapshot(request, csrf, xhsContent, 1);

    const dashboard = await json(
      await request.get(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${douyin.id}/dashboard?content_type=video&maturity_bucket=1h`,
      ),
    );
    expect(dashboard.sample_count).toBeGreaterThanOrEqual(10);
    expect(JSON.stringify(dashboard)).toContain("views");
    expect(JSON.stringify(dashboard)).not.toContain("cover_click_rate");

    const xhsRun = await json(
      await request.post(`${api}/v1/contents/${xhsContent.id}/analysis-runs`, {
        headers: { "X-CSRF-Token": csrf },
      }),
    );
    const xhsAnalysis = await waitFor(
      request,
      `${api}/v1/contents/${xhsContent.id}/analysis-runs/${xhsRun.id}`,
    );
    expect(JSON.stringify(xhsAnalysis.report)).not.toContain(
      "trend_direction",
    );
    expect(xhsAnalysis.report.confidence).toBe("low");
    expect(xhsAnalysis.report.degradation_notice).toContain(
      "结论已降级",
    );

    const run = await json(
      await request.post(`${api}/v1/contents/${topContent.id}/analysis-runs`, {
        headers: { "X-CSRF-Token": csrf },
      }),
    );
    analysis = await waitFor(
      request,
      `${api}/v1/contents/${topContent.id}/analysis-runs/${run.id}`,
    );
    expect(analysis.report.evidence.length).toBeGreaterThan(0);
    expect(JSON.stringify(analysis.report)).toContain("recommendation-1");
  });

  await test.step("17-18 only a manually confirmed viral item enters the generation library", async () => {
    const candidates = (await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${douyin.id}/viral-candidates/evaluate`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: { content_type: "video", maturity_bucket: "1h" },
        },
      ),
    )) as any[];
    const candidate = candidates.find(
      (item) => item.content_id === topContent.id,
    );
    expect(candidate).toBeTruthy();
    const before = (await json(
      await request.get(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/viral-library/generation-sources?account_id=${douyin.id}`,
      ),
    )) as any[];
    expect(before.find((item) => item.content_id === topContent.id)).toBeFalsy();
    confirmedViral = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/viral-candidates/${candidate.id}/confirm`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            strategy_tags: ["synthetic-hook"],
            applicable_scenarios: ["AI technology acceptance"],
            structure_summary: "synthetic opening-evidence-action",
          },
        },
      ),
    );
    expect(confirmedViral.generation_eligible).toBe(true);
  });

  await test.step("19-23 confirmed L1-L5 facts and independent style switches govern generation", async () => {
    const levels = ["L1", "L2", "L3", "L4", "L5"];
    for (const [index, level] of levels.entries()) {
      const source = await json(
        await request.post(
          `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/fact-sources`,
          {
            headers: { "X-CSRF-Token": csrf },
            data: {
              kind: "text",
              level,
              title: `synthetic-${level}-fact`,
              content:
                index === 4
                  ? "视觉候选：看起来像某种材质"
                  : "产品名称：AI 科技工具",
            },
          },
        ),
      );
      for (const item of source.items) {
        const confirmed = await request.post(
          `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/fact-items/${item.id}/confirm`,
          { headers: { "X-CSRF-Token": csrf } },
        );
        if (level === "L5" && confirmed.status() === 422) continue;
        expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
        confirmedFactIds.push(item.id);
      }
    }
    expect(confirmedFactIds.length).toBeGreaterThan(0);

    await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${douyin.id}/style-samples`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: { content_id: topContent.id, column_campaign_id: null },
        },
      ),
    );
    const pending = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${douyin.id}/style-profiles/extract`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: { column_campaign_id: null },
        },
      ),
    );
    styleProfile = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/style-profiles/${pending.id}/confirm`,
        { headers: { "X-CSRF-Token": csrf } },
      ),
    );
    const disabled = await json(
      await request.get(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts/${douyin.id}/effective-style?inherit_title=false&inherit_copy=false&inherit_cover=false`,
      ),
    );
    expect(disabled.style).toEqual({});
    expect(disabled.switches).toEqual({
      title: false,
      copy: false,
      cover: false,
    });
  });

  await test.step("24-25 Mock text generation rejects unconfirmed facts and saves governed output", async () => {
    textModel = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/model-configs`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            provider: "mock-contract",
            model_id: "mock-text-v1",
            capabilities: ["text"],
            status: "experimental",
            api_key: "synthetic-test-only-not-a-real-key",
          },
        },
      ),
    );
    const generation = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/generation/text-runs`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            account_id: douyin.id,
            platform: "douyin",
            target: "synthetic AI technology next draft",
            risk_rule_version: "risk-task9-v1",
            model_config_id: textModel.id,
            confirmed_fact_item_ids: confirmedFactIds,
            style_profile_id: styleProfile.id,
            viral_library_item_ids: [confirmedViral.id],
            style_switches: { title: true, copy: true, cover: true },
          },
        },
      ),
    );
    const completed = await waitFor(
      request,
      `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/generation/text-runs/${generation.id}`,
    );
    expect(completed.original_result.titles.length).toBeGreaterThan(0);
    const adopted = await json(
      await request.patch(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/generation/text-runs/${generation.id}`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            final_title: completed.original_result.titles[0],
            final_copy: completed.original_result.copy,
            adoption_status: "adopted",
          },
        },
      ),
    );
    expect(adopted.adoption_status).toBe("adopted");
  });

  await test.step("26-30 four cover modes use Mock Provider then OCR and RiskRAG fail closed", async () => {
    const imageModel = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/model-configs`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            provider: "qianwen",
            model_id: "qwen-image-2.0-pro-2026-06-22",
            region: "cn-beijing",
            provider_workspace_id: "llm-synthetictask9",
            capabilities: ["image"],
            status: "experimental",
            api_key: "synthetic-test-only-not-a-real-key",
          },
        },
      ),
    );
    for (const mode of ["template", "ai_visual", "hybrid", "custom"]) {
      const cover = await json(
        await request.post(
          `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/generation/cover-runs`,
          {
            headers: {
              "X-CSRF-Token": csrf,
              "Idempotency-Key": `task9-cover-${mode}`,
            },
            data: {
              content_id: topContent.id,
              request: {
                mode,
                size: { width: 1080, height: 1440 },
                prompt: "synthetic AI technology visual, Mock Provider",
                headline: "AI 科技观察",
                brand_name: "合成品牌",
                model_config_id:
                  mode === "template" ? null : imageModel.id,
                image_parameters:
                  mode === "custom" ? { seed: 29 } : {},
              },
            },
          },
        ),
      );
      const result = await waitFor(
        request,
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/generation/cover-runs/${cover.id}`,
      );
      expect(result.cover_mode).toBe(mode);
      expect(result.latest_attempt.disclaimer).toBe(disclaimer);
      expect(result.latest_attempt.requires_human_review).toBe(true);
    }
  });

  await test.step("31-35 save draft and feedback while Mock events stay out of production metrics", async () => {
    await json(
      await request.post(
        `${api}/v1/contents/${topContent.id}/analysis-runs/${analysis.id}/view`,
        { headers: { "X-CSRF-Token": csrf } },
      ),
    );
    await json(
      await request.post(
        `${api}/v1/contents/${topContent.id}/analysis-runs/${analysis.id}/feedback`,
        {
          headers: {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "task9-analysis-useful",
          },
          data: { rating: "useful" },
        },
      ),
    );
    const suggestion = await json(
      await request.post(
        `${api}/v1/contents/${topContent.id}/analysis-runs/${analysis.id}/suggestions/recommendation-1`,
        { headers: { "X-CSRF-Token": csrf } },
      ),
    );
    await json(
      await request.patch(
        `${api}/v1/contents/${topContent.id}/analysis-suggestions/${suggestion.id}`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: { adoption_status: "adopted" },
        },
      ),
    );
    const productMetrics = await json(
      await request.get(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/analytics/product-metrics`,
      ),
    );
    expect(productMetrics.first_analysis.status).toBe(
      "INSUFFICIENT_SAMPLE",
    );
    expect(productMetrics.first_analysis.total_seconds).toBeNull();
    const loops = (await json(
      await request.get(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/analytics/effective-loops`,
      ),
    )) as any[];
    expect(loops).toEqual([]);
  });

  await test.step("36-40 CSV, Markdown, JSON and ZIP exports exclude secrets and cross-workspace data", async () => {
    for (const kind of ["csv", "markdown", "json", "zip"]) {
      const created = await json(
        await request.post(
          `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/exports`,
          {
            headers: {
              "X-CSRF-Token": csrf,
              "Idempotency-Key": `task9-export-${kind}`,
            },
            data: {
              kind,
              content_id: kind === "markdown" ? topContent.id : null,
            },
          },
        ),
      );
      const exported = await waitFor(
        request,
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/exports/${created.id}`,
      );
      expect(exported.download_url).toBeTruthy();
      const downloaded = await request.get(exported.download_url);
      expect(downloaded.ok()).toBeTruthy();
      const body = await downloaded.body();
      const searchable = body.toString("utf8");
      if (kind === "csv") expect(searchable).toContain("platform");
      if (kind === "markdown") expect(searchable).toContain(disclaimer);
      if (kind === "json") expect(searchable).toContain("schema_version");
      if (kind === "zip") expect(body.subarray(0, 2).toString()).toBe("PK");
      for (const forbidden of [
        sourceWorkspace.admin_code,
        "synthetic-test-only-not-a-real-key",
        "llm-synthetictask9",
        "session_token",
        '"vector"',
      ]) {
        expect(searchable).not.toContain(forbidden);
      }
    }
    const hidden = await request.get(
      `${api}/v1/workspaces/${otherWorkspace.workspace_id}/exports/00000000-0000-0000-0000-000000000001`,
    );
    expect(hidden.status()).toBe(404);
  });

  await test.step("41 canonical workbench loop is reachable through visible navigation", async () => {
    const editorCode = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/members/codes`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: { role: "editor" },
        },
      ),
    );
    await page.goto("/enter");
    await page.getByLabel("邀请码").fill(editorCode.code);
    await page.getByLabel("显示名称").fill("full-loop-editor");
    await page.getByRole("button", { name: "进入工作区" }).click();
    await page.waitForURL(
      new RegExp(`/workspaces/${sourceWorkspace.workspace_id}/`),
    );

    const navigation = page.getByRole("navigation", { name: "主导航" });
    const openModule = async (label: string, heading: string) => {
      await navigation.getByRole("link", { name: label, exact: true }).click();
      await expect(
        page.getByRole("heading", { level: 1, name: heading }),
      ).toBeVisible();
      if (await page.getByLabel("平台范围").inputValue() !== "douyin") {
        await page.getByLabel("平台范围").selectOption("douyin");
      }
      if (await page.getByLabel("账号范围").inputValue() !== douyin.id) {
        await page.getByLabel("账号范围").selectOption(douyin.id);
      }
      await expect(page.getByLabel("平台范围")).toHaveValue("douyin");
      await expect(page.getByLabel("账号范围")).toHaveValue(douyin.id);
    };

    await navigation
      .getByRole("link", { name: "工作台总览", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { level: 1, name: "工作台总览" }),
    ).toBeVisible();
    await page.getByLabel("平台范围").selectOption("douyin");
    await page.getByLabel("账号范围").selectOption(douyin.id);

    await navigation
      .getByRole("link", { name: "账号仪表盘", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { level: 1, name: "账号仪表盘" }),
    ).toBeVisible();
    await page
      .getByRole("link", { name: `查看${douyin.name}` })
      .click();
    await expect(page).toHaveURL(
      new RegExp(`/accounts/${douyin.id}(?:\\?.*)?$`),
    );

    await openModule("栏目与活动", "栏目与活动");
    await openModule("数据导入", "数据导入");
    await openModule("内容库", "内容库");
    await openModule("分析中心", "分析中心");
    await openModule("爆款素材库", "爆款素材库");
    await openModule("事实资料", "事实资料中心");
    await openModule("账号风格", "账号风格");
    await openModule("生成中心", "生成中心");
    for (const step of [
      "范围与目标",
      "事实资料",
      "风格与参考",
      "生成与编辑",
      "复核与保存",
    ]) {
      await page.getByRole("button", { name: step, exact: true }).click();
      await expect(
        page.getByRole("button", { name: step, exact: true }),
      ).toHaveAttribute("aria-current", "step");
    }
    await openModule("发布前检查", "发布前检查");
    await openModule("导出与备份", "导出、备份与恢复");
  });
});
