import { describe, expect, it, vi } from "vitest";
import { CaptureState } from "../src/content/overlay";
import { uploadPreview } from "../src/capture/upload";
import { pollCaptureTask } from "../src/capture/task-status";

const previewController = (state: CaptureState) => ({
  state,
  preview: state === CaptureState.PreviewReady
    ? { imageData: "data:image/png;base64,SYNTHETIC", maskedRegions: [] }
    : null,
  canUpload: () => state === CaptureState.PreviewReady,
});

describe("extension capture upload", () => {
  it("uploads only a final preview with minimal metadata and bearer/idempotency headers", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          task_id: "task-1",
          status: "queued",
          request_id: "req-1",
          review_url: "/review/task-1",
          expires_at: "2030-01-01T00:00:00Z",
        }),
        { status: 202 },
      ),
    );
    const result = await uploadPreview({
      controller: previewController(CaptureState.PreviewReady),
      serverOrigin: "https://synthetic.example",
      accessToken: "short-lived-token",
      workspaceId: "workspace-1",
      platform: "douyin",
      pageVersion: "douyin-creator-v1",
      pageIdentifier: "synthetic-detail-1",
      collectedAt: "2030-01-01T00:00:00Z",
      fetcher,
      idempotencyKey: "idem-1",
    });

    expect(result.task_id).toBe("task-1");
    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://synthetic.example/v1/extension/workspaces/workspace-1/capture-tasks");
    expect(init.headers).toMatchObject({
      Authorization: "Bearer short-lived-token",
      "Idempotency-Key": "idem-1",
    });
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({
      platform: "douyin",
      page_version: "douyin-creator-v1",
      page_identifier: "synthetic-detail-1",
      collected_at: "2030-01-01T00:00:00Z",
      screenshot_data_url: "data:image/png;base64,SYNTHETIC",
    });
    expect(JSON.stringify(body)).not.toContain("cookie");
    expect(JSON.stringify(body)).not.toContain("hidden");
  });

  it("rejects every non-final state and does not send stale previews", async () => {
    const fetcher = vi.fn();
    for (const state of [
      CaptureState.Detected,
      CaptureState.Capturing,
      CaptureState.Redacting,
      CaptureState.Cancelled,
      CaptureState.Failed,
    ]) {
      await expect(
        uploadPreview({
          controller: previewController(state),
          serverOrigin: "https://synthetic.example",
          accessToken: "token",
          workspaceId: "workspace-1",
          platform: "douyin",
          pageVersion: "douyin-creator-v1",
          pageIdentifier: "synthetic-detail-1",
          collectedAt: "2030-01-01T00:00:00Z",
          fetcher,
          idempotencyKey: `idem-${state}`,
        }),
      ).rejects.toThrow("preview_ready");
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("polls with bounded retry and returns an actionable terminal failure", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "running" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "failed", error: "识别失败" }), { status: 200 }));
    const result = await pollCaptureTask({
      serverOrigin: "https://synthetic.example",
      accessToken: "token",
      taskId: "task-1",
      fetcher,
      maxAttempts: 3,
      sleep: vi.fn().mockResolvedValue(undefined),
    });
    expect(result.status).toBe("failed");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
