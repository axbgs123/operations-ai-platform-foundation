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
