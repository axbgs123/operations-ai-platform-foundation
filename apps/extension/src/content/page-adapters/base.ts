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

export type DetectionInput = {
  url: string;
  document: Document;
  hotspotTargetPlatform?: Platform | null;
};

export interface PageAdapter {
  readonly platform: Platform;
  detect(input: DetectionInput): PageDetection;
}

import { stableFingerprint } from "./utils";
export { parseRect, stableFingerprint, unsupported } from "./utils";

export const detectPage = (input: DetectionInput): PageDetection => {
  for (const adapter of adapters) {
    const result = adapter.detect(input);
    if (result.supported || result.reason !== "unsupported-url") return result;
  }
  if (input.hotspotTargetPlatform) {
    try {
      const parsed = new URL(input.url);
      if (parsed.protocol === "https:") {
        return {
          supported: true,
          platform: input.hotspotTargetPlatform,
          pageVersion: "hotspot-public-page-v1",
          signature: `${input.hotspotTargetPlatform}:hotspot:${stableFingerprint([
            parsed.origin,
            parsed.pathname,
            parsed.search,
            input.document.title.slice(0, 300),
          ])}`,
          captureRegion: null,
          sensitiveRegions: [],
        };
      }
    } catch {
      // Invalid or restricted URLs remain unsupported.
    }
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
