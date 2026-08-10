import { chromium, expect, request, test, type APIRequestContext, type BrowserContext, type Page } from "@playwright/test";
import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const apiPort = process.env.EXTENSION_E2E_API_PORT;
const webPort = process.env.EXTENSION_E2E_WEB_PORT;
const cdpPort = process.env.EXTENSION_E2E_CDP_PORT;
const e2eSecret = process.env.EXTENSION_E2E_SECRET;
if (!apiPort || !webPort || !cdpPort || !e2eSecret) throw new Error("extension E2E runtime is not configured");
const apiOrigin = `http://127.0.0.1:${apiPort}`;
const extensionClient = "operations-capture-extension";
// Global setup builds current HEAD; each test copies this dist into an isolated temporary profile.
const unpacked = resolve(import.meta.dirname, "../../apps/extension/dist");
const longCreatorFixture = resolve(import.meta.dirname, "fixtures/long-creator-page.html");

type Session = { workspace_id: string; member_id: string; csrf_token: string };

async function json<T>(response: { ok(): boolean; status(): number; text(): Promise<string>; json(): Promise<unknown> }): Promise<T> {
  expect(response.ok(), await response.text()).toBe(true);
  return response.json() as Promise<T>;
}

async function onboard(admin: APIRequestContext): Promise<Session> {
  return json<Session>(
    await admin.post(`${apiOrigin}/v1/workspaces/onboard`, {
      data: { workspace_name: "扩展 0.3 隔离验收", display_name: "合成管理员" },
    }),
  );
}

async function openPopupPage(
  context: BrowserContext,
  extensionId: string,
): Promise<Page> {
  let worker = context.serviceWorkers()[0];
  if (!worker) worker = await context.waitForEvent("serviceworker");
  const opened = await worker.evaluate(async () => {
    const extensionChrome = (globalThis as unknown as {
      chrome: { action: { openPopup(): Promise<void> } };
    }).chrome;
    try {
      await extensionChrome.action.openPopup();
      return { ok: true };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : "unknown" };
    }
  });
  expect(opened).toEqual({ ok: true });
  const anchor = context.pages()[0] ?? (await context.newPage());
  const cdp = await context.newCDPSession(anchor);
  let popupTarget: { targetId: string; type: string; url: string } | undefined;
  await expect.poll(async () => {
    const targets = await cdp.send("Target.getTargets") as {
      targetInfos: Array<{ targetId: string; type: string; url: string }>;
    };
    popupTarget = targets.targetInfos.find((target) => target.url === `chrome-extension://${extensionId}/popup.html`);
    return popupTarget;
  }, { timeout: 10_000 }).toBeDefined();
  await cdp.detach();
  const cdpBrowser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`);
  const cdpContext = cdpBrowser.contexts()[0];
  if (!cdpContext) throw new Error("CDP did not expose the extension context");
  let popup: Page | undefined;
  await expect.poll(() => {
    popup = cdpContext.pages().find((page) => page.url() === `chrome-extension://${extensionId}/popup.html`);
    return popup;
  }, { timeout: 10_000 }).toBeDefined();
  if (!popup) throw new Error(`CDP did not expose popup target: ${JSON.stringify(popupTarget)}`);
  await popup.waitForLoadState("domcontentloaded");
  expect(popup.url()).toBe(`chrome-extension://${extensionId}/popup.html`);
  return popup;
}

async function launchExtensionContext(profile: string, extensionPath: string): Promise<BrowserContext> {
  return chromium.launchPersistentContext(profile, {
    channel: "chromium",
    headless: false,
    viewport: { width: 1280, height: 800 },
    args: [
      `--disable-extensions-except=${extensionPath}`,
      `--load-extension=${extensionPath}`,
      `--remote-debugging-port=${cdpPort}`,
    ],
  });
}

test("0.3.0 真实扩展链持久续期并安全披露自动化截图权限边界", async ({ browser }) => {
  test.setTimeout(120_000);
  const manifest = JSON.parse(await readFile(join(unpacked, "manifest.json"), "utf8")) as {
    name: string;
    version: string;
  };
  expect(manifest).toMatchObject({ name: "运营数据采集助手", version: "0.3.0" });

  const adminContext = await browser.newContext();
  const editorContext = await browser.newContext();
  const extensionApi = await request.newContext();
  const extensionProfile = await mkdtemp(join(tmpdir(), "operations-ai-extension-e2e-"));
  let extensionContext: BrowserContext | undefined;

  try {
    const testUnpacked = join(extensionProfile, "preauthorized-unpacked");
    await cp(unpacked, testUnpacked, { recursive: true });
    const testManifestPath = join(testUnpacked, "manifest.json");
    const testManifest = JSON.parse(await readFile(testManifestPath, "utf8")) as {
      host_permissions: string[];
    };
    testManifest.host_permissions = [...testManifest.host_permissions, "http://127.0.0.1/*"];
    await writeFile(testManifestPath, JSON.stringify(testManifest, null, 2));
    extensionContext = await launchExtensionContext(extensionProfile, testUnpacked);
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

    let currentWorker = extensionContext.serviceWorkers()[0];
    if (!currentWorker) currentWorker = await extensionContext.waitForEvent("serviceworker");
    const extensionId = new URL(currentWorker.url()).host;
    expect(extensionId).toBe("mdbmlilohlhmjmcmkpbpjhldganompcl");

    const fixtureHtml = await readFile(longCreatorFixture, "utf8");
    await extensionContext.route("https://creator.douyin.com/**", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: fixtureHtml,
      });
    });
    let creator = extensionContext.pages()[0] ?? (await extensionContext.newPage());
    await creator.goto("https://creator.douyin.com/creator-micro/content/manage?fixture=extension-0.3-long-page");
    await expect.poll(() => creator.locator("html").getAttribute("data-operations-capture-supported")).toBe("true");

    let pairingPopup = await openPopupPage(extensionContext, extensionId);
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
    const postPairStorage = await pairingPopup.evaluate(async () => {
      const local = await chrome.storage.local.get("extensionDeviceRegistration");
      const session = await chrome.storage.session.get("extensionBinding");
      return { local: local.extensionDeviceRegistration, session: session.extensionBinding };
    });
    expect(postPairStorage, `popup status: ${await pairingPopup.locator("#status").innerText()}`).toMatchObject({
      local: { deviceId: expect.any(String), extensionVersion: "0.3.0" },
      session: { accessToken: expect.any(String), providerMode: "mock" },
    });
    await expect(pairingPopup.locator("#destination")).toContainText(
      "扩展 0.3 隔离验收",
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
    const persistedKey = await pairingPopup.evaluate(async () => {
      const record = await new Promise<{ privateKey: CryptoKey; publicJwk: JsonWebKey }>((resolve, reject) => {
        const request = indexedDB.open("operations-ai-extension-device", 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
          const database = request.result;
          const read = database.transaction("device-keys", "readonly").objectStore("device-keys").get("device");
          read.onerror = () => reject(read.error);
          read.onsuccess = () => { database.close(); resolve(read.result); };
        };
      });
      let privateExportRejected = false;
      try { await crypto.subtle.exportKey("jwk", record.privateKey); } catch { privateExportRejected = true; }
      return { privateExtractable: record.privateKey.extractable, privateExportRejected, publicJwk: record.publicJwk };
    });
    expect(persistedKey.privateExtractable).toBe(false);
    expect(persistedKey.privateExportRejected).toBe(true);
    expect(Object.keys(persistedKey.publicJwk).sort()).toEqual(["crv", "kty", "x", "y"]);
    await pairingPopup.close();
    await extensionContext.close();
    extensionContext = await launchExtensionContext(extensionProfile, testUnpacked);
    await extensionContext.route("https://creator.douyin.com/**", async (route) => {
      await route.fulfill({ contentType: "text/html; charset=utf-8", body: fixtureHtml });
    });
    creator = extensionContext.pages()[0] ?? (await extensionContext.newPage());
    await creator.goto("https://creator.douyin.com/creator-micro/content/manage?fixture=extension-0.3-long-page-restarted");
    await expect.poll(() => creator.locator("html").getAttribute("data-operations-capture-supported")).toBe("true");
    currentWorker = extensionContext.serviceWorkers()[0] ?? await extensionContext.waitForEvent("serviceworker");
    expect(new URL(currentWorker.url()).host).toBe(extensionId);
    const bindingBeforeRestartPopup = await currentWorker.evaluate(async () =>
      (await chrome.storage.session.get("extensionBinding")).extensionBinding,
    );
    expect(bindingBeforeRestartPopup).toBeUndefined();
    const sessionEventsBefore = await json<{ events: Array<{ path: string; status: number }> }>(
      await extensionApi.get(`${apiOrigin}/__e2e/extension-session-events`, {
        headers: { "X-E2E-Secret": e2eSecret },
      }),
    );
    expect(sessionEventsBefore.events).toEqual([]);
    const restartedWorkerHealth = await currentWorker.evaluate(async (origin) => {
      try {
        const response = await fetch(`${origin}/healthz`);
        return { ok: response.ok, status: response.status };
      } catch (error) {
        return { error: error instanceof Error ? error.message : "unknown" };
      }
    }, apiOrigin);
    expect(restartedWorkerHealth).toEqual({ ok: true, status: 200 });
    const restartedIdentityDiagnostic = await currentWorker.evaluate(async () => {
      const local = await chrome.storage.local.get("extensionDeviceRegistration");
      const rawRecord = await new Promise<{
        deviceId: string;
        privateKey: CryptoKey;
        publicJwk: JsonWebKey;
      }>((resolve, reject) => {
        const request = indexedDB.open("operations-ai-extension-device", 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
          const database = request.result;
          const transaction = database.transaction("device-keys", "readonly");
          const read = transaction.objectStore("device-keys").get("device");
          read.onerror = () => reject(read.error);
          read.onsuccess = () => { database.close(); resolve(read.result); };
        };
      });
      let signatureVerified = false;
      let signatureError: string | null = null;
      try {
        const publicKey = await crypto.subtle.importKey(
          "jwk",
          rawRecord.publicJwk,
          { name: "ECDSA", namedCurve: "P-256" },
          false,
          ["verify"],
        );
        const payload = new Uint8Array([0, 1, 2, 3]);
        const signature = await crypto.subtle.sign(
          { name: "ECDSA", hash: "SHA-256" },
          rawRecord.privateKey,
          payload,
        );
        signatureVerified = await crypto.subtle.verify(
          { name: "ECDSA", hash: "SHA-256" },
          publicKey,
          signature,
          payload,
        );
      } catch (error) {
        signatureError = error instanceof Error ? error.message : String(error);
      }
      return {
        registration: local.extensionDeviceRegistration,
        recordDeviceId: rawRecord.deviceId,
        privateKeyIsCryptoKey: rawRecord.privateKey instanceof CryptoKey,
        privateKeyType: rawRecord.privateKey.type,
        privateKeyExtractable: rawRecord.privateKey.extractable,
        privateKeyAlgorithm: rawRecord.privateKey.algorithm,
        privateKeyUsages: rawRecord.privateKey.usages,
        publicJwk: rawRecord.publicJwk,
        signatureVerified,
        signatureError,
      };
    });
    expect(restartedIdentityDiagnostic).toMatchObject({
      recordDeviceId: persistedConnection.local.deviceId,
      privateKeyIsCryptoKey: true,
      privateKeyType: "private",
      privateKeyExtractable: false,
      privateKeyAlgorithm: { name: "ECDSA", namedCurve: "P-256" },
      privateKeyUsages: ["sign"],
      signatureVerified: true,
      signatureError: null,
    });
    pairingPopup = await openPopupPage(extensionContext, extensionId);
    await pairingPopup.waitForTimeout(1_000);
    const restartDiagnostic = await pairingPopup.evaluate(async () => {
      const session = await chrome.storage.session.get("extensionBinding");
      const local = await chrome.storage.local.get("extensionDeviceRegistration");
      const keyPresent = await new Promise<boolean>((resolve, reject) => {
        const request = indexedDB.open("operations-ai-extension-device", 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
          const database = request.result;
          const read = database.transaction("device-keys", "readonly").objectStore("device-keys").get("device");
          read.onerror = () => reject(read.error);
          read.onsuccess = () => { database.close(); resolve(Boolean(read.result)); };
        };
      });
      const binding = session.extensionBinding as { accessToken?: unknown; providerMode?: unknown; workspaceId?: unknown } | undefined;
      return {
        binding: binding ? {
          accessTokenPresent: typeof binding.accessToken === "string" && binding.accessToken.length > 0,
          providerMode: binding.providerMode,
          workspaceId: binding.workspaceId,
        } : null,
        registration: local.extensionDeviceRegistration,
        keyPresent,
      };
    });
    expect(restartDiagnostic, `${JSON.stringify({ restartDiagnostic, restartedIdentityDiagnostic })}; ${await pairingPopup.locator("#status").innerText()}`).toMatchObject({
      binding: { accessTokenPresent: true, providerMode: "mock", workspaceId: owner.workspace_id },
    });
    await expect(pairingPopup.locator("#destination")).toContainText("扩展 0.3 隔离验收", { timeout: 15_000 });
    const renewedAfterBrowserRestart = await pairingPopup.evaluate(async () => {
      const session = await chrome.storage.session.get("extensionBinding");
      const local = await chrome.storage.local.get("extensionDeviceRegistration");
      const record = await new Promise<{ privateKey: CryptoKey }>((resolve, reject) => {
        const request = indexedDB.open("operations-ai-extension-device", 1);
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
          const database = request.result;
          const read = database.transaction("device-keys", "readonly").objectStore("device-keys").get("device");
          read.onerror = () => reject(read.error);
          read.onsuccess = () => { database.close(); resolve(read.result); };
        };
      });
      return {
        binding: session.extensionBinding,
        registration: local.extensionDeviceRegistration,
        privateExtractable: record.privateKey.extractable,
      };
    });
    expect(renewedAfterBrowserRestart).toMatchObject({
      binding: { accessToken: expect.any(String), providerMode: "mock", workspaceId: owner.workspace_id },
      registration: { deviceId: persistedConnection.local.deviceId, extensionVersion: "0.3.0" },
      privateExtractable: false,
    });
    expect(renewedAfterBrowserRestart.binding.accessToken).not.toBe(persistedConnection.session.accessToken);
    const sessionEventsAfter = await json<{ events: Array<{ path: string; status: number }> }>(
      await extensionApi.get(`${apiOrigin}/__e2e/extension-session-events`, {
        headers: { "X-E2E-Secret": e2eSecret },
      }),
    );
    expect(sessionEventsAfter.events).toEqual([
      { path: "/v1/extension/session/challenge", status: 201 },
      { path: "/v1/extension/session/renew", status: 201 },
    ]);

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
        extension_version: "0.3.0",
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
    const shortcutDisclosure = await capturePopup.locator("#shortcut-status").innerText();
    expect(shortcutDisclosure).toMatch(/^整页采集快捷键：\S+/);
    expect(shortcutDisclosure).not.toContain("未分配");
    await capturePopup.getByRole("button", { name: "自动采集整页" }).click();
    const overlay = creator.locator("[data-operations-capture-overlay]");
    await expect(overlay.getByText("确认截图和遮挡")).toBeVisible({ timeout: 30_000 });
    await expect(overlay).toContainText("当前使用 Mock 识别，不会调用外部付费模型");
    await expect(overlay).toContainText("遮挡敏感信息：关");
    await expect(overlay).toContainText("整页采集未能生成可预览图片：empty（0 张）");
    await expect(overlay.getByRole("button", { name: "确认上传" })).toHaveCount(0);
    const programmaticCaptureBoundary = await currentWorker.evaluate(async () => {
      try {
        await chrome.tabs.captureVisibleTab({ format: "png" });
        return { unexpectedlyCaptured: true, error: null };
      } catch (error) {
        return {
          unexpectedlyCaptured: false,
          error: error instanceof Error ? error.message : String(error),
        };
      }
    });
    expect(programmaticCaptureBoundary.unexpectedlyCaptured).toBe(false);
    expect(programmaticCaptureBoundary.error).toMatch(/activeTab|<all_urls>/);
    expect(account.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(e2eSecret).not.toBe("");
  } finally {
    await extensionContext?.close();
    await extensionApi.dispose();
    await adminContext.close();
    await editorContext.close();
    await rm(extensionProfile, { recursive: true, force: true });
  }
});
