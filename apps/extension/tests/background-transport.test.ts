import { describe, expect, it, vi } from "vitest";

import {
  pollCaptureThroughBackground,
  uploadHotspotThroughBackground,
  uploadCaptureThroughBackground,
} from "../src/capture/background-transport";
import { CaptureState } from "../src/content/overlay";

const context = {
  platform: "douyin" as const,
  pageVersion: "douyin-visible-tab-v1",
  pageSignature: "douyin:fixture",
};

describe("background capture transport", () => {
  it("sends the final preview to the background without server credentials", async () => {
    const sendMessage = vi.fn().mockResolvedValue({
      ok: true,
      task: { task_id: "00000000-0000-0000-0000-000000000002", status: "queued" },
    });

    await expect(uploadCaptureThroughBackground({
      controller: {
        state: CaptureState.PreviewReady,
        preview: { imageData: "data:image/png;base64,SYNTHETIC", maskedRegions: [] },
        canUpload: () => true,
      },
      ...context,
      collectedAt: "2030-01-01T00:00:00.000Z",
      idempotencyKey: "capture-idem-1",
      captureMetadata: {
        capture_mode: "full-page",
        complete: true,
        stop_reason: "bottom",
        slice_count: 3,
      },
      sendMessage,
    })).resolves.toMatchObject({ status: "queued" });

    const message = sendMessage.mock.calls[0]?.[0];
    expect(message).toEqual({
      type: "UPLOAD_CAPTURE_TASK",
      ...context,
      screenshotDataUrl: "data:image/png;base64,SYNTHETIC",
      collectedAt: "2030-01-01T00:00:00.000Z",
      idempotencyKey: "capture-idem-1",
      captureMetadata: {
        capture_mode: "full-page",
        complete: true,
        stop_reason: "bottom",
        slice_count: 3,
      },
    });
    expect(JSON.stringify(message)).not.toContain("accessToken");
    expect(JSON.stringify(message)).not.toContain("serverOrigin");
  });

  it("polls through the background and preserves safe terminal errors", async () => {
    const sendMessage = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        task: { task_id: "00000000-0000-0000-0000-000000000002", status: "succeeded" },
      })
      .mockResolvedValueOnce({ ok: false, error: "rebind-required" });

    await expect(pollCaptureThroughBackground({
      ...context,
      taskId: "00000000-0000-0000-0000-000000000002",
      sendMessage,
    })).resolves.toMatchObject({ status: "succeeded" });
    await expect(pollCaptureThroughBackground({
      ...context,
      taskId: "00000000-0000-0000-0000-000000000002",
      sendMessage,
    })).rejects.toThrow("rebind-required");
  });

  it("rejects a non-final preview before crossing the runtime boundary", async () => {
    const sendMessage = vi.fn();
    await expect(uploadCaptureThroughBackground({
      controller: { state: CaptureState.Capturing, preview: null, canUpload: () => false },
      ...context,
      collectedAt: "2030-01-01T00:00:00.000Z",
      idempotencyKey: "capture-idem-1",
      captureMetadata: {
        capture_mode: "visible",
        complete: true,
        stop_reason: "visible",
        slice_count: 1,
      },
      sendMessage,
    })).rejects.toThrow("preview_ready");
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("sends hotspot page metadata without credentials", async () => {
    const sendMessage = vi.fn().mockResolvedValue({
      ok: true,
      task: { task_id: "00000000-0000-0000-0000-000000000003", status: "queued" },
    });
    await uploadHotspotThroughBackground({
      controller: {
        state: CaptureState.PreviewReady,
        preview: { imageData: "data:image/png;base64,SYNTHETIC", maskedRegions: [] },
        canUpload: () => true,
      },
      platform: "douyin", pageVersion: "hotspot-public-page-v1", pageSignature: "douyin:hotspot:test",
      collectedAt: "2030-01-01T00:00:00.000Z", idempotencyKey: "hotspot-1",
      sourceUrl: "https://example.com/trending", pageTitle: "今日热榜",
      captureMetadata: { capture_mode: "full-page", complete: true, stop_reason: "bottom", slice_count: 2 },
      sendMessage,
    });
    expect(sendMessage.mock.calls[0]?.[0]).toMatchObject({
      type: "UPLOAD_HOTSPOT_CAPTURE", sourceUrl: "https://example.com/trending", pageTitle: "今日热榜",
    });
    expect(JSON.stringify(sendMessage.mock.calls[0]?.[0])).not.toContain("accessToken");
  });
});
