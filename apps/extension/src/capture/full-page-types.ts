export type CapturePlatform = "douyin" | "xiaohongshu";

export type CaptureViewport = {
  width: number;
  height: number;
  devicePixelRatio: number;
};

export type CaptureSlice = {
  dataUrl: string;
  sequence: number;
  scrollY: number;
  url: string;
  platform: CapturePlatform;
  pageVersion: string;
  pageSignature: string;
  viewport: CaptureViewport;
};

export type PartialCaptureReason =
  | "cancelled"
  | "page-hidden"
  | "pagehide"
  | "window-blur"
  | "page-drift"
  | "bottom-unstable"
  | "capture-failed";

export type FullPageCaptureResult = {
  slices: CaptureSlice[];
  complete: boolean;
  stopReason: "bottom" | "slice-limit" | "time-limit";
  originalScrollY: number;
  /** Present whenever complete is false for a reason other than a stated bound. */
  partialReason?: PartialCaptureReason;
};

export type StitchedCapture = {
  dataUrl: string | null;
  width: number;
  height: number;
  complete: boolean;
  croppedOverlapPixels: number;
  sliceCount: number;
  partialReason?: "empty" | "invalid-slice-order" | "pixel-limit" | "edge-limit" | "encoded-size" | "canvas-failed" | "dimension-mismatch" | "overlap-unverified";
};

export type StitchLimits = {
  maxPixels: number;
  maxEdge: number;
  maxBytes: number;
};
