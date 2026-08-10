import { chromium, expect, request, test, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";
import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const apiPort = process.env.EXTENSION_E2E_API_PORT;
const webPort = process.env.EXTENSION_E2E_WEB_PORT;
const e2eSecret = process.env.EXTENSION_E2E_SECRET;
if (!apiPort || !webPort || !e2eSecret) throw new Error("extension E2E runtime is not configured");
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const extensionClient = "operations-capture-extension";
const unpacked = resolve(process.cwd(), "../../apps/extension/release/unpacked");

type Session = { workspace_id: string; member_id: string; csrf_token: string };

async function json<T>(response: { ok(): boolean; status(): number; text(): Promise<string>; json(): Promise<unknown> }): Promise<T> {
  expect(response.ok(), await response.text()).toBe(true);
  return response.json() as Promise<T>;
}

async function onboard(admin: APIRequestContext): Promise<Session> {
  return json<Session>(
    await admin.post(`${apiOrigin}/v1/workspaces/onboard`, {
      data: { workspace_name: "扩展 0.2 隔离验收", display_name: "合成管理员" },
    }),
  );
}

async function openPopupPage(
  context: BrowserContext,
  extensionId: string,
): Promise<Page> {
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  await popup.waitForLoadState("domcontentloaded");
  expect(popup.url()).toBe(`chrome-extension://${extensionId}/popup.html`);
  return popup;
}

test("0.2.0 真实扩展链完成配对、安全采集和 Web 人工确认", async ({ browser }) => {
  test.setTimeout(120_000);
  const manifest = JSON.parse(await readFile(join(unpacked, "manifest.json"), "utf8")) as {
    name: string;
    version: string;
  };
  expect(manifest).toMatchObject({ name: "运营数据采集助手", version: "0.2.0" });

  const adminContext = await browser.newContext();
  const editorContext = await browser.newContext();
  const extensionApi = await request.newContext();
  const extensionProfile = await mkdtemp(join(tmpdir(), "operations-ai-extension-e2e-"));
  const testUnpacked = join(extensionProfile, "preauthorized-unpacked");
  await cp(unpacked, testUnpacked, { recursive: true });
  const testManifestPath = join(testUnpacked, "manifest.json");
  const testManifest = JSON.parse(await readFile(testManifestPath, "utf8")) as {
    host_permissions: string[];
  };
  testManifest.host_permissions = [...testManifest.host_permissions, "http://127.0.0.1/*"];
  await writeFile(testManifestPath, JSON.stringify(testManifest, null, 2));
  const extensionContext = await chromium.launchPersistentContext(extensionProfile, {
    channel: "chromium",
    headless: false,
    viewport: { width: 1280, height: 800 },
    args: [`--disable-extensions-except=${testUnpacked}`, `--load-extension=${testUnpacked}`],
  });

  try {
    const admin = adminContext.request;
    const editor = editorContext.request;
    const owner = await onboard(admin);
    const invitation = await json<{ code: string }>(
      await admin.post(`${apiOrigin}/v1/workspaces/${owner.workspace_id}/members/codes`, {
        headers: { "X-CSRF-Token": owner.csrf_token },
        data: { role: "editor" },
      }),
    );
    const editorSession = await json<Session>(
      await editor.post(`${apiOrigin}/v1/sessions/invite`, {
        data: { code: invitation.code, display_name: "合成编辑者" },
      }),
    );
    const account = await json<{ id: string }>(
      await editor.post(`${apiOrigin}/v1/workspaces/${owner.workspace_id}/accounts`, {
        headers: { "X-CSRF-Token": editorSession.csrf_token },
        data: {
          platform: "douyin",
          name: "合成抖音账号",
          objectives: ["reach"],
          metric_weights: { views: 1 },
          benchmark_sample_size: 30,
        },
      }),
    );
    const membersBefore = await json<Array<{ id: string }>>(
      await admin.get(`${apiOrigin}/v1/workspaces/${owner.workspace_id}/members`),
    );
    expect(membersBefore).toHaveLength(2);
    const pairing = await json<{ pairing_code: string }>(
      await admin.post(`${apiOrigin}/v1/workspaces/${owner.workspace_id}/extension-pairing-codes`, {
        headers: { "X-CSRF-Token": owner.csrf_token },
      }),
    );

    let serviceWorker = extensionContext.serviceWorkers()[0];
    if (!serviceWorker) serviceWorker = await extensionContext.waitForEvent("serviceworker");
    const extensionId = new URL(serviceWorker.url()).host;
    expect(extensionId).toBe("mdbmlilohlhmjmcmkpbpjhldganompcl");

    await extensionContext.route("https://creator.douyin.com/**", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `<!doctype html><html><body style="margin:0;background:#f6f7fb">
          <main style="padding:180px 80px"><h1>合成创作者页面</h1>
          <section style="width:760px;height:420px;background:#fff;border:1px solid #ccd3df">仅用于隔离截图验收</section></main>
        </body></html>`,
      });
    });
    const creator = extensionContext.pages()[0] ?? (await extensionContext.newPage());
    await creator.goto("https://creator.douyin.com/creator-micro/content/manage?fixture=extension-0.2");
    await expect.poll(() => creator.locator("html").getAttribute("data-operations-capture-supported")).toBe("true");

    const pairingPopup = await openPopupPage(extensionContext, extensionId);
    const pairStatuses: number[] = [];
    pairingPopup.on("response", (response) => {
      if (response.url().endsWith("/v1/extension/pair")) {
        pairStatuses.push(response.status());
      }
    });
    expect(
      await pairingPopup.evaluate(() => chrome.permissions.contains({ origins: ["http://127.0.0.1/*"] })),
    ).toBe(true);
    expect(
      await pairingPopup.evaluate(async () => {
        await chrome.storage.session.set({ extensionE2eProbe: "ready" });
        const stored = await chrome.storage.session.get("extensionE2eProbe");
        await chrome.storage.session.remove("extensionE2eProbe");
        return stored.extensionE2eProbe;
      }),
    ).toBe("ready");
    expect(
      await pairingPopup.evaluate(async (origin) => {
        try {
          const response = await fetch(`${origin}/healthz`);
          return { ok: response.ok, status: response.status };
        } catch (error) {
          return { error: error instanceof Error ? error.message : "unknown" };
        }
      }, apiOrigin),
    ).toEqual({ ok: true, status: 200 });
    await pairingPopup.getByRole("button", { name: "高级设置" }).click();
    await pairingPopup.locator("#server-origin").fill(apiOrigin);
    await pairingPopup.locator("#pairing-code").fill(pairing.pairing_code);
    await pairingPopup.getByRole("button", { name: "连接工作区" }).click();
    await expect.poll(() => pairStatuses).toEqual([201]);
    await expect(pairingPopup.locator("#destination")).toContainText(
      "扩展 0.2 隔离验收",
      { timeout: 15_000 },
    );
    const persistedConnection = await pairingPopup.evaluate(async () => {
      const local = await chrome.storage.local.get("extensionDeviceRegistration");
      const session = await chrome.storage.session.get("extensionBinding");
      return { local: local.extensionDeviceRegistration, session: session.extensionBinding };
    });
    expect(persistedConnection.local).toMatchObject({
      deviceId: expect.any(String),
      workspaceId: owner.workspace_id,
    });
    expect(JSON.stringify(persistedConnection.local)).not.toContain("accessToken");
    expect(JSON.stringify(persistedConnection.local)).not.toContain("pairingCode");
    expect(persistedConnection.session).toMatchObject({ accessToken: expect.any(String) });

    const membersAfter = await json<Array<{ id: string }>>(
      await admin.get(`${apiOrigin}/v1/workspaces/${owner.workspace_id}/members`),
    );
    expect(membersAfter.map(({ id }) => id)).toEqual(membersBefore.map(({ id }) => id));
    const replay = await extensionApi.post(`${apiOrigin}/v1/extension/pair`, {
      headers: { "X-Extension-Client": extensionClient },
      data: {
        pairing_code: pairing.pairing_code,
        client_id: extensionClient,
        device_id: "00000000-0000-0000-0000-000000000099",
        device_public_key_jwk: { kty: "EC", crv: "P-256", x: "A".repeat(43), y: "A".repeat(43) },
        device_label: "replay device",
        extension_version: "0.2.0",
      },
    });
    expect(replay.status()).toBe(401);
    expect(await replay.json()).toEqual({ detail: "pairing code invalid or expired" });

    await pairingPopup.close();
    await creator.bringToFront();
    const capturePopup = await openPopupPage(extensionContext, extensionId);
    await capturePopup.evaluate(async (creatorUrl) => {
      const [tab] = await chrome.tabs.query({ url: creatorUrl });
      if (tab?.id === undefined) throw new Error("synthetic creator tab unavailable");
      await chrome.tabs.update(tab.id, { active: true });
      location.reload();
    }, creator.url());
    await capturePopup.waitForLoadState("domcontentloaded");
    await expect(capturePopup.locator("#page-status")).toContainText("当前页面已就绪");
    const runtimeStart = await capturePopup.evaluate(async (creatorUrl) => {
      const [tab] = await chrome.tabs.query({ url: creatorUrl });
      if (tab?.id === undefined) throw new Error("synthetic creator tab unavailable");
      const status = await chrome.tabs.sendMessage(tab.id, { type: "GET_PAGE_STATUS" });
      const armed = await chrome.runtime.sendMessage({
        type: "START_SAFE_CAPTURE",
        tabId: tab.id,
        platform: status.platform,
        pageVersion: status.pageVersion,
        pageSignature: status.pageSignature,
      });
      const started = await chrome.tabs.sendMessage(tab.id, { type: "START_SAFE_CAPTURE" });
      return { armed, started };
    }, creator.url());
    expect(runtimeStart).toEqual({ armed: { ok: true }, started: { ok: true } });
    const overlay = creator.locator("[data-operations-capture-overlay]");
    await expect(overlay.getByText("拖动选择要采集的区域")).toBeVisible();
    await overlay.getByRole("button", { name: "取消" }).click();
    await expect(overlay).toHaveCount(0);

    const binding = await serviceWorker.evaluate(async () => {
      const stored = await chrome.storage.session.get("extensionBinding");
      return stored.extensionBinding as { accessToken: string; workspaceId: string };
    });
    expect(binding.workspaceId).toBe(owner.workspace_id);
    const createdTask = await json<{ task_id: string; review_url: string }>(
      await extensionApi.post(
        `${apiOrigin}/v1/extension/workspaces/${owner.workspace_id}/capture-tasks`,
        {
          headers: {
            Authorization: `Bearer ${binding.accessToken}`,
            "Idempotency-Key": `extension-e2e-${process.env.EXTENSION_E2E_RUN_ID}`,
          },
          data: {
            platform: "douyin",
            page_version: "douyin-creator-v1",
            page_identifier: "synthetic-extension-runtime",
            collected_at: new Date().toISOString(),
            screenshot_data_url: "data:image/png;base64,U1lOVEhFVElD",
          },
        },
      ),
    );
    const taskId = createdTask.task_id;
    const reviewUrl = `${process.env.EXTENSION_E2E_WEB_ORIGIN ?? `http://127.0.0.1:${webPort}`}${createdTask.review_url}`;
    expect(createdTask.review_url).toContain(`/workspaces/${owner.workspace_id}/imports`);
    const scopedTask = await json<{ status: string; workspace_id: string }>(
      await extensionApi.get(
        `${apiOrigin}/v1/extension/workspaces/${owner.workspace_id}/capture-tasks/${taskId}`,
        { headers: { Authorization: `Bearer ${binding.accessToken}` } },
      ),
    );
    expect(scopedTask).toMatchObject({ status: "succeeded", workspace_id: owner.workspace_id });
    const stagedBefore = await json<{ present: boolean; prefix_matches: boolean }>(
      await extensionApi.get(`${apiOrigin}/__e2e/capture-object/${owner.workspace_id}/${taskId}`, {
        headers: { "X-E2E-Secret": e2eSecret },
      }),
    );
    expect(stagedBefore).toEqual({ present: true, prefix_matches: true });

    const denied = await extensionApi.post(`${apiOrigin}/v1/extension/capture-tasks/${taskId}/confirm`, {
      headers: { Authorization: `Bearer ${binding.accessToken}` },
    });
    expect(denied.status()).toBe(403);

    const editorPage = await editorContext.newPage();
    const editorReviewUrl = new URL(reviewUrl);
    editorReviewUrl.searchParams.set("platform", "douyin");
    editorReviewUrl.searchParams.set("account", account.id);
    await editorPage.goto(editorReviewUrl.toString());
    await editorPage.evaluate((csrf) => sessionStorage.setItem("workspace_csrf", csrf), editorSession.csrf_token);
    await editorPage.reload();
    await expect(editorPage.getByText("扩展识别结果待确认")).toBeVisible();
    await editorPage.getByRole("button", { name: "人工确认并写入快照" }).click();
    await expect(editorPage.getByText("已写入 1 条正式快照。")).toBeVisible();
    const stagedAfter = await json<{ present: boolean; prefix_matches: boolean }>(
      await extensionApi.get(`${apiOrigin}/__e2e/capture-object/${owner.workspace_id}/${taskId}`, {
        headers: { "X-E2E-Secret": e2eSecret },
      }),
    );
    expect(stagedAfter).toEqual({ present: false, prefix_matches: true });
  } finally {
    await extensionContext.close();
    await extensionApi.dispose();
    await adminContext.close();
    await editorContext.close();
    await rm(extensionProfile, { recursive: true, force: true });
  }
});
