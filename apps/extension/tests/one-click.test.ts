import { describe, expect, it, vi } from "vitest";
import {
  createPersistedTrustStore,
  createTrustStore,
  establishTrust,
  type TrustContext,
} from "../src/capture/trust-state";
import { OneClickController } from "../src/capture/one-click";

const context: TrustContext = {
  serverOrigin: "https://synthetic.example",
  platform: "douyin",
  pageSignature: "douyin:signature-1",
  pageVersion: "douyin-creator-v1",
  extensionVersion: "0.1.0",
  captureRegionFingerprint: "region-1",
  sensitiveRegionFingerprint: "sensitive-1",
};

describe("opt-in one-click capture", () => {
  it("is off by default and can only be enabled after safe capture success", async () => {
    const store = createTrustStore();
    const controller = new OneClickController(store);
    expect(controller.enabled).toBe(false);
    await expect(controller.enable(context, { safeCaptureCompleted: false })).rejects.toThrow(
      "safe-capture-required",
    );
    await controller.enable(context, { safeCaptureCompleted: true });
    expect(controller.enabled).toBe(true);
    expect(await store.load()).toMatchObject(context);
  });

  it("requires an exact server/platform/signature/version/region match before capture", async () => {
    const store = createTrustStore();
    await establishTrust(store, context);
    const controller = new OneClickController(store);
    await controller.restore();
    const capture = vi.fn().mockResolvedValue("synthetic-image");
    const upload = vi.fn().mockResolvedValue({ review_url: "/review/task-1" });

    await expect(
      controller.capture(
        { ...context, pageSignature: "changed-signature" },
        { captureVisibleTab: capture, upload },
      ),
    ).rejects.toThrow("trust-mismatch");
    expect(capture).not.toHaveBeenCalled();

    await controller.enable(context, { safeCaptureCompleted: true });
    const result = await controller.capture<{ review_url: string }>(context, {
      captureVisibleTab: capture,
      upload,
    });
    expect(result.review_url).toBe("/review/task-1");
    expect(capture).toHaveBeenCalledTimes(1);
    expect(upload).toHaveBeenCalledWith("synthetic-image");
  });

  it("keeps Web confirmation outside one-click and allows the user to turn it off", async () => {
    const store = createTrustStore();
    const controller = new OneClickController(store);
    await controller.enable(context, { safeCaptureCompleted: true });
    expect(controller.requiresWebConfirmation()).toBe(true);
    await controller.disable();
    expect(controller.enabled).toBe(false);
    expect(await store.load()).toBeNull();
  });

  it("persists only typed trust metadata and rejects malformed stored state", async () => {
    let value: Record<string, unknown> = {};
    const storage = {
      async get(key: string) {
        return { [key]: value[key] };
      },
      async set(values: Record<string, unknown>) {
        value = values;
      },
      async remove(key: string) {
        delete value[key];
      },
    };
    const store = createPersistedTrustStore(storage);
    await establishTrust(store, context);
    expect(value).not.toHaveProperty("accessToken");
    expect(value).not.toHaveProperty("screenshot");
    expect(await store.load()).toMatchObject(context);
    value.captureTrustState = { serverOrigin: context.serverOrigin };
    expect(await store.load()).toBeNull();
  });
});
