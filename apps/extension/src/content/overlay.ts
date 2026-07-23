import type { PageDetection, Rect } from "./page-adapters/base";
import type { PreviewImage } from "./redaction";

export enum CaptureState {
  Unsupported = "unsupported",
  Detected = "detected",
  PreviewRequired = "preview_required",
  Capturing = "capturing",
  Redacting = "redacting",
  PreviewReady = "preview_ready",
  Cancelled = "cancelled",
  Failed = "failed",
}

type CaptureFn = () => Promise<string>;
type DetectionFn = () => PageDetection;

const sameRegions = (a: PageDetection, b: PageDetection) =>
  JSON.stringify(a.sensitiveRegions) === JSON.stringify(b.sensitiveRegions);

export class SafeCaptureController {
  state: CaptureState;
  preview: PreviewImage | null = null;
  private detection: PageDetection | null = null;
  private allowUnredact = false;

  constructor(
    private readonly detect: DetectionFn,
    private readonly captureVisibleTab: CaptureFn,
  ) {
    this.state = detect().supported ? CaptureState.Detected : CaptureState.Unsupported;
  }

  async beginPreview(): Promise<void> {
    const current = this.detect();
    if (!current.supported) {
      this.fail("unsupported-page");
      return;
    }
    this.detection = current;
    this.state = CaptureState.PreviewRequired;
  }

  async confirmRegion(): Promise<void> {
    if (this.state !== CaptureState.PreviewRequired || !this.detection) {
      throw new Error("preview-confirmation-required");
    }
    const current = this.detect();
    if (!current.supported || current.signature !== this.detection.signature) {
      this.fail("page-changed");
      throw new Error("page-changed");
    }
    this.state = CaptureState.Capturing;
    try {
      const imageData = await this.captureVisibleTab();
      this.preview = { imageData, maskedRegions: [] };
      this.state = current.sensitiveRegions.length > 0
        ? CaptureState.Redacting
        : CaptureState.PreviewReady;
    } catch {
      this.fail("capture-failed");
      throw new Error("capture-failed");
    }
  }

  async setPreview(preview: PreviewImage): Promise<void> {
    if (!this.detection || this.state !== CaptureState.Redacting) {
      throw new Error("redaction-required");
    }
    const current = this.detect();
    if (!sameRegions(current, this.detection)) {
      this.fail("sensitive-region-changed");
      throw new Error("sensitive-region-changed");
    }
    this.preview = preview;
    this.state = CaptureState.PreviewReady;
  }

  crop(_rect: Rect): void {
    if (this.state !== CaptureState.Redacting && this.state !== CaptureState.PreviewReady) {
      throw new Error("preview-required");
    }
  }

  async retake(): Promise<void> {
    this.preview = null;
    await this.beginPreview();
  }

  async cancel(): Promise<void> {
    this.preview = null;
    this.detection = null;
    this.state = CaptureState.Cancelled;
  }

  async unredact(): Promise<void> {
    if (!this.allowUnredact) throw new Error("confirmation-required");
  }

  canUpload(): boolean {
    return this.state === CaptureState.PreviewReady && this.preview !== null;
  }

  serializeForRestart(): { state: CaptureState } {
    return { state: CaptureState.Detected };
  }

  static restoreAfterRestart(
    _serialized: { state: CaptureState },
    detect: DetectionFn,
    capture: CaptureFn,
  ): SafeCaptureController {
    return new SafeCaptureController(detect, capture);
  }

  private fail(_reason: string): CaptureState {
    this.preview = null;
    this.detection = null;
    this.state = CaptureState.Failed;
    return this.state;
  }
}
