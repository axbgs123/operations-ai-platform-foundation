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
      platform: "douyin",
      pageVersion: "douyin-creator-v1",
      fetcher,
      maxAttempts: 3,
      sleep: vi.fn().mockResolvedValue(undefined),
    });
    expect(result.status).toBe("failed");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("keeps the capture scope in the local timeout result", async () => {
    const result = await pollCaptureTask({
      serverOrigin: "https://synthetic.example",
      accessToken: "token",
      taskId: "task-timeout",
      platform: "xiaohongshu",
      pageVersion: "xiaohongshu-creator-v1",
      fetcher: vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "running" }), { status: 200 }),
      ),
      maxAttempts: 1,
      sleep: vi.fn().mockResolvedValue(undefined),
    });

    expect(result).toMatchObject({
      status: "failed",
      platform: "xiaohongshu",
      page_version: "xiaohongshu-creator-v1",
    });
  });

  it("clears the binding and requires re-pairing when polling loses authorization", async () => {
    const onRebindRequired = vi.fn().mockResolvedValue(undefined);
    await expect(
      pollCaptureTask({
        serverOrigin: "https://synthetic.example",
        accessToken: "expired-token",
        taskId: "task-expired",
        platform: "douyin",
        pageVersion: "douyin-visible-tab-v1",
        fetcher: vi.fn().mockResolvedValue(new Response(null, { status: 401 })),
        onRebindRequired,
        sleep: vi.fn(),
      }),
    ).rejects.toThrow("rebind-required");
    expect(onRebindRequired).toHaveBeenCalledOnce();
  });

  it("retries a lost POST response with the same idempotency key", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("response lost"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ task_id: "task-recovered", status: "queued" }), { status: 202 }),
      );
    const result = await uploadPreview({
      controller: previewController(CaptureState.PreviewReady),
      serverOrigin: "https://synthetic.example",
      accessToken: "token",
      workspaceId: "workspace-1",
      platform: "douyin",
      pageVersion: "douyin-visible-tab-v1",
      pageIdentifier: "douyin:fixture",
      collectedAt: "2030-01-01T00:00:00Z",
      fetcher,
      idempotencyKey: "stable-capture-id",
      requestMaxAttempts: 2,
      retrySleep: vi.fn().mockResolvedValue(undefined),
    });
    expect(result.task_id).toBe("task-recovered");
    expect(fetcher).toHaveBeenCalledTimes(2);
    for (const call of fetcher.mock.calls) {
      expect((call[1] as RequestInit).headers).toMatchObject({
        "Idempotency-Key": "stable-capture-id",
      });
    }
  });

  it("retries eligible 429 and 5xx responses, then succeeds within the bound", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 429 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ task_id: "task-after-rate-limit", status: "queued" }), { status: 202 }),
      );
    await expect(
      uploadPreview({
        controller: previewController(CaptureState.PreviewReady),
        serverOrigin: "https://synthetic.example",
        accessToken: "token",
        workspaceId: "workspace-1",
        platform: "douyin",
        pageVersion: "douyin-visible-tab-v1",
        pageIdentifier: "douyin:fixture",
        collectedAt: "2030-01-01T00:00:00Z",
        fetcher,
        idempotencyKey: "idem-rate-limit",
        requestMaxAttempts: 2,
        retrySleep: vi.fn().mockResolvedValue(undefined),
      }),
    ).resolves.toMatchObject({ task_id: "task-after-rate-limit" });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("does not retry unsafe 4xx and clears binding once on 401 or 403", async () => {
    for (const status of [400, 401, 403]) {
      const fetcher = vi.fn().mockResolvedValue(new Response(null, { status }));
      const onRebindRequired = vi.fn().mockResolvedValue(undefined);
      await expect(
        uploadPreview({
          controller: previewController(CaptureState.PreviewReady),
          serverOrigin: "https://synthetic.example",
          accessToken: "token",
          workspaceId: "workspace-1",
          platform: "douyin",
          pageVersion: "douyin-visible-tab-v1",
          pageIdentifier: "douyin:fixture",
          collectedAt: "2030-01-01T00:00:00Z",
          fetcher,
          idempotencyKey: `idem-${status}`,
          requestMaxAttempts: 3,
          retrySleep: vi.fn().mockResolvedValue(undefined),
          onRebindRequired,
        }),
      ).rejects.toThrow(status === 400 ? "capture upload failed" : "rebind-required");
      expect(fetcher).toHaveBeenCalledOnce();
      expect(onRebindRequired).toHaveBeenCalledTimes(status === 400 ? 0 : 1);
    }
  });

  it("stops after bounded transient exhaustion", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("offline"));
    await expect(
      uploadPreview({
        controller: previewController(CaptureState.PreviewReady),
        serverOrigin: "https://synthetic.example",
        accessToken: "token",
        workspaceId: "workspace-1",
        platform: "douyin",
        pageVersion: "douyin-visible-tab-v1",
        pageIdentifier: "douyin:fixture",
        collectedAt: "2030-01-01T00:00:00Z",
        fetcher,
        idempotencyKey: "idem-exhausted",
        requestMaxAttempts: 2,
        retrySleep: vi.fn().mockResolvedValue(undefined),
      }),
    ).rejects.toThrow("capture request failed");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("aborts a hung upload request at the per-attempt timeout", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn((_url: string | URL | Request, init?: RequestInit) => {
        if (!init?.signal) return Promise.reject(new Error("missing abort signal"));
        return new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        });
      });
      const pending = uploadPreview({
        controller: previewController(CaptureState.PreviewReady),
        serverOrigin: "https://synthetic.example",
        accessToken: "token",
        workspaceId: "workspace-1",
        platform: "douyin",
        pageVersion: "douyin-visible-tab-v1",
        pageIdentifier: "douyin:fixture",
        collectedAt: "2030-01-01T00:00:00Z",
        fetcher,
        idempotencyKey: "idem-timeout",
        requestMaxAttempts: 1,
        requestTimeoutMs: 50,
      });
      const assertion = expect(pending).rejects.toThrow("capture request timeout");
      await vi.advanceTimersByTimeAsync(50);
      await assertion;
      expect(fetcher).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the timeout active while reading the successful response body", async () => {
    vi.useFakeTimers();
    try {
      let requestSignal: AbortSignal | undefined;
      let finishBody!: (value: object) => void;
      const fetcher = vi.fn((_url: string | URL | Request, init?: RequestInit) => {
        requestSignal = init?.signal ?? undefined;
        return Promise.resolve({
          ok: true,
          status: 202,
          json: () => new Promise<object>((resolve, reject) => {
            finishBody = resolve;
            requestSignal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          }),
        } as Response);
      });
      const pending = uploadPreview({
        controller: previewController(CaptureState.PreviewReady),
        serverOrigin: "https://synthetic.example",
        accessToken: "token",
        workspaceId: "workspace-1",
        platform: "douyin",
        pageVersion: "douyin-visible-tab-v1",
        pageIdentifier: "douyin:fixture",
        collectedAt: "2030-01-01T00:00:00Z",
        fetcher,
        idempotencyKey: "idem-body-timeout",
        requestMaxAttempts: 1,
        requestTimeoutMs: 50,
      });
      const outcome = pending.then(
        (value) => ({ value, error: null as Error | null }),
        (error: Error) => ({ value: null, error }),
      );
      await vi.advanceTimersByTimeAsync(50);
      if (!requestSignal?.aborted) {
        finishBody({ task_id: "unexpected", status: "queued" });
      }
      const settled = await outcome;
      expect(requestSignal?.aborted).toBe(true);
      expect(settled.value).toBeNull();
      expect(settled.error?.message).toBe("capture request timeout");
    } finally {
      vi.useRealTimers();
    }
  });

  it("retries transient polling requests but keeps the overall status attempt bound", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("temporary network loss"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "running" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "succeeded" }), { status: 200 }));
    const result = await pollCaptureTask({
      serverOrigin: "https://synthetic.example",
      accessToken: "token",
      taskId: "task-retry",
      platform: "douyin",
      pageVersion: "douyin-visible-tab-v1",
      fetcher,
      maxAttempts: 2,
      requestMaxAttempts: 2,
      sleep: vi.fn().mockResolvedValue(undefined),
    });
    expect(result.status).toBe("succeeded");
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
});
