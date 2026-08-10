import { describe, expect, it, vi } from "vitest";

import { createBackgroundMessageHandler } from "../src/background";
import { createContentMessageHandler } from "../src/content";
import { armAndStartSafeCapture } from "../src/popup/main";
import { parseRuntimeMessage } from "../src/runtime/messages";

const supportedTab = {
  id: 7,
  windowId: 3,
  url: "https://creator.douyin.com/creator-micro/content/manage",
};

describe("extension runtime message boundary", () => {
  it("accepts only exact, typed capture messages", () => {
    expect(parseRuntimeMessage({ type: "GET_PAGE_STATUS" })).toEqual({ type: "GET_PAGE_STATUS" });
    expect(parseRuntimeMessage({ type: "START_SAFE_CAPTURE", tabId: 7 })).toEqual({
      type: "START_SAFE_CAPTURE",
      tabId: 7,
    });
    expect(parseRuntimeMessage({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" })).toEqual({
      type: "CAPTURE_VISIBLE_TAB",
      pageSignature: "douyin:fixture",
    });
    expect(parseRuntimeMessage({ type: "OPEN_REVIEW", url: "https://app.example/review" })).toEqual({
      type: "OPEN_REVIEW",
      url: "https://app.example/review",
    });

    expect(parseRuntimeMessage({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "", token: "secret" })).toBeNull();
    expect(parseRuntimeMessage({ type: "START_SAFE_CAPTURE", tabId: -1 })).toBeNull();
    expect(parseRuntimeMessage({ type: "UNKNOWN" })).toBeNull();
  });

  it("captures only once after the popup arms the active supported tab", async () => {
    const captureVisibleTab = vi.fn().mockResolvedValue("data:image/png;base64,SAFE");
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn().mockResolvedValue(supportedTab),
      captureVisibleTab,
      now: () => 1000,
    });

    await expect(handler({ type: "START_SAFE_CAPTURE", tabId: 7 }, {})).resolves.toEqual({ ok: true });
    await expect(
      handler(
        { type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" },
        { tab: supportedTab },
      ),
    ).resolves.toEqual({ ok: true, dataUrl: "data:image/png;base64,SAFE" });
    expect(captureVisibleTab).toHaveBeenCalledWith(3, { format: "png" });

    await expect(
      handler(
        { type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" },
        { tab: supportedTab },
      ),
    ).resolves.toEqual({ ok: false, error: "capture-not-armed" });
    expect(captureVisibleTab).toHaveBeenCalledTimes(1);
  });

  it("rejects inactive, unsupported, expired, and non-tab capture senders", async () => {
    const captureVisibleTab = vi.fn();
    let now = 1000;
    const queryActiveTab = vi.fn().mockResolvedValue(supportedTab);
    const handler = createBackgroundMessageHandler({
      queryActiveTab,
      captureVisibleTab,
      now: () => now,
    });

    await handler({ type: "START_SAFE_CAPTURE", tabId: 7 }, {});
    queryActiveTab.mockResolvedValueOnce({ ...supportedTab, id: 8 });
    await expect(
      handler({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" }, { tab: supportedTab }),
    ).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });

    await handler({ type: "START_SAFE_CAPTURE", tabId: 7 }, {});
    queryActiveTab.mockResolvedValueOnce({
      ...supportedTab,
      url: "https://creator.xiaohongshu.com/publish/publish-manage",
    });
    await expect(
      handler({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" }, { tab: supportedTab }),
    ).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });

    queryActiveTab.mockResolvedValue(supportedTab);
    await handler({ type: "START_SAFE_CAPTURE", tabId: 7 }, {});
    now = 32_000;
    await expect(
      handler({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" }, { tab: supportedTab }),
    ).resolves.toEqual({ ok: false, error: "capture-not-armed" });

    await expect(
      handler({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" }, {}),
    ).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });
    expect(captureVisibleTab).not.toHaveBeenCalled();
  });

  it("arms the active tab before asking its content script to start", async () => {
    const arm = vi.fn().mockResolvedValue({ ok: true });
    const startContent = vi.fn().mockResolvedValue({ ok: true });
    await expect(armAndStartSafeCapture(7, arm, startContent)).resolves.toBeUndefined();
    expect(arm.mock.invocationCallOrder[0]).toBeLessThan(startContent.mock.invocationCallOrder[0]);
    expect(arm).toHaveBeenCalledWith({ type: "START_SAFE_CAPTURE", tabId: 7 });
    expect(startContent).toHaveBeenCalledWith({ type: "START_SAFE_CAPTURE" });

    startContent.mockClear();
    await expect(
      armAndStartSafeCapture(7, vi.fn().mockResolvedValue({ ok: false }), startContent),
    ).rejects.toThrow("capture-not-armed");
    expect(startContent).not.toHaveBeenCalled();

    await expect(
      armAndStartSafeCapture(
        7,
        vi.fn().mockResolvedValue({ ok: true }),
        vi.fn().mockResolvedValue({ ok: false, error: "rebind-required" }),
      ),
    ).rejects.toThrow("rebind-required");
  });

  it("reports page status and mounts capture only for an exact explicit start message", async () => {
    const mount = vi.fn().mockResolvedValue(undefined);
    const handler = createContentMessageHandler({
      detect: () => ({
        supported: true,
        platform: "douyin",
        pageVersion: "douyin-visible-tab-v1",
        signature: "douyin:fixture",
        captureRegion: null,
        sensitiveRegions: [],
      }),
      startCapture: mount,
    });
    await expect(handler({ type: "GET_PAGE_STATUS" })).resolves.toEqual({
      supported: true,
      platform: "douyin",
      pageVersion: "douyin-visible-tab-v1",
    });
    await expect(handler({ type: "START_SAFE_CAPTURE" })).resolves.toEqual({ ok: true });
    expect(mount).toHaveBeenCalledOnce();
    await expect(handler({ type: "START_SAFE_CAPTURE", extra: true })).resolves.toEqual({
      ok: false,
      error: "invalid-message",
    });
    expect(mount).toHaveBeenCalledOnce();
  });
});
