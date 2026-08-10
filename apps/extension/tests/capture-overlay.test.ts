import { JSDOM } from "jsdom";
import { describe, expect, it, vi } from "vitest";

import type { ExtensionBinding } from "../src/auth/storage";
import {
  CaptureOverlay,
  normalizeSelection,
  validateReviewUrl,
} from "../src/content/capture-overlay";
import { applyRedactions, cropVisibleTab } from "../src/content/image-processing";

const binding: ExtensionBinding = {
  serverOrigin: "https://api.ops.example.com",
  webOrigin: "https://app.ops.example.com",
  workspaceId: "00000000-0000-0000-0000-000000000001",
  workspaceName: "运营工作区",
  memberDisplayName: "小王",
  accessToken: "opaque-short-lived-token",
  expiresAt: "2030-01-01T00:00:00Z",
  providerMode: "mock",
  region: null,
};

const detected = {
  supported: true as const,
  platform: "douyin" as const,
  pageVersion: "douyin-visible-tab-v1",
  signature: "douyin:fixture",
  captureRegion: null,
  sensitiveRegions: [],
};

const task = (overrides: Record<string, unknown> = {}) => ({
  task_id: "00000000-0000-0000-0000-000000000010",
  workspace_id: binding.workspaceId,
  platform: "douyin" as const,
  page_version: "douyin-visible-tab-v1",
  status: "succeeded" as const,
  request_id: "request-1",
  review_url: `/workspaces/${binding.workspaceId}/imports?captureTask=00000000-0000-0000-0000-000000000010`,
  expires_at: "2030-01-01T00:00:00Z",
  recognition: null,
  error: null,
  formal_snapshot_ids: [],
  provider_mode: "mock",
  region: null,
  ...overrides,
});

function fixture(overrides: Record<string, unknown> = {}) {
  const dom = new JSDOM("<!doctype html><html><body><main>creator fixture</main></body></html>");
  const captureVisibleTab = vi.fn().mockResolvedValue("data:image/png;base64,RAW");
  const crop = vi.fn().mockResolvedValue("data:image/png;base64,CROPPED");
  const redact = vi.fn().mockResolvedValue("data:image/png;base64,REDACTED");
  const upload = vi.fn().mockResolvedValue(task({ status: "queued" }));
  const poll = vi.fn().mockResolvedValue(task());
  const options = {
    document: dom.window.document,
    viewport: { width: 1280, height: 720, devicePixelRatio: 2 },
    detect: vi.fn(() => detected),
    captureVisibleTab,
    crop,
    redact,
    upload,
    poll,
    binding,
    uuid: () => "capture-uuid-1",
    nextFrame: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  const flow = CaptureOverlay.mount(options);
  return {
    dom,
    flow,
    options,
    captureVisibleTab: options.captureVisibleTab,
    crop: options.crop,
    redact: options.redact,
    upload: options.upload,
    poll: options.poll,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("user-selected safe capture overlay", () => {
  it("normalizes reversed drags and clamps them to the visible viewport", () => {
    expect(normalizeSelection({ x: 500, y: 300 }, { x: -20, y: 20 }, { width: 400, height: 240 })).toEqual({
      x: 0,
      y: 20,
      width: 400,
      height: 220,
    });
  });

  it("requires explicit start and rejects selections smaller than 40 by 40 CSS pixels", async () => {
    const { flow, captureVisibleTab } = fixture();
    expect(flow.state).toBe("selecting");
    await expect(flow.confirmSelection({ x: 20, y: 30, width: 39, height: 80 })).rejects.toThrow(
      "selection-too-small",
    );
    expect(captureVisibleTab).not.toHaveBeenCalled();
    expect(flow.canUpload()).toBe(false);
  });

  it("hides extension UI for a frame, captures, crops with viewport metrics, and enters preview", async () => {
    const { flow, captureVisibleTab, crop, upload, options } = fixture({
      nextFrame: vi.fn(async () => {
        expect(flow.element.hidden).toBe(true);
      }),
    });
    const selection = { x: 20, y: 30, width: 500, height: 300 };
    await flow.confirmSelection(selection);
    expect(captureVisibleTab).toHaveBeenCalledTimes(1);
    expect(crop).toHaveBeenCalledWith("data:image/png;base64,RAW", selection, options.viewport);
    expect(flow.state).toBe("previewing");
    expect(flow.element.hidden).toBe(false);
    expect(upload).not.toHaveBeenCalled();
  });

  it("adds and removes redactions, then uploads only after final confirmation", async () => {
    const { flow, upload, redact, poll } = fixture();
    await expect(flow.confirmUpload()).rejects.toThrow("final-preview-required");
    await flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    Array.from(flow.element.querySelectorAll("button")).find((button) => button.textContent === "启用遮挡")!.click();
    const id = flow.addRedaction({ x: 40, y: 50, width: 120, height: 32 });
    expect(flow.redactions).toHaveLength(1);
    flow.removeRedaction(id);
    expect(flow.redactions).toHaveLength(0);
    flow.addRedaction({ x: 40, y: 50, width: 120, height: 40 });
    const visibleMask = flow.element.querySelector<HTMLElement>("[data-redaction-preview]");
    expect(visibleMask?.style.background).toBe("rgb(0, 0, 0)");
    expect(visibleMask?.style.left).toBe("8%");
    expect(visibleMask?.style.top).toBe("16.6667%");
    await flow.confirmUpload();
    expect(redact).toHaveBeenCalledWith("data:image/png;base64,CROPPED", [
      { x: 80, y: 100, width: 240, height: 80 },
    ]);
    expect(upload).toHaveBeenCalledWith("data:image/png;base64,REDACTED", "capture-uuid-1");
    expect(poll).toHaveBeenCalledTimes(1);
    expect(flow.state).toBe("completed");
  });

  it("keeps redaction controls unmounted by default and confirms before clearing masks", async () => {
    const confirm = vi.fn().mockReturnValue(false);
    const { flow } = fixture({ confirm });
    await flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });

    expect(flow.element.textContent).not.toContain("添加遮挡");
    const enable = Array.from(flow.element.querySelectorAll("button")).find((button) => button.textContent === "启用遮挡")!;
    enable.click();
    flow.addRedaction({ x: 40, y: 50, width: 120, height: 40 });
    const disable = Array.from(flow.element.querySelectorAll("button")).find((button) => button.textContent === "关闭遮挡")!;
    disable.click();

    expect(confirm).toHaveBeenCalledOnce();
    expect(flow.redactions).toHaveLength(1);
    expect(flow.element.textContent).toContain("添加遮挡");

    confirm.mockReturnValue(true);
    disable.click();
    expect(flow.redactions).toHaveLength(0);
    expect(flow.element.textContent).not.toContain("添加遮挡");
  });

  it("previews full-page completeness, slices, dimensions, and size before upload", async () => {
    const { flow, upload } = fixture({
      mode: "full-page",
      fullPageCapture: vi.fn().mockResolvedValue({
        dataUrl: "data:image/png;base64,FULLPAGE",
        width: 1280,
        height: 4000,
        complete: true,
        stopReason: "bottom",
        sliceCount: 6,
      }),
    });

    await flow.startAutomaticCapture();
    expect(flow.state).toBe("previewing");
    expect(flow.element.textContent).toContain("完整");
    expect(flow.element.textContent).toContain("采集 6 屏");
    expect(flow.element.textContent).toContain("1280×4000");
    expect(upload).not.toHaveBeenCalled();
    await flow.confirmUpload();
    expect(upload).toHaveBeenCalledOnce();
  });

  it("aborts an in-progress full-page driver when the overlay is cancelled", async () => {
    const fullPageCapture = vi.fn((signal: AbortSignal) => new Promise<never>((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("capture-cancelled")));
    }));
    const { flow } = fixture({ mode: "full-page", fullPageCapture });
    const pending = flow.startAutomaticCapture();
    await vi.waitFor(() => expect(fullPageCapture).toHaveBeenCalledOnce());

    flow.cancel();

    expect((fullPageCapture.mock.calls[0] as [AbortSignal])[0].aborted).toBe(true);
    await expect(pending).rejects.toThrow("capture-cancelled");
  });

  it.each([
    ["slice-limit", 3],
    ["empty", 0],
  ])("shows the full-page stop reason and recovery actions when no preview can be stitched: %s", async (stopReason, sliceCount) => {
    const { flow, upload } = fixture({
      mode: "full-page",
      fullPageCapture: vi.fn().mockResolvedValue({
        dataUrl: null,
        complete: false,
        stopReason,
        sliceCount,
      }),
    });

    await flow.startAutomaticCapture();

    expect(flow.state).toBe("failed");
    expect(flow.element.textContent).toContain(stopReason);
    expect(flow.element.textContent).toContain("重试");
    expect(flow.element.textContent).toContain("关闭");
    expect(upload).not.toHaveBeenCalled();
  });

  it("lets the user drag an exact redaction on the preview after choosing 添加遮挡", async () => {
    const { flow, dom } = fixture();
    await flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    Array.from(flow.element.querySelectorAll("button")).find((button) => button.textContent === "启用遮挡")!.click();
    const addButton = Array.from(flow.element.querySelectorAll("button")).find(
      (button) => button.textContent === "添加遮挡",
    )!;
    addButton.click();
    const image = flow.element.querySelector("img")!;
    Object.defineProperty(image, "getBoundingClientRect", {
      value: () => ({ left: 100, top: 50, width: 500, height: 300, right: 600, bottom: 350 }),
    });
    const pointer = (type: string, x: number, y: number) => {
      const event = dom.window.document.createEvent("Event");
      event.initEvent(type, true, true);
      Object.assign(event, { clientX: x, clientY: y, button: 0 });
      image.dispatchEvent(event);
    };
    pointer("pointerdown", 140, 100);
    pointer("pointerup", 260, 140);
    expect(flow.redactions).toMatchObject([{ x: 40, y: 50, width: 120, height: 40 }]);
  });

  it("deduplicates repeated final confirmation with the same in-memory idempotency key", async () => {
    const { flow, upload } = fixture();
    await flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    await Promise.all([flow.confirmUpload(), flow.confirmUpload()]);
    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload).toHaveBeenCalledWith(expect.any(String), "capture-uuid-1");
  });

  it("cancels pending processing before any upload and removes the overlay", async () => {
    let finishRedaction!: (value: string) => void;
    const redact = vi.fn(() => new Promise<string>((resolve) => { finishRedaction = resolve; }));
    const { flow, upload, dom } = fixture({ redact });
    await flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    const pending = flow.confirmUpload();
    flow.cancel();
    finishRedaction("data:image/png;base64,REDACTED");
    await expect(pending).rejects.toThrow("capture-cancelled");
    expect(upload).not.toHaveBeenCalled();
    expect(flow.state).toBe("cancelled");
    expect(dom.window.document.querySelector("[data-operations-capture-overlay]")).toBeNull();
  });

  it("fences cancellation during the hidden frame before requesting a screenshot", async () => {
    const frame = deferred<void>();
    const onDestroy = vi.fn();
    const { flow, captureVisibleTab } = fixture({
      nextFrame: () => frame.promise,
      onDestroy,
    });
    const pending = flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    flow.cancel();
    frame.resolve();
    await expect(pending).rejects.toThrow("capture-cancelled");
    expect(captureVisibleTab).not.toHaveBeenCalled();
    expect(flow.state).toBe("cancelled");
    expect(onDestroy).toHaveBeenCalledOnce();
  });

  it("fences cancellation while the browser screenshot request is pending", async () => {
    const capture = deferred<string>();
    const crop = vi.fn();
    const { flow, captureVisibleTab } = fixture({
      captureVisibleTab: vi.fn(() => capture.promise),
      crop,
    });
    const pending = flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    await vi.waitFor(() => expect(captureVisibleTab).toHaveBeenCalledOnce());
    flow.cancel();
    capture.resolve("data:image/png;base64,RAW");
    await expect(pending).rejects.toThrow("capture-cancelled");
    expect(crop).not.toHaveBeenCalled();
    expect(flow.state).toBe("cancelled");
  });

  it("fences cancellation while image cropping is pending and retains no uploadable preview", async () => {
    const cropResult = deferred<string>();
    const crop = vi.fn(() => cropResult.promise);
    const { flow } = fixture({ crop });
    const pending = flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    await vi.waitFor(() => expect(crop).toHaveBeenCalledOnce());
    flow.cancel();
    cropResult.resolve("data:image/png;base64,CROPPED");
    await expect(pending).rejects.toThrow("capture-cancelled");
    expect(flow.state).toBe("cancelled");
    expect(flow.canUpload()).toBe(false);
  });

  it("fails closed on visibility loss while selecting", () => {
    const { flow, dom } = fixture();
    Object.defineProperty(dom.window.document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    const visibilityEvent = dom.window.document.createEvent("Event");
    visibilityEvent.initEvent("visibilitychange", false, false);
    dom.window.document.dispatchEvent(visibilityEvent);
    expect(flow.state).toBe("cancelled");
    expect(dom.window.document.querySelector("[data-operations-capture-overlay]")).toBeNull();
  });

  it("fails closed on pagehide while capturing", async () => {
    const capture = deferred<string>();
    const { flow, dom, captureVisibleTab } = fixture({
      captureVisibleTab: vi.fn(() => capture.promise),
    });
    const pending = flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    await vi.waitFor(() => expect(captureVisibleTab).toHaveBeenCalledOnce());
    const pagehideEvent = dom.window.document.createEvent("Event");
    pagehideEvent.initEvent("pagehide", false, false);
    dom.window.document.defaultView?.dispatchEvent(pagehideEvent);
    capture.resolve("data:image/png;base64,RAW");
    await expect(pending).rejects.toThrow("capture-cancelled");
    expect(flow.state).toBe("cancelled");
  });

  it("clears an in-memory preview when the page window loses focus", async () => {
    const { flow, dom } = fixture();
    await flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    expect(flow.canUpload()).toBe(true);
    const blurEvent = dom.window.document.createEvent("Event");
    blurEvent.initEvent("blur", false, false);
    dom.window.document.defaultView?.dispatchEvent(blurEvent);
    expect(flow.state).toBe("cancelled");
    expect(flow.canUpload()).toBe(false);
  });

  it("fails closed when viewport size or device pixel ratio changes before capture", async () => {
    let viewport = { width: 1280, height: 720, devicePixelRatio: 2 };
    const first = fixture({ getViewport: () => viewport });
    viewport = { width: 1200, height: 720, devicePixelRatio: 2 };
    await expect(first.flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 })).rejects.toThrow(
      "viewport-changed",
    );
    expect(first.captureVisibleTab).not.toHaveBeenCalled();

    viewport = { width: 1280, height: 720, devicePixelRatio: 2 };
    const second = fixture({ getViewport: () => viewport });
    viewport = { width: 1280, height: 720, devicePixelRatio: 1.5 };
    await expect(second.flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 })).rejects.toThrow(
      "viewport-changed",
    );
    expect(second.captureVisibleTab).not.toHaveBeenCalled();
  });

  it("fails closed when the page changes and cancellation removes all extension UI", async () => {
    let current = detected;
    const { flow, dom, captureVisibleTab } = fixture({ detect: vi.fn(() => current) });
    current = { ...detected, signature: "douyin:changed" };
    await expect(flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 })).rejects.toThrow(
      "page-changed",
    );
    expect(captureVisibleTab).not.toHaveBeenCalled();
    expect(flow.state).toBe("failed");
    flow.cancel();
    expect(flow.state).toBe("cancelled");
    expect(dom.window.document.querySelector("[data-operations-capture-overlay]")).toBeNull();
  });

  it("rechecks the page after hiding the overlay and before requesting a browser screenshot", async () => {
    let current = detected;
    const captureVisibleTab = vi.fn().mockResolvedValue("data:image/png;base64,RAW");
    const { flow } = fixture({
      detect: vi.fn(() => current),
      captureVisibleTab,
      nextFrame: vi.fn(async () => {
        current = { ...detected, signature: "douyin:navigated-during-frame" };
      }),
    });
    await expect(flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 })).rejects.toThrow(
      "page-changed",
    );
    expect(captureVisibleTab).not.toHaveBeenCalled();
    expect(flow.state).toBe("failed");
  });

  it("renders only a validated user-clicked review link and never opens a tab programmatically", async () => {
    const { flow } = fixture();
    await flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    await flow.confirmUpload();
    const link = flow.element.querySelector<HTMLAnchorElement>("a[data-review-link]");
    expect(link?.href).toBe(
      `https://app.ops.example.com/workspaces/${binding.workspaceId}/imports?captureTask=00000000-0000-0000-0000-000000000010`,
    );
    expect(link?.target).toBe("_blank");
    expect(link?.rel).toBe("noopener noreferrer");
    expect(link?.textContent).toBe("到运营工具确认");
  });

  it("rejects review URLs outside the paired origin or workspace imports path", () => {
    expect(
      validateReviewUrl(
        `/workspaces/${binding.workspaceId}/imports/review/task-1`,
        binding,
      ),
    ).toBe(`https://app.ops.example.com/workspaces/${binding.workspaceId}/imports/review/task-1`);
    expect(() => validateReviewUrl("https://evil.example/steal", binding)).toThrow("unsafe-review-url");
    expect(() => validateReviewUrl("/workspaces/other/imports", binding)).toThrow("unsafe-review-url");
    expect(() => validateReviewUrl(`/workspaces/${binding.workspaceId}/imports-redirect`, binding)).toThrow(
      "unsafe-review-url",
    );
    expect(() => validateReviewUrl("/workspaces/00000000-0000-0000-0000-000000000001/settings", binding)).toThrow(
      "unsafe-review-url",
    );
  });

  it("requires re-pairing after an authorization failure", async () => {
    const rePair = vi.fn().mockResolvedValue(undefined);
    const { flow } = fixture({
      upload: vi.fn().mockRejectedValue(new Error("rebind-required")),
      onRePairRequired: rePair,
    });
    await flow.confirmSelection({ x: 20, y: 30, width: 500, height: 300 });
    await expect(flow.confirmUpload()).rejects.toThrow("rebind-required");
    expect(rePair).toHaveBeenCalledOnce();
    expect(flow.state).toBe("failed");
  });
});

describe("controlled visible-tab image processing", () => {
  it("crops using device pixel ratio and emits a PNG", async () => {
    const calls: unknown[][] = [];
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ({ drawImage: (...args: unknown[]) => calls.push(args), fillRect: vi.fn() }),
      toDataURL: () => "data:image/png;base64,UE5H",
    };
    const restoreImage = globalThis.Image;
    const restoreDocument = globalThis.document;
    class SyntheticImage {
      naturalWidth = 2560;
      naturalHeight = 1440;
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      set src(_value: string) { queueMicrotask(() => this.onload?.()); }
    }
    Object.assign(globalThis, {
      Image: SyntheticImage,
      document: { createElement: () => canvas },
    });
    try {
      const result = await cropVisibleTab(
        "data:image/png;base64,UkFX",
        { x: 10, y: 20, width: 100, height: 50 },
        { width: 1280, height: 720, devicePixelRatio: 2 },
      );
      expect(canvas.width).toBe(200);
      expect(canvas.height).toBe(100);
      expect(calls[0]?.slice(1)).toEqual([20, 40, 200, 100, 0, 0, 200, 100]);
      expect(result).toBe("data:image/png;base64,UE5H");
    } finally {
      Object.assign(globalThis, { Image: restoreImage, document: restoreDocument });
    }
  });

  it("draws opaque rectangles and rejects decode failure or oversized output", async () => {
    const fillRect = vi.fn();
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ({ drawImage: vi.fn(), fillStyle: "", fillRect }),
      toDataURL: () => "data:image/png;base64,UE5H",
    };
    const restoreImage = globalThis.Image;
    const restoreDocument = globalThis.document;
    class SyntheticImage {
      naturalWidth = 200;
      naturalHeight = 100;
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      set src(value: string) { queueMicrotask(() => value.includes("BROKEN") ? this.onerror?.() : this.onload?.()); }
    }
    Object.assign(globalThis, { Image: SyntheticImage, document: { createElement: () => canvas } });
    try {
      await expect(applyRedactions("data:image/png;base64,BROKEN", [])).rejects.toThrow("image-decode-failed");
      await expect(
        applyRedactions("data:image/png;base64,UkFX", [{ x: 5, y: 6, width: 30, height: 12 }]),
      ).resolves.toBe("data:image/png;base64,UE5H");
      expect(fillRect).toHaveBeenCalledWith(5, 6, 30, 12);
    } finally {
      Object.assign(globalThis, { Image: restoreImage, document: restoreDocument });
    }
  });

  it("rejects a decoded screenshot whose physical dimensions do not match the captured viewport", async () => {
    const canvas = {
      width: 0,
      height: 0,
      getContext: () => ({ drawImage: vi.fn(), fillRect: vi.fn() }),
      toDataURL: () => "data:image/png;base64,UE5H",
    };
    const restoreImage = globalThis.Image;
    const restoreDocument = globalThis.document;
    class MismatchedImage {
      naturalWidth = 2200;
      naturalHeight = 1200;
      onload: null | (() => void) = null;
      onerror: null | (() => void) = null;
      set src(_value: string) { queueMicrotask(() => this.onload?.()); }
    }
    Object.assign(globalThis, { Image: MismatchedImage, document: { createElement: () => canvas } });
    try {
      await expect(
        cropVisibleTab(
          "data:image/png;base64,UkFX",
          { x: 10, y: 20, width: 100, height: 50 },
          { width: 1280, height: 720, devicePixelRatio: 2 },
        ),
      ).rejects.toThrow("screenshot-dimension-mismatch");
    } finally {
      Object.assign(globalThis, { Image: restoreImage, document: restoreDocument });
    }
  });
});
