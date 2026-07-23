import type { DetectionInput, PageAdapter, PageDetection } from "./base";
import { parseRect, stableFingerprint, unsupported } from "./utils";

const version = "xiaohongshu-creator-v1";
const anchor = "笔记管理";

export const createXiaohongshuAdapter = (): PageAdapter => ({
  platform: "xiaohongshu",
  detect({ url, document }: DetectionInput): PageDetection {
    const parsed = new URL(url);
    if (
      parsed.hostname !== "creator.xiaohongshu.com" ||
      !parsed.pathname.startsWith("/publish/publish-manage")
    ) {
      return unsupported("xiaohongshu", "unsupported-url");
    }
    if (!document.querySelector(`[data-anchor="${anchor}"]`)) {
      return unsupported("xiaohongshu", "missing-anchor");
    }
    const pageVersion = document.documentElement.dataset.pageVersion ?? "unknown";
    if (pageVersion !== version) return unsupported("xiaohongshu", "unknown-page-version");
    if (document.documentElement.dataset.accountPlatform !== "xiaohongshu") {
      return unsupported("xiaohongshu", "platform-account-mismatch");
    }
    const captureRegion = parseRect(
      document.querySelector("[data-capture-region]")?.getAttribute("data-capture-region") ?? undefined,
    );
    if (!captureRegion) return unsupported("xiaohongshu", "missing-capture-region");
    const sensitiveRegions = (document.querySelector("[data-sensitive-region]")?.getAttribute("data-sensitive-region") ?? "")
      .split(",")
      .filter(Boolean)
      .map((kind, index) => ({
        kind,
        label: kind,
        rect: { x: 8 + index * 14, y: 8, width: 10, height: 10 },
      }));
    return {
      supported: true,
      platform: "xiaohongshu",
      pageVersion,
      signature: `xiaohongshu:${stableFingerprint([pageVersion, anchor, captureRegion ? JSON.stringify(captureRegion) : ""])}`,
      captureRegion,
      sensitiveRegions,
    };
  },
});
