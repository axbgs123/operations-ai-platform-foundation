import { describe, expect, it, vi } from "vitest";
import { CaptureState, SafeCaptureController } from "../src/content/overlay";
import { applyRectangularRedaction } from "../src/content/redaction";

const detected = {
  supported: true as const,
  platform: "douyin" as const,
  pageVersion: "douyin-creator-v1",
  signature: "douyin:1234567890abcdef",
  captureRegion: { x: 10, y: 20, width: 300, height: 200 },
  sensitiveRegions: [
    { kind: "phone", label: "手机号", rect: { x: 20, y: 30, width: 80, height: 20 } },
  ],
};

describe("preview-first safe capture mode", () => {
  it("starts in a non-capturing state and requires explicit region confirmation", async () => {
    const capture = vi.fn().mockResolvedValue("synthetic-image");
    const controller = new SafeCaptureController(() => detected, capture);

    expect(controller.state).toBe(CaptureState.Detected);
    expect(controller.canUpload()).toBe(false);
    await controller.beginPreview();
    expect(controller.state).toBe(CaptureState.PreviewRequired);
    expect(capture).not.toHaveBeenCalled();
    await controller.confirmRegion();
    expect(capture).toHaveBeenCalledTimes(1);
    expect(controller.state).toBe(CaptureState.Redacting);
  });

  it("requires a final preview, supports crop/redaction, and never exposes an upload before ready", async () => {
    const controller = new SafeCaptureController(
      () => detected,
      vi.fn().mockResolvedValue("synthetic-image"),
    );
    await controller.beginPreview();
    await controller.confirmRegion();
    expect(controller.canUpload()).toBe(false);
    const masked = applyRectangularRedaction(
      { imageData: "synthetic-image", maskedRegions: [] },
      [detected.sensitiveRegions[0].rect],
    );
    controller.setPreview(masked);
    expect(controller.state).toBe(CaptureState.PreviewReady);
    expect(controller.canUpload()).toBe(true);
    expect(masked.imageData).not.toBe("synthetic-image");
    await expect(controller.unredact()).rejects.toThrow("confirmation-required");
    await controller.cancel();
    expect(controller.state).toBe(CaptureState.Cancelled);
    expect(controller.preview).toBeNull();
  });

  it("fails safe when signature or sensitive regions change, and supports retake", async () => {
    let current = detected;
    const controller = new SafeCaptureController(
      () => current,
      vi.fn().mockResolvedValue("synthetic-image"),
    );
    await controller.beginPreview();
    current = { ...detected, signature: "douyin:fedcba0987654321" };
    await expect(controller.confirmRegion()).rejects.toThrow("page-changed");
    expect(controller.state).toBe(CaptureState.Failed);
    expect(controller.preview).toBeNull();

    current = detected;
    await controller.beginPreview();
    await controller.confirmRegion();
    current = {
      ...detected,
      sensitiveRegions: [
        ...detected.sensitiveRegions,
        { kind: "email", label: "邮箱", rect: { x: 1, y: 2, width: 90, height: 20 } },
      ],
    };
    await expect(controller.setPreview({ imageData: "image", maskedRegions: [] })).rejects.toThrow(
      "sensitive-region-changed",
    );
    expect(controller.state).toBe(CaptureState.Failed);
  });

  it("does not restore an unconfirmed capture after a service worker restart", async () => {
    const controller = new SafeCaptureController(() => detected, vi.fn());
    expect(controller.serializeForRestart()).toEqual({ state: CaptureState.Detected });
    expect(SafeCaptureController.restoreAfterRestart({ state: CaptureState.Capturing }, () => detected, vi.fn()).state).toBe(
      CaptureState.Detected,
    );
  });
});
