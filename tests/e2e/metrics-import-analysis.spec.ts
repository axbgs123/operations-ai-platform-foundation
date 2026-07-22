import path from "node:path";

import { expect, test } from "@playwright/test";


const fixture = path.resolve(
  process.cwd(),
  "../../apps/api/tests/fixtures/imports/douyin_mixed.csv",
);

test("CSV upload stays staged until a valid row is selected and confirmed", async ({
  page,
  request,
}) => {
  const workspaceResponse = await request.post(
    "http://127.0.0.1:8100/v1/workspaces",
    { data: { name: `导入 E2E ${Date.now()}` } },
  );
  const workspace = (await workspaceResponse.json()) as {
    workspace_id: string;
    admin_code: string;
  };

  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(workspace.admin_code);
  await page.getByLabel("显示名称").fill("导入管理员");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page).toHaveURL(
    `/workspaces/${workspace.workspace_id}/settings/members`,
  );

  const account = (await page.evaluate(async (workspaceId) => {
    const response = await fetch(
      `http://127.0.0.1:8100/v1/workspaces/${workspaceId}/accounts`,
      {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": sessionStorage.getItem("workspace_csrf") ?? "",
        },
        body: JSON.stringify({
          platform: "douyin",
          name: "E2E 合成导入账号",
          objectives: ["reach"],
          metric_weights: { views: 1 },
          benchmark_sample_size: 30,
        }),
      },
    );
    return response.json();
  }, workspace.workspace_id)) as { id: string };

  await page.goto(
    `/workspaces/${workspace.workspace_id}/imports?accountId=${account.id}&platform=douyin`,
  );
  await page.getByLabel("CSV 或 Excel 文件").setInputFiles(fixture);
  await page.getByRole("button", { name: "生成暂存预览" }).click();

  await expect(page.getByText("新增 2")).toBeVisible();
  await expect(page.getByText("失败 1")).toBeVisible();
  await expect(page.getByText("title is required")).toBeVisible();

  const beforeConfirm = await page.evaluate(async (workspaceId) => {
    const response = await fetch(
      `http://127.0.0.1:8100/v1/contents?workspace_id=${workspaceId}`,
      { credentials: "include" },
    );
    return response.json();
  }, workspace.workspace_id);
  expect(beforeConfirm).toEqual([]);

  await page.getByLabel("选择第 2 行").check();
  await page.getByRole("button", { name: "人工确认并写入正式数据" }).click();
  await expect(page.getByText("已写入 1 条内容和 1 条指标快照")).toBeVisible();

  const afterConfirm = (await page.evaluate(async (workspaceId) => {
    const response = await fetch(
      `http://127.0.0.1:8100/v1/contents?workspace_id=${workspaceId}`,
      { credentials: "include" },
    );
    return response.json();
  }, workspace.workspace_id)) as Array<{ title: string }>;
  expect(afterConfirm).toHaveLength(1);
  expect(afterConfirm[0].title).toBe("合成样本一");
});

test("Douyin and Xiaohongshu keep dashboard metrics, benchmarks, and reports isolated", async ({
  page,
  request,
}) => {
  const workspaceResponse = await request.post(
    "http://127.0.0.1:8100/v1/workspaces",
    { data: { name: `双平台隔离 E2E ${Date.now()}` } },
  );
  const workspace = (await workspaceResponse.json()) as {
    workspace_id: string;
    admin_code: string;
  };

  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(workspace.admin_code);
  await page.getByLabel("显示名称").fill("隔离验收管理员");
  await page.getByRole("button", { name: "进入工作区" }).click();
  await expect(page).toHaveURL(
    `/workspaces/${workspace.workspace_id}/settings/members`,
  );

  const result = await page.evaluate(async (workspaceId) => {
    const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
    const api = async (
      path: string,
      init: RequestInit = {},
    ): Promise<Record<string, unknown>> => {
      const response = await fetch(`http://127.0.0.1:8100${path}`, {
        ...init,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
          ...init.headers,
        },
      });
      if (!response.ok) {
        throw new Error(`${response.status} ${await response.text()}`);
      }
      return response.json();
    };

    const setupPlatform = async (
      platform: "douyin" | "xiaohongshu",
      metricKey: "completion_rate" | "cover_click_rate",
      metricValue: number,
    ) => {
      const account = await api(`/v1/workspaces/${workspaceId}/accounts`, {
        method: "POST",
        body: JSON.stringify({
          platform,
          name: `${platform} 合成隔离账号`,
          objectives: ["reach"],
          metric_weights: { [metricKey]: 1 },
          benchmark_sample_size: 30,
        }),
      });
      const content = await api("/v1/contents", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId,
          account_id: account.id,
          platform,
          content_type: "video",
          title: `${platform} 合成验收内容`,
          body: "仅使用合成数据验证平台隔离。",
        }),
      });
      const published = await api(`/v1/contents/${content.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "published" }),
      });
      const collectedAt = new Date(
        new Date(published.published_at as string).getTime() + 60 * 60 * 1000,
      ).toISOString();
      const snapshot = await api(`/v1/contents/${content.id}/snapshots`, {
        method: "POST",
        body: JSON.stringify({
          collected_at: collectedAt,
          source: "manual",
          metrics: [{ key: metricKey, raw_value: metricValue }],
        }),
      });
      await api(`/v1/contents/${content.id}/snapshots/${snapshot.id}/confirm`, {
        method: "POST",
      });
      return {
        accountId: account.id,
        contentId: content.id,
        snapshotId: snapshot.id,
        metricKey,
      };
    };

    const readPlatform = async (setup: {
      accountId: unknown;
      contentId: unknown;
      snapshotId: unknown;
      metricKey: string;
    }) => {
      let run = await api(`/v1/contents/${setup.contentId}/analysis-runs`, {
        method: "POST",
      });
      for (let attempt = 0; attempt < 30 && run.status !== "succeeded"; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        run = await api(
          `/v1/contents/${setup.contentId}/analysis-runs/${run.id}`,
        );
      }
      const dashboard = await api(
        `/v1/workspaces/${workspaceId}/accounts/${setup.accountId}/dashboard?content_type=video&maturity_bucket=1h`,
      );
      return {
        accountId: setup.accountId,
        snapshotId: setup.snapshotId,
        benchmarkRunId: run.benchmark_run_id,
        runSnapshotIds: run.snapshot_ids,
        status: run.status,
        report: JSON.stringify(run.report),
        sampleCount: dashboard.sample_count,
        metricKeys: (dashboard.goal_cards as Array<{ metric_key: string }>).map(
          (card) => card.metric_key,
        ),
      };
    };

    const douyinSetup = await setupPlatform("douyin", "completion_rate", 0.82);
    const xiaohongshuSetup = await setupPlatform(
      "xiaohongshu",
      "cover_click_rate",
      0.37,
    );
    const douyin = await readPlatform(douyinSetup);
    const xiaohongshu = await readPlatform(xiaohongshuSetup);
    return {
      douyin,
      xiaohongshu,
      douyinAfterSwitchBack: await readPlatform(douyinSetup),
    };
  }, workspace.workspace_id);

  expect(result.douyin.status).toBe("succeeded");
  expect(result.xiaohongshu.status).toBe("succeeded");
  expect(result.douyin.accountId).not.toBe(result.xiaohongshu.accountId);
  expect(result.douyin.benchmarkRunId).not.toBe(
    result.xiaohongshu.benchmarkRunId,
  );
  expect(result.douyin.sampleCount).toBe(1);
  expect(result.xiaohongshu.sampleCount).toBe(1);
  expect(result.douyin.runSnapshotIds).toEqual([result.douyin.snapshotId]);
  expect(result.xiaohongshu.runSnapshotIds).toEqual([
    result.xiaohongshu.snapshotId,
  ]);
  expect(result.douyin.metricKeys).toContain("completion_rate");
  expect(result.douyin.metricKeys).not.toContain("cover_click_rate");
  expect(result.xiaohongshu.metricKeys).toContain("cover_click_rate");
  expect(result.xiaohongshu.metricKeys).not.toContain("completion_rate");
  expect(result.douyin.report).toContain("metric:completion_rate");
  expect(result.douyin.report).not.toContain("metric:cover_click_rate");
  expect(result.xiaohongshu.report).toContain("metric:cover_click_rate");
  expect(result.xiaohongshu.report).not.toContain("metric:completion_rate");
  expect(result.douyinAfterSwitchBack).toEqual(result.douyin);
});
