import { JSDOM } from "jsdom";
import { describe, expect, it, vi } from "vitest";

import type { ExtensionBinding } from "../src/auth/storage";
import { createPopupController, type PageStatus } from "../src/popup/main";

const binding: ExtensionBinding = {
  serverOrigin: "https://api.ops.example.com",
  webOrigin: "https://app.ops.example.com",
  workspaceId: "00000000-0000-0000-0000-000000000001",
  workspaceName: "运营工作区",
  memberDisplayName: "小王",
  accessToken: "opaque-short-lived-token",
  expiresAt: "2026-08-11T00:00:00Z",
  providerMode: "mock",
  region: null,
};

const popup = () => new JSDOM(`<!doctype html><body>
  <form id="pairing-form"><input id="pairing-code" required /><button type="submit">连接</button></form>
  <button id="advanced-toggle" type="button">高级设置</button>
  <section id="advanced-settings" hidden><input id="server-origin" /></section>
  <p id="destination"></p><p id="member"></p><p id="processing"></p><p id="expiry"></p><p id="page-status"></p><p id="status"></p>
  <p id="shortcut-status"></p>
  <button id="start-safe-capture" type="button" hidden>自动采集整页</button><details id="more-capture-methods"><summary>更多采集方式</summary><button id="start-visible-capture" type="button">采集可见区域</button><button id="start-region-capture" type="button">手动选区</button></details><button id="unbind" type="button" hidden>解绑</button>
</body>`);

const supported: PageStatus = {
  supported: true,
  platform: "douyin",
  pageVersion: "douyin-visible-tab-v1",
  pageSignature: "douyin:fixture",
};

describe("capture extension pairing popup", () => {
  it("uses the local API by default and keeps remote HTTPS settings hidden", async () => {
    const dom = popup();
    const controller = createPopupController(dom.window.document, {
      store: { load: async () => null, save: async () => undefined, clear: async () => undefined },
      pair: vi.fn(), revoke: vi.fn(), getPageStatus: vi.fn(), startSafeCapture: vi.fn(),
    });
    await controller.render();
    expect(dom.window.document.querySelector<HTMLInputElement>("#server-origin")?.value).toBe("http://127.0.0.1:51201");
    expect(dom.window.document.querySelector("#advanced-settings")?.hasAttribute("hidden")).toBe(true);
    dom.window.document.querySelector<HTMLButtonElement>("#advanced-toggle")?.click();
    expect(dom.window.document.querySelector("#advanced-settings")?.hasAttribute("hidden")).toBe(false);
  });

  it("shows a paired supported page without raw identities or token", async () => {
    const dom = popup();
    const controller = createPopupController(dom.window.document, {
      store: { load: async () => binding, save: async () => undefined, clear: async () => undefined },
      pair: vi.fn(), revoke: vi.fn(), getPageStatus: vi.fn().mockResolvedValue(supported), startSafeCapture: vi.fn(),
    });
    await controller.render();
    const text = dom.window.document.body.textContent ?? "";
    expect(text).toContain("https://app.ops.example.com");
    expect(text).toContain("运营工作区");
    expect(text).toContain("小王");
    expect(text).not.toContain(binding.workspaceId);
    expect(text).not.toContain(binding.accessToken);
    expect(dom.window.document.querySelector("#start-safe-capture")?.hasAttribute("hidden")).toBe(false);
    expect(dom.window.document.querySelector("#advanced-settings")?.hasAttribute("hidden")).toBe(true);
    expect(dom.window.document.querySelector("#advanced-toggle")?.hasAttribute("hidden")).toBe(true);
  });

  it("explains an unsupported page and hides safe capture while still paired", async () => {
    const dom = popup();
    const controller = createPopupController(dom.window.document, {
      store: { load: async () => binding, save: async () => undefined, clear: async () => undefined },
      pair: vi.fn(), revoke: vi.fn(), getPageStatus: vi.fn().mockResolvedValue({ supported: false, platform: null, pageVersion: "unknown", pageSignature: "unsupported", reason: "unsupported-url" }), startSafeCapture: vi.fn(),
    });
    await controller.render();
    expect(dom.window.document.querySelector("#page-status")?.textContent).toContain("当前页面暂不支持");
    expect(dom.window.document.querySelector("#start-safe-capture")?.hasAttribute("hidden")).toBe(true);
  });

  it("degrades an expired binding to the unpaired state", async () => {
    const dom = popup();
    const clear = vi.fn();
    const controller = createPopupController(dom.window.document, {
      store: { load: async () => ({ ...binding, expiresAt: "2026-08-09T00:00:00Z" }), save: async () => undefined, clear },
      pair: vi.fn(), revoke: vi.fn(), getPageStatus: vi.fn(), startSafeCapture: vi.fn(), now: () => Date.parse("2026-08-10T00:00:00Z"),
    });
    await controller.render();
    expect(clear).toHaveBeenCalledOnce();
    expect(dom.window.document.querySelector("#status")?.textContent).toContain("连接已过期");
    expect(dom.window.document.querySelector("#pairing-form")?.hasAttribute("hidden")).toBe(false);
  });

  it("clears the pairing code after a successful and failed submission", async () => {
    for (const pair of [vi.fn().mockResolvedValue(undefined), vi.fn().mockRejectedValue(new Error("服务器配对失败"))]) {
      const dom = popup();
      const code = dom.window.document.querySelector<HTMLInputElement>("#pairing-code")!;
      code.value = "123456";
      const controller = createPopupController(dom.window.document, {
        store: { load: async () => null, save: async () => undefined, clear: async () => undefined },
        pair, revoke: vi.fn(), getPageStatus: vi.fn(), startSafeCapture: vi.fn(),
      });
      await controller.submit();
      expect(code.value).toBe("");
    }
  });

  it("sends start only for a paired supported page", async () => {
    const dom = popup();
    const startSafeCapture = vi.fn();
    const controller = createPopupController(dom.window.document, {
      store: { load: async () => binding, save: async () => undefined, clear: async () => undefined },
      pair: vi.fn(), revoke: vi.fn(), getPageStatus: vi.fn().mockResolvedValue(supported), startSafeCapture,
    });
    await controller.render();
    await controller.start();
    expect(startSafeCapture).toHaveBeenCalledWith({ type: "START_CAPTURE", mode: "full-page" });
  });

  it("shows the actual registered shortcut and keeps secondary modes under more capture methods", async () => {
    const dom = popup();
    const controller = createPopupController(dom.window.document, {
      store: { load: async () => binding, save: async () => undefined, clear: async () => undefined },
      pair: vi.fn(), revoke: vi.fn(), getPageStatus: vi.fn().mockResolvedValue(supported), startSafeCapture: vi.fn(),
      getShortcut: vi.fn().mockResolvedValue("Command+Shift+8"),
    });
    await controller.render();
    expect(dom.window.document.querySelector("#shortcut-status")?.textContent).toContain("Command+Shift+8");
    expect(dom.window.document.querySelector("#start-safe-capture")?.textContent).toBe("自动采集整页");
    expect(dom.window.document.querySelector("#more-capture-methods")?.textContent).toContain("采集可见区域");
    expect(dom.window.document.querySelector("#more-capture-methods")?.textContent).toContain("手动选区");
  });

  it.each([
    ["fetch rejection", async () => { throw new Error("offline"); }],
    ["non-2xx response", async () => { throw new Error("503"); }],
    ["normal 204", async () => undefined],
  ])("always completes local unbinding after %s", async (_name, revoke) => {
    const dom = popup();
    let stored: ExtensionBinding | null = binding;
    const clearTrust = vi.fn();
    const controller = createPopupController(dom.window.document, {
      store: {
        load: async () => stored,
        save: async (next) => { stored = next; },
        clear: async () => { stored = null; },
      },
      pair: vi.fn(),
      revoke: async () => {
        stored = null;
        await revoke();
      },
      getPageStatus: vi.fn().mockResolvedValue(supported),
      startSafeCapture: vi.fn(),
      onUnbound: async () => { clearTrust(); },
    });
    await controller.render();
    await expect(controller.unbind()).resolves.toBeUndefined();
    expect(clearTrust).toHaveBeenCalledOnce();
    expect(dom.window.document.querySelector("#pairing-form")?.hasAttribute("hidden")).toBe(false);
    expect(dom.window.document.querySelector("#start-safe-capture")?.hasAttribute("hidden")).toBe(true);
    if (_name !== "normal 204") {
      const status = dom.window.document.querySelector("#status")?.textContent;
      expect(status).toBe("本地已解绑，但未能通知服务器；服务端令牌将在到期后自动失效。");
      expect(status).not.toContain("恢复连接后完成");
    }
  });
});
