import { chromium, expect, request, test, type APIRequestContext } from "@playwright/test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const apiOrigin = "http://127.0.0.1:8120";
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

test("0.2.0 配对、安全采集和 Web 人工确认形成隔离闭环", async ({ browser }) => {
  test.setTimeout(120_000);
  const manifest = JSON.parse(await readFile(join(unpacked, "manifest.json"), "utf8")) as {
    name: string;
    version: string;
  };
  expect(manifest).toMatchObject({ name: "运营数据采集助手", version: "0.2.0" });

  const adminContext = await browser.newContext();
  const editorContext = await browser.newContext();
  const syntheticContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const extensionApi = await request.newContext();
  const extensionProfile = await mkdtemp(join(tmpdir(), "operations-ai-extension-e2e-"));
  const extensionContext = await chromium.launchPersistentContext(extensionProfile, {
    channel: "chromium",
    headless: false,
    viewport: { width: 1280, height: 800 },
    args: [`--disable-extensions-except=${unpacked}`, `--load-extension=${unpacked}`],
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
    const paired = await json<{
      workspace_id: string;
      workspace_name: string;
      member_display_name: string;
      access_token: string;
      expires_at: string;
      provider_mode: "mock";
      region: null;
      web_origin: string;
    }>(
      await extensionApi.post(`${apiOrigin}/v1/extension/pair`, {
        headers: { "X-Extension-Client": extensionClient },
        data: { pairing_code: pairing.pairing_code, client_id: extensionClient },
      }),
    );
    await serviceWorker.evaluate(
      async ({ apiOrigin: serverOrigin, paired: response }) => {
        await chrome.storage.session.set({
          extensionBinding: {
            serverOrigin,
            webOrigin: response.web_origin,
            workspaceId: response.workspace_id,
            workspaceName: response.workspace_name,
            memberDisplayName: response.member_display_name,
            accessToken: response.access_token,
            expiresAt: response.expires_at,
            providerMode: response.provider_mode,
            region: response.region,
          },
        });
      },
      { apiOrigin, paired },
    );
    const popup = await extensionContext.newPage();
    await popup.goto(`chrome-extension://${extensionId}/popup.html`);
    await expect(popup.locator("#destination")).toContainText("扩展 0.2 隔离验收");

    const membersAfter = await json<Array<{ id: string }>>(
      await admin.get(`${apiOrigin}/v1/workspaces/${owner.workspace_id}/members`),
    );
    expect(membersAfter.map(({ id }) => id)).toEqual(membersBefore.map(({ id }) => id));

    const replay = await extensionApi.post(`${apiOrigin}/v1/extension/pair`, {
      headers: { "X-Extension-Client": extensionClient },
      data: { pairing_code: pairing.pairing_code, client_id: extensionClient },
    });
    expect(replay.status()).toBe(401);
    expect(await replay.json()).toEqual({ detail: "pairing code invalid or expired" });

    await syntheticContext.route("https://creator.douyin.com/**", async (route) => {
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: `<!doctype html><html><body style="margin:0;background:#f6f7fb">
          <main style="padding:180px 80px"><h1>合成创作者页面</h1>
          <section style="width:760px;height:420px;background:#fff;border:1px solid #ccd3df">仅用于隔离截图验收</section></main>
        </body></html>`,
      });
    });
    const creator = await syntheticContext.newPage();
    await creator.goto("https://creator.douyin.com/creator-micro/content/manage?fixture=extension-0.2");
    await creator.exposeFunction(
      "__operationsExtensionFetch",
      async (url: string, init: { method?: string; headers?: Record<string, string>; body?: string }) => {
        const response = await extensionApi.fetch(url, {
          method: init.method,
          headers: init.headers,
          data: init.body,
        });
        return { status: response.status(), body: await response.text() };
      },
    );
    await creator.evaluate(
      ({ apiOrigin: serverOrigin, paired: response }) => {
        const binding = {
          serverOrigin,
          webOrigin: response.web_origin,
          workspaceId: response.workspace_id,
          workspaceName: response.workspace_name,
          memberDisplayName: response.member_display_name,
          accessToken: response.access_token,
          expiresAt: response.expires_at,
          providerMode: response.provider_mode,
          region: response.region,
        };
        const nativeFetch = window.fetch.bind(window);
        Object.assign(window, {
          fetch: async (input: RequestInfo | URL, init: RequestInit = {}) => {
            const url = String(input);
            if (!url.startsWith(serverOrigin)) return nativeFetch(input, init);
            const result = await (window as unknown as {
              __operationsExtensionFetch(
                url: string,
                init: { method?: string; headers?: Record<string, string>; body?: string },
              ): Promise<{ status: number; body: string }>;
            }).__operationsExtensionFetch(url, {
              method: init.method,
              headers: Object.fromEntries(new Headers(init.headers).entries()),
              body: typeof init.body === "string" ? init.body : undefined,
            });
            return new Response(result.body, {
              status: result.status,
              headers: { "Content-Type": "application/json" },
            });
          },
          chrome: {
            storage: {
              session: {
                get: async () => ({ extensionBinding: binding }),
                set: async () => undefined,
                remove: async () => undefined,
              },
            },
            runtime: {
              onMessage: {
                addListener: (listener: unknown) => {
                  (window as unknown as { __operationsContentListener: unknown }).__operationsContentListener = listener;
                },
              },
              sendMessage: async (message: { type?: string }) => {
                if (message.type !== "CAPTURE_VISIBLE_TAB") return { ok: false, error: "unsupported-message" };
                const ratio = window.devicePixelRatio || 1;
                const canvas = document.createElement("canvas");
                canvas.width = Math.round(window.innerWidth * ratio);
                canvas.height = Math.round(window.innerHeight * ratio);
                const context = canvas.getContext("2d")!;
                context.fillStyle = "#f6f7fb";
                context.fillRect(0, 0, canvas.width, canvas.height);
                context.fillStyle = "#2864dc";
                context.fillRect(100 * ratio, 220 * ratio, 760 * ratio, 420 * ratio);
                return { ok: true, dataUrl: canvas.toDataURL("image/png") };
              },
            },
          },
        });
      },
      { apiOrigin, paired },
    );
    await creator.addScriptTag({ path: join(unpacked, "content.js") });
    await expect.poll(() => creator.locator("html").getAttribute("data-operations-capture-supported")).toBe("true");
    await popup.close();
    await creator.bringToFront();
    const started = await creator.evaluate(
      () =>
        new Promise<unknown>((resolve) => {
          const listener = (window as unknown as {
            __operationsContentListener: (
              message: unknown,
              sender: unknown,
              respond: (value: unknown) => void,
            ) => void;
          }).__operationsContentListener;
          listener({ type: "START_SAFE_CAPTURE" }, {}, resolve);
        }),
    );
    expect(started).toEqual({ ok: true });

    const overlay = creator.locator("[data-operations-capture-overlay]");
    await expect(overlay.getByText("拖动选择要采集的区域")).toBeVisible();
    await creator.mouse.move(90, 260);
    await creator.mouse.down();
    await creator.mouse.move(850, 700);
    await creator.mouse.up();
    await expect(overlay.getByAltText("待确认的采集截图")).toBeVisible();
    await overlay.getByRole("button", { name: "添加遮挡" }).click();
    const preview = overlay.getByAltText("待确认的采集截图");
    const bounds = await preview.boundingBox();
    expect(bounds).not.toBeNull();
    await creator.mouse.move(bounds!.x + 30, bounds!.y + 30);
    await creator.mouse.down();
    await creator.mouse.move(bounds!.x + 180, bounds!.y + 90);
    await creator.mouse.up();
    await expect(overlay.getByText(/遮挡：/)).toBeVisible();
    await overlay.getByRole("button", { name: "确认上传" }).click();
    const reviewLink = overlay.locator("[data-review-link]");
    await expect(reviewLink).toBeVisible({ timeout: 30_000 });
    const reviewUrl = await reviewLink.getAttribute("href");
    expect(reviewUrl).toContain(`/workspaces/${owner.workspace_id}/imports`);
    const taskId = new URL(reviewUrl!).searchParams.get("capture_task_id");
    expect(taskId).toBeTruthy();

    const binding = await serviceWorker.evaluate(async () => {
      const stored = await chrome.storage.session.get("extensionBinding");
      return stored.extensionBinding as { accessToken: string; workspaceId: string };
    });
    expect(binding.workspaceId).toBe(owner.workspace_id);
    const scopedTask = await json<{ status: string; workspace_id: string }>(
      await extensionApi.get(
        `${apiOrigin}/v1/extension/workspaces/${owner.workspace_id}/capture-tasks/${taskId}`,
        { headers: { Authorization: `Bearer ${binding.accessToken}` } },
      ),
    );
    expect(scopedTask).toMatchObject({ status: "succeeded", workspace_id: owner.workspace_id });

    const extensionConfirmClient = await request.newContext();
    try {
      const denied = await extensionConfirmClient.post(`${apiOrigin}/v1/extension/capture-tasks/${taskId}/confirm`, {
        headers: { Authorization: `Bearer ${binding.accessToken}` },
      });
      expect(denied.status()).toBe(403);
    } finally {
      await extensionConfirmClient.dispose();
    }

    const editorPage = await editorContext.newPage();
    const editorReviewUrl = new URL(reviewUrl!);
    editorReviewUrl.searchParams.set("platform", "douyin");
    editorReviewUrl.searchParams.set("account", account.id);
    await editorPage.goto(editorReviewUrl.toString());
    await editorPage.evaluate((csrf) => sessionStorage.setItem("workspace_csrf", csrf), editorSession.csrf_token);
    await editorPage.reload();
    await expect(editorPage.getByText("扩展识别结果待确认")).toBeVisible();
    await editorPage.getByRole("button", { name: "人工确认并写入快照" }).click();
    await expect(editorPage.getByText("已写入 1 条正式快照。")).toBeVisible();

    const confirmed = await json<{ formal_snapshot_ids: string[] }>(
      await editor.get(`${apiOrigin}/v1/imports/capture-tasks/${taskId}`),
    );
    expect(confirmed.formal_snapshot_ids).toHaveLength(1);
  } finally {
    await extensionContext.close();
    await extensionApi.dispose();
    await adminContext.close();
    await editorContext.close();
    await syntheticContext.close();
    await rm(extensionProfile, { recursive: true, force: true });
  }
});
