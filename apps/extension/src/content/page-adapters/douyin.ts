import type { DetectionInput, PageAdapter, PageDetection } from "./base";
import { createPageSignatureTracker, unsupported } from "./utils";

const version = "douyin-visible-tab-v1";

export const createDouyinAdapter = (): PageAdapter => {
  const signature = createPageSignatureTracker("douyin", version);
  return {
    platform: "douyin",
    detect({ url, document }: DetectionInput): PageDetection {
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
      signature: signature(parsed, document),
      captureRegion: null,
      sensitiveRegions: [],
    };
    },
  };
};
