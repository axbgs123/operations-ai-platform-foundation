import type { DetectionInput, PageAdapter, PageDetection } from "./base";
import { stableFingerprint, unsupported } from "./utils";

const version = "douyin-visible-tab-v1";

export const createDouyinAdapter = (): PageAdapter => ({
  platform: "douyin",
  detect({ url }: DetectionInput): PageDetection {
    const parsed = new URL(url);
    if (
      parsed.hostname !== "creator.douyin.com" ||
      !parsed.pathname.startsWith("/creator-micro/content/manage")
    ) {
      return unsupported("douyin", "unsupported-url");
    }
    return {
      supported: true,
      platform: "douyin",
      pageVersion: version,
      signature: `douyin:${stableFingerprint([version, parsed.hostname, parsed.pathname])}`,
      captureRegion: null,
      sensitiveRegions: [],
    };
  },
});
