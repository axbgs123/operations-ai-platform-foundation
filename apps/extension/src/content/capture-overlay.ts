import type { ExtensionBinding } from "../auth/storage";
import type { CaptureTaskRead } from "../capture/task-status";
import type { PageDetection, Rect } from "./page-adapters/base";
import type { ViewportMetrics } from "./image-processing";
import type { CaptureMode } from "../runtime/messages";

type Point = { x: number; y: number };
type OverlayState =
  | "selecting"
  | "capturing"
  | "previewing"
  | "uploading"
  | "completed"
  | "failed"
  | "cancelled";

type Redaction = Rect & { id: string };
export type FullPagePreview = {
  dataUrl: string;
  width: number;
  height: number;
  complete: boolean;
  stopReason: string;
  sliceCount: number;
};
export type CaptureBinding = Pick<
  ExtensionBinding,
  "serverOrigin" | "webOrigin" | "workspaceId" | "accessToken" | "expiresAt" | "providerMode"
>;

export type CaptureOverlayOptions = {
  document: Document;
  viewport: ViewportMetrics;
  detect(): PageDetection;
  captureVisibleTab(): Promise<string>;
  crop(dataUrl: string, selection: Rect, viewport: ViewportMetrics): Promise<string>;
  redact(dataUrl: string, redactions: Rect[]): Promise<string>;
  upload(dataUrl: string, idempotencyKey: string): Promise<CaptureTaskRead>;
  poll(task: CaptureTaskRead): Promise<CaptureTaskRead>;
  binding: CaptureBinding;
  getViewport?: () => ViewportMetrics;
  uuid?: () => string;
  nextFrame?: () => Promise<void>;
  onRePairRequired?: () => Promise<void>;
  onDestroy?: (overlay: CaptureOverlay) => void;
  confirm?(message: string): boolean;
  mode?: CaptureMode;
  fullPageCapture?(): Promise<FullPagePreview>;
};

const clamp = (value: number, minimum: number, maximum: number) =>
  Math.max(minimum, Math.min(value, maximum));

export function normalizeSelection(start: Point, end: Point, viewport: Pick<ViewportMetrics, "width" | "height">): Rect {
  const startX = clamp(start.x, 0, viewport.width);
  const startY = clamp(start.y, 0, viewport.height);
  const endX = clamp(end.x, 0, viewport.width);
  const endY = clamp(end.y, 0, viewport.height);
  return {
    x: Math.min(startX, endX),
    y: Math.min(startY, endY),
    width: Math.abs(endX - startX),
    height: Math.abs(endY - startY),
  };
}

export function validateReviewUrl(reviewUrl: string, binding: CaptureBinding): string {
  let result: URL;
  let expectedOrigin: string;
  try {
    result = new URL(reviewUrl, binding.webOrigin);
    expectedOrigin = new URL(binding.webOrigin).origin;
  } catch {
    throw new Error("unsafe-review-url");
  }
  const requiredPath = `/workspaces/${binding.workspaceId}/imports`;
  if (
    result.origin !== expectedOrigin ||
    result.username !== "" ||
    result.password !== "" ||
    (result.pathname !== requiredPath && !result.pathname.startsWith(`${requiredPath}/`))
  ) {
    throw new Error("unsafe-review-url");
  }
  return result.toString();
}

const defaultNextFrame = () =>
  new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));

export class CaptureOverlay {
  state: OverlayState = "selecting";
  readonly element: HTMLDivElement;
  readonly redactions: Redaction[] = [];

  private readonly initialDetection: PageDetection;
  private readonly initialViewport: ViewportMetrics;
  private readonly uuid: () => string;
  private readonly nextFrame: () => Promise<void>;
  private selection: Rect | null = null;
  private previewDataUrl: string | null = null;
  private captureId: string | null = null;
  private uploadPromise: Promise<void> | null = null;
  private reviewUrl: string | null = null;
  private dragStart: Point | null = null;
  private redactionDragStart: Point | null = null;
  private addingRedaction = false;
  private redactionEnabled = false;
  private redactionSequence = 0;
  private destroyed = false;
  private fullPagePreview: FullPagePreview | null = null;

  private constructor(private readonly options: CaptureOverlayOptions) {
    this.initialDetection = options.detect();
    this.initialViewport = { ...options.viewport };
    if (!this.initialDetection.supported || !this.initialDetection.platform) {
      throw new Error("unsupported-page");
    }
    this.uuid = options.uuid ?? (() => crypto.randomUUID());
    this.nextFrame = options.nextFrame ?? defaultNextFrame;
    this.element = options.document.createElement("div");
    this.element.dataset.operationsCaptureOverlay = "true";
    this.element.setAttribute("role", "dialog");
    this.element.setAttribute("aria-modal", "true");
    Object.assign(this.element.style, {
      position: "fixed",
      inset: "0",
      zIndex: "2147483647",
      background: "rgba(12, 20, 36, 0.72)",
      color: "#172033",
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      cursor: "crosshair",
    });
    this.element.addEventListener("pointerdown", this.onPointerDown);
    this.element.addEventListener("pointerup", this.onPointerUp);
    this.options.document.addEventListener("keydown", this.onKeyDown);
    this.options.document.addEventListener("visibilitychange", this.onVisibilityChange);
    this.options.document.defaultView?.addEventListener("pagehide", this.onLifecycleLoss);
    this.options.document.defaultView?.addEventListener("blur", this.onLifecycleLoss);
    this.options.document.body.append(this.element);
    this.render();
  }

  static mount(options: CaptureOverlayOptions): CaptureOverlay {
    return new CaptureOverlay(options);
  }

  canUpload(): boolean {
    return this.state === "previewing" && this.previewDataUrl !== null;
  }

  captureMetadata(): {
    capture_mode: CaptureMode;
    complete: boolean;
    stop_reason: string;
    slice_count: number;
  } {
    const mode = this.options.mode ?? "region";
    if (this.fullPagePreview) {
      return {
        capture_mode: mode,
        complete: this.fullPagePreview.complete,
        stop_reason: this.fullPagePreview.stopReason,
        slice_count: this.fullPagePreview.sliceCount,
      };
    }
    return {
      capture_mode: mode,
      complete: true,
      stop_reason: mode === "visible" ? "visible" : "region",
      slice_count: 1,
    };
  }

  async startAutomaticCapture(): Promise<void> {
    const mode = this.options.mode ?? "region";
    if (mode === "region") return;
    if (mode === "visible") {
      return this.confirmSelection({
        x: 0,
        y: 0,
        width: this.initialViewport.width,
        height: this.initialViewport.height,
      });
    }
    if (!this.options.fullPageCapture) throw new Error("full-page-capture-unavailable");
    if (this.state !== "selecting") throw new Error("capture-not-available");
    this.captureId = this.uuid();
    this.state = "capturing";
    this.element.hidden = true;
    try {
      await this.nextFrame();
      this.throwIfCancelled();
      if (!this.pageStillMatches()) throw new Error("page-changed");
      const preview = await this.options.fullPageCapture();
      this.throwIfCancelled();
      if (!preview.dataUrl || preview.width <= 0 || preview.height <= 0 || preview.sliceCount <= 0) {
        throw new Error("capture-failed");
      }
      this.fullPagePreview = preview;
      this.previewDataUrl = preview.dataUrl;
      const ratio = this.initialViewport.devicePixelRatio;
      this.selection = { x: 0, y: 0, width: preview.width / ratio, height: preview.height / ratio };
      this.state = "previewing";
    } catch (error) {
      if (this.isCancelled() || (error instanceof Error && error.message === "capture-cancelled")) {
        if (!this.destroyed) this.state = "cancelled";
        throw new Error("capture-cancelled");
      }
      this.state = "failed";
      throw error;
    } finally {
      if (!this.destroyed) {
        this.element.hidden = false;
        this.render();
      }
    }
  }

  async confirmSelection(selection: Rect): Promise<void> {
    if (this.state !== "selecting") throw new Error("selection-not-available");
    const normalized = normalizeSelection(
      { x: selection.x, y: selection.y },
      { x: selection.x + selection.width, y: selection.y + selection.height },
      this.options.viewport,
    );
    if (normalized.width < 40 || normalized.height < 40) throw new Error("selection-too-small");
    if (!this.pageStillMatches()) {
      this.state = "failed";
      this.renderMessage("页面已经变化，请重新开始采集。");
      throw new Error("page-changed");
    }
    this.selection = normalized;
    this.captureId = this.uuid();
    this.state = "capturing";
    this.element.hidden = true;
    let failureMessage: string | null = null;
    try {
      await this.nextFrame();
      this.throwIfCancelled();
      if (!this.pageStillMatches()) throw new Error("page-changed");
      const captureViewport = this.readStableViewport();
      const fullImage = await this.options.captureVisibleTab();
      this.throwIfCancelled();
      this.readStableViewport();
      const cropped = await this.options.crop(fullImage, normalized, captureViewport);
      this.throwIfCancelled();
      this.readStableViewport();
      this.previewDataUrl = cropped;
      this.state = "previewing";
    } catch (error) {
      if (this.isCancelled() || (error instanceof Error && error.message === "capture-cancelled")) {
        if (!this.destroyed) this.state = "cancelled";
        throw new Error("capture-cancelled");
      }
      this.state = "failed";
      failureMessage = error instanceof Error && error.message === "page-changed"
        ? "页面已经变化，请重新开始采集。"
        : "截图失败，请确认当前页面仍受支持后重试。";
      throw error;
    } finally {
      if (!this.destroyed) {
        this.element.hidden = false;
        if (failureMessage) this.renderMessage(failureMessage);
        else this.render();
      }
    }
  }

  addRedaction(region: Rect): string {
    if (this.state !== "previewing" || !this.selection) throw new Error("final-preview-required");
    const normalized = normalizeSelection(
      { x: region.x, y: region.y },
      { x: region.x + region.width, y: region.y + region.height },
      { width: this.selection.width, height: this.selection.height },
    );
    if (normalized.width <= 0 || normalized.height <= 0) throw new Error("invalid-redaction-region");
    const id = `redaction-${++this.redactionSequence}`;
    this.redactions.push({ ...normalized, id });
    this.render();
    return id;
  }

  removeRedaction(id: string): void {
    const index = this.redactions.findIndex((region) => region.id === id);
    if (index >= 0) this.redactions.splice(index, 1);
    this.render();
  }

  toggleRedaction(): void {
    if (this.redactionEnabled) {
      const approve = this.options.confirm ?? ((message: string) => this.options.document.defaultView?.confirm(message) ?? false);
      if (this.redactions.length > 0 && !approve("关闭遮挡将清空已有遮挡，是否继续？")) {
        return;
      }
      this.redactions.splice(0);
      this.addingRedaction = false;
      this.redactionEnabled = false;
    } else {
      this.redactionEnabled = true;
    }
    this.render();
  }

  reselect(): void {
    if (this.state === "uploading") return;
    this.selection = null;
    this.previewDataUrl = null;
    this.fullPagePreview = null;
    this.captureId = null;
    this.uploadPromise = null;
    this.reviewUrl = null;
    this.addingRedaction = false;
    this.redactionEnabled = false;
    this.redactionDragStart = null;
    this.redactions.splice(0);
    this.state = "selecting";
    this.render();
  }

  confirmUpload(): Promise<void> {
    if (this.uploadPromise) return this.uploadPromise;
    if (!this.canUpload() || !this.previewDataUrl || !this.captureId) {
      return Promise.reject(new Error("final-preview-required"));
    }
    this.uploadPromise = this.performUpload();
    return this.uploadPromise;
  }

  cancel(): void {
    this.state = "cancelled";
    this.destroy();
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.element.removeEventListener("pointerdown", this.onPointerDown);
    this.element.removeEventListener("pointerup", this.onPointerUp);
    this.options.document.removeEventListener("keydown", this.onKeyDown);
    this.options.document.removeEventListener("visibilitychange", this.onVisibilityChange);
    this.options.document.defaultView?.removeEventListener("pagehide", this.onLifecycleLoss);
    this.options.document.defaultView?.removeEventListener("blur", this.onLifecycleLoss);
    this.element.remove();
    this.previewDataUrl = null;
    this.fullPagePreview = null;
    this.selection = null;
    this.redactions.splice(0);
    this.options.onDestroy?.(this);
  }

  private async performUpload(): Promise<void> {
    this.state = "uploading";
    this.render();
    try {
      const ratio = this.options.viewport.devicePixelRatio;
      const scaledRedactions = this.redactions.map(({ x, y, width, height }) => ({
        x: x * ratio,
        y: y * ratio,
        width: width * ratio,
        height: height * ratio,
      }));
      const finalImage = await this.options.redact(this.previewDataUrl!, scaledRedactions);
      if (this.isCancelled()) throw new Error("capture-cancelled");
      let task = await this.options.upload(finalImage, this.captureId!);
      if (this.isCancelled()) throw new Error("capture-cancelled");
      if (!['succeeded', 'failed', 'cancelled'].includes(task.status)) {
        task = await this.options.poll(task);
      }
      if (this.isCancelled()) throw new Error("capture-cancelled");
      if (task.status !== "succeeded") throw new Error(task.error || "recognition-failed");
      this.reviewUrl = validateReviewUrl(task.review_url, this.options.binding);
      this.state = "completed";
      this.render();
    } catch (error) {
      if (
        (error instanceof Error && error.message === "capture-cancelled") ||
        this.isCancelled()
      ) {
        this.state = "cancelled";
        throw error;
      }
      this.state = "failed";
      if (error instanceof Error && error.message === "rebind-required") {
        await this.options.onRePairRequired?.();
      }
      this.renderMessage(
        error instanceof Error && error.message === "rebind-required"
          ? "连接已失效，请回到扩展重新连接。"
          : "采集未完成，请检查页面后重试。",
      );
      throw error;
    }
  }

  private isCancelled(): boolean {
    return this.destroyed || (this.state as OverlayState) === "cancelled";
  }

  private pageStillMatches(): boolean {
    const current = this.options.detect();
    return Boolean(
      current.supported &&
      current.platform === this.initialDetection.platform &&
      current.pageVersion === this.initialDetection.pageVersion &&
      current.signature === this.initialDetection.signature,
    );
  }

  private throwIfCancelled(): void {
    if (this.isCancelled()) throw new Error("capture-cancelled");
  }

  private readStableViewport(): ViewportMetrics {
    const current = this.options.getViewport?.() ?? this.options.viewport;
    const dprChanged = Math.abs(current.devicePixelRatio - this.initialViewport.devicePixelRatio) > 0.001;
    if (
      current.width !== this.initialViewport.width ||
      current.height !== this.initialViewport.height ||
      dprChanged
    ) {
      throw new Error("viewport-changed");
    }
    return { ...current };
  }

  private render(): void {
    if (this.destroyed) return;
    this.element.replaceChildren();
    const panel = this.options.document.createElement("section");
    Object.assign(panel.style, {
      position: "absolute",
      top: "24px",
      left: "50%",
      transform: "translateX(-50%)",
      width: "min(640px, calc(100vw - 32px))",
      padding: "16px",
      borderRadius: "12px",
      background: "#ffffff",
      boxShadow: "0 16px 48px rgba(0,0,0,.28)",
      cursor: "default",
    });
    const title = this.options.document.createElement("strong");
    title.textContent = this.state === "selecting" ? "拖动选择要采集的区域" : "确认截图和遮挡";
    panel.append(title);

    const details = this.options.document.createElement("p");
    const platform = this.initialDetection.platform === "douyin" ? "抖音" : "小红书";
    const size = this.fullPagePreview
      ? ` · ${this.fullPagePreview.width}×${this.fullPagePreview.height}`
      : this.selection ? ` · ${Math.round(this.selection.width)}×${Math.round(this.selection.height)}` : "";
    const fullPageDetails = this.fullPagePreview
      ? ` · ${this.fullPagePreview.complete ? "完整" : "部分"} · ${this.fullPagePreview.sliceCount} 张 · ${Math.ceil((this.fullPagePreview.dataUrl.length * 3) / 4 / 1024)} KB`
      : "";
    details.textContent = `${platform} · ${this.options.binding.webOrigin}${size}${fullPageDetails} · 遮挡 ${this.redactions.length} 处`;
    panel.append(details);

    const disclosure = this.options.document.createElement("p");
    disclosure.textContent = this.options.binding.providerMode === "mock"
      ? "当前使用 Mock 识别，不会调用外部付费模型；结果仍需人工确认。"
      : "截图将发送到已连接服务器进行识别；结果仍需人工确认。";
    panel.append(disclosure);

    if (this.previewDataUrl && this.state !== "selecting") {
      const preview = this.options.document.createElement("div");
      Object.assign(preview.style, {
        position: "relative",
        display: "inline-block",
        maxWidth: "100%",
      });
      const image = this.options.document.createElement("img");
      image.src = this.previewDataUrl;
      image.alt = "待确认的采集截图";
      image.style.maxWidth = "100%";
      image.style.maxHeight = "45vh";
      if (this.addingRedaction) {
        image.style.cursor = "crosshair";
        image.addEventListener("pointerdown", this.onRedactionPointerDown);
        image.addEventListener("pointerup", this.onRedactionPointerUp);
      }
      preview.append(image);
      if (this.selection && this.redactionEnabled) {
        for (const region of this.redactions) {
          const mask = this.options.document.createElement("span");
          mask.dataset.redactionPreview = region.id;
          const percent = (value: number, total: number) =>
            `${Number(((value / total) * 100).toFixed(4))}%`;
          Object.assign(mask.style, {
            position: "absolute",
            left: percent(region.x, this.selection.width),
            top: percent(region.y, this.selection.height),
            width: percent(region.width, this.selection.width),
            height: percent(region.height, this.selection.height),
            background: "#000000",
            pointerEvents: "none",
          });
          preview.append(mask);
        }
      }
      panel.append(preview);
      if (this.redactionEnabled) {
        for (const region of this.redactions) {
          const row = this.options.document.createElement("div");
          row.textContent = `遮挡：${Math.round(region.x)}, ${Math.round(region.y)} · ${Math.round(region.width)}×${Math.round(region.height)}`;
          const remove = this.button("删除", () => this.removeRedaction(region.id));
          row.append(remove);
          panel.append(row);
        }
      }
    }

    if (this.state === "previewing") {
      if (this.addingRedaction) {
        const instruction = this.options.document.createElement("p");
        instruction.textContent = "请在截图上拖动，框出需要遮挡的位置。";
        panel.append(instruction);
      }
      panel.append(
        this.button("重新选择", () => this.reselect()),
        this.button(this.redactionEnabled ? "关闭遮挡" : "启用遮挡", () => this.toggleRedaction()),
      );
      if (this.redactionEnabled) {
        panel.append(this.button("添加遮挡", () => {
          this.addingRedaction = true;
          this.render();
        }));
      }
      panel.append(
        this.button("取消", () => this.cancel()),
        this.button("确认上传", () => void this.confirmUpload()),
      );
    } else if (this.state === "selecting") {
      panel.append(this.button("取消", () => this.cancel()));
    } else if (this.state === "uploading") {
      const status = this.options.document.createElement("p");
      status.textContent = "正在上传并等待识别…";
      panel.append(status);
    } else if (this.state === "completed" && this.reviewUrl) {
      const link = this.options.document.createElement("a");
      link.dataset.reviewLink = "true";
      link.href = this.reviewUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "到运营工具确认";
      panel.append(link, this.button("关闭", () => this.cancel()));
    }
    this.element.append(panel);
  }

  private renderMessage(message: string): void {
    if (this.destroyed) return;
    this.element.replaceChildren();
    const panel = this.options.document.createElement("section");
    panel.style.cssText = "margin:24px auto;padding:16px;max-width:560px;background:#fff;border-radius:12px;cursor:default";
    const text = this.options.document.createElement("p");
    text.textContent = message;
    panel.append(text, this.button("关闭", () => this.cancel()));
    this.element.append(panel);
  }

  private button(label: string, action: () => void): HTMLButtonElement {
    const button = this.options.document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.style.margin = "8px 8px 0 0";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      action();
    });
    return button;
  }

  private readonly onPointerDown = (event: PointerEvent) => {
    if (this.state !== "selecting" || event.button !== 0 || event.target !== this.element) return;
    this.dragStart = { x: event.clientX, y: event.clientY };
    event.preventDefault();
  };

  private readonly onPointerUp = (event: PointerEvent) => {
    if (this.state !== "selecting" || !this.dragStart || event.target !== this.element) return;
    const selection = normalizeSelection(
      this.dragStart,
      { x: event.clientX, y: event.clientY },
      this.options.viewport,
    );
    this.dragStart = null;
    void this.confirmSelection(selection).catch(() => undefined);
  };

  private readonly onRedactionPointerDown = (event: PointerEvent) => {
    if (!this.addingRedaction || event.button !== 0) return;
    const image = event.currentTarget as HTMLImageElement;
    const bounds = image.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0 || !this.selection) return;
    this.redactionDragStart = {
      x: ((event.clientX - bounds.left) / bounds.width) * this.selection.width,
      y: ((event.clientY - bounds.top) / bounds.height) * this.selection.height,
    };
    event.preventDefault();
  };

  private readonly onRedactionPointerUp = (event: PointerEvent) => {
    if (!this.addingRedaction || !this.redactionDragStart || !this.selection) return;
    const image = event.currentTarget as HTMLImageElement;
    const bounds = image.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    const end = {
      x: ((event.clientX - bounds.left) / bounds.width) * this.selection.width,
      y: ((event.clientY - bounds.top) / bounds.height) * this.selection.height,
    };
    const region = normalizeSelection(this.redactionDragStart, end, {
      width: this.selection.width,
      height: this.selection.height,
    });
    this.redactionDragStart = null;
    this.addingRedaction = false;
    if (region.width > 0 && region.height > 0) this.addRedaction(region);
    else this.render();
  };

  private readonly onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") this.cancel();
  };

  private readonly onVisibilityChange = () => {
    if (this.options.document.visibilityState === "hidden") this.cancel();
  };

  private readonly onLifecycleLoss = () => {
    this.cancel();
  };
}
