import type { DetectionInput, PageAdapter, PageDetection } from "./base";
import { stableFingerprint, unsupported } from "./utils";

const version = "xiaohongshu-visible-tab-v1";

export const createXiaohongshuAdapter = (): PageAdapter => ({
  platform: "xiaohongshu",
  detect({ url }: DetectionInput): PageDetection {
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
      signature: `xiaohongshu:${stableFingerprint([version, parsed.hostname, parsed.pathname])}`,
      captureRegion: null,
      sensitiveRegions: [],
    };
  },
});
