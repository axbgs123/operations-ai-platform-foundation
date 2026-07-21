import { expect, test } from "@playwright/test";


async function enterWithCode(
  page: import("@playwright/test").Page,
  code: string,
  displayName: string,
) {
  await page.goto("/enter");
  await page.getByLabel("邀请码").fill(code);
  await page.getByLabel("显示名称").fill(displayName);
  await page.getByRole("button", { name: "进入工作区" }).click();
}


test("admin issues independent codes while editor and viewer are denied", async ({
  browser,
  page,
  request,
}) => {
  const workspaceResponse = await request.post(
    "http://127.0.0.1:8100/v1/workspaces",
    { data: { name: `E2E 工作区 ${Date.now()}` } },
  );
  expect(workspaceResponse.status()).toBe(201);
  const workspace = (await workspaceResponse.json()) as {
    workspace_id: string;
    admin_code: string;
  };

  await enterWithCode(page, workspace.admin_code, "E2E 管理员");
  await expect(page).toHaveURL(
    `/workspaces/${workspace.workspace_id}/settings/members`,
  );

  await page.getByLabel("成员角色").selectOption("viewer");
  await page.getByRole("button", { name: "生成独立邀请码" }).click();
  const viewerCode = await page.locator("output").textContent();
  expect(viewerCode).toContain(".");

  await page.getByLabel("成员角色").selectOption("editor");
  await page.getByRole("button", { name: "生成独立邀请码" }).click();
  const editorCode = await page.locator("output").textContent();
  expect(editorCode).toContain(".");

  for (const [role, code] of [
    ["查看者", viewerCode],
    ["编辑者", editorCode],
  ] as const) {
    const context = await browser.newContext();
    const memberPage = await context.newPage();
    await enterWithCode(memberPage, code ?? "", `E2E ${role}`);
    await expect(memberPage).toHaveURL(
      `/workspaces/${workspace.workspace_id}/settings/members`,
    );
    await memberPage.getByRole("button", { name: "生成独立邀请码" }).click();
    await expect(memberPage.getByText("permission denied")).toBeVisible();
    await context.close();
  }
});
