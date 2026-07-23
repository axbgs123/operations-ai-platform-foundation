export type Platform = "douyin" | "xiaohongshu";

export type Rect = { x: number; y: number; width: number; height: number };

export type SensitiveRegion = {
  kind: string;
  label: string;
  rect: Rect;
};

export type PageDetection = {
  supported: boolean;
  platform: Platform | null;
  pageVersion: string;
  signature: string;
  captureRegion: Rect | null;
  sensitiveRegions: SensitiveRegion[];
  reason?: string;
};

export type DetectionInput = { url: string; document: Document };

export interface PageAdapter {
  readonly platform: Platform;
  detect(input: DetectionInput): PageDetection;
}

export { parseRect, stableFingerprint, unsupported } from "./utils";

export const detectPage = (input: DetectionInput): PageDetection => {
  for (const adapter of adapters) {
    const result = adapter.detect(input);
    if (result.supported || result.reason !== "unsupported-url") return result;
  }
  return {
    supported: false,
    platform: null,
    pageVersion: "unknown",
    signature: "unsupported",
    captureRegion: null,
    sensitiveRegions: [],
    reason: "unsupported-url",
  };
};

import { createDouyinAdapter } from "./douyin";
import { createXiaohongshuAdapter } from "./xiaohongshu";

const adapters: PageAdapter[] = [createDouyinAdapter(), createXiaohongshuAdapter()];
