import { describe, expect, it, vi } from "vitest";
import { createTrustStore, establishTrust, type TrustContext } from "../src/capture/trust-state";
import { OneClickController } from "../src/capture/one-click";

const context: TrustContext = {
  serverOrigin: "https://synthetic.example",
  platform: "xiaohongshu",
  pageSignature: "xhs:signature-1",
  pageVersion: "xiaohongshu-creator-v1",
  extensionVersion: "0.1.0",
  captureRegionFingerprint: "region-1",
  sensitiveRegionFingerprint: "sensitive-1",
};

describe("one-click fail-safe fallback", () => {
  it.each([
    ["page signature changes", { pageSignature: "changed" }, "trust-mismatch"],
    ["page version changes", { pageVersion: "future" }, "trust-mismatch"],
    ["capture region changes", { captureRegionFingerprint: "expanded" }, "trust-mismatch"],
    ["sensitive region expands", { sensitiveRegionFingerprint: "expanded" }, "trust-mismatch"],
    ["captcha appears", { captchaDetected: true }, "captcha-or-login"],
    ["login state is abnormal", { loginRequired: true }, "captcha-or-login"],
  ])("falls back when %s", async (_name, overrides, reason) => {
    const store = createTrustStore();
    await establishTrust(store, context);
    const controller = new OneClickController(store);
    await controller.restore();
    await expect(
      controller.capture(
        { ...context, ...overrides } as TrustContext & {
          captchaDetected?: boolean;
          loginRequired?: boolean;
        },
        { captureVisibleTab: vi.fn(), upload: vi.fn() },
      ),
    ).rejects.toThrow(reason);
    expect(controller.enabled).toBe(false);
    expect(await store.load()).toBeNull();
  });

  it("falls back after capture, upload, or recognition failures without bypassing controls", async () => {
    const store = createTrustStore();
    await establishTrust(store, context);
    const controller = new OneClickController(store);
    await controller.restore();
    await expect(
      controller.capture(context, {
        captureVisibleTab: vi.fn().mockRejectedValue(new Error("capture failed")),
        upload: vi.fn(),
      }),
    ).rejects.toThrow("capture-failed");
    expect(controller.enabled).toBe(false);

    await controller.enable(context, { safeCaptureCompleted: true });
    await expect(
      controller.capture(context, {
        captureVisibleTab: vi.fn().mockResolvedValue("image"),
        upload: vi.fn().mockResolvedValue({ status: "failed" }),
      }),
    ).rejects.toThrow("recognition-failed");
    expect(controller.enabled).toBe(false);

    await controller.enable(context, { safeCaptureCompleted: true });
    await expect(
      controller.capture(context, {
        captureVisibleTab: vi.fn().mockResolvedValue("image"),
        upload: vi.fn().mockRejectedValue(new Error("upload failed")),
      }),
    ).rejects.toThrow("upload-failed");
    expect(controller.enabled).toBe(false);
  });

  it("restores only trust metadata after a service worker restart", async () => {
    const store = createTrustStore();
    await establishTrust(store, context);
    const controller = OneClickController.restoreAfterRestart(store);
    await controller.restore();
    expect(controller.enabled).toBe(true);
    expect(controller.serializedRuntimeState()).toEqual({
      enabled: true,
      hasPreview: false,
      hasToken: false,
    });
  });
});
