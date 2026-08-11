import type { DetectionInput, PageAdapter, PageDetection } from "./base";
import { createPageSignatureTracker, unsupported } from "./utils";

const version = "xiaohongshu-visible-tab-v1";

export const createXiaohongshuAdapter = (): PageAdapter => {
  const signature = createPageSignatureTracker("xiaohongshu", version);
  return {
    platform: "xiaohongshu",
    detect({ url, document }: DetectionInput): PageDetection {
    const parsed = new URL(url);
    if (
      parsed.hostname !== "creator.xiaohongshu.com" ||
      !parsed.pathname.startsWith("/publish/publish-manage")
    ) {
      return unsupported("xiaohongshu", "unsupported-url");
    }
    return {
      supported: true,
      platform: "xiaohongshu",
      pageVersion: version,
      signature: signature(parsed, document),
      captureRegion: null,
      sensitiveRegions: [],
    };
    },
  };
};
