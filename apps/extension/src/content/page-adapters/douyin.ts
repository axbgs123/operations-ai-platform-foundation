import type { DetectionInput, PageAdapter, PageDetection } from "./base";
import { parseRect, stableFingerprint, unsupported } from "./utils";

const version = "douyin-creator-v1";
const anchor = "作品管理";

export const createDouyinAdapter = (): PageAdapter => ({
  platform: "douyin",
  detect({ url, document }: DetectionInput): PageDetection {
    const parsed = new URL(url);
    if (
      parsed.hostname !== "creator.douyin.com" ||
      !parsed.pathname.startsWith("/creator-micro/content/manage")
    ) {
      return unsupported("douyin", "unsupported-url");
    }
    if (!document.querySelector(`[data-anchor="${anchor}"]`)) {
      return unsupported("douyin", "missing-anchor");
    }
    const pageVersion = document.documentElement.dataset.pageVersion ?? "unknown";
    if (pageVersion !== version) return unsupported("douyin", "unknown-page-version");
    if (document.documentElement.dataset.accountPlatform !== "douyin") {
      return unsupported("douyin", "platform-account-mismatch");
    }
    const captureRegion = parseRect(
      document.querySelector("[data-capture-region]")?.getAttribute("data-capture-region") ?? undefined,
    );
    if (!captureRegion) return unsupported("douyin", "missing-capture-region");
    const sensitiveRegions = (document.querySelector("[data-sensitive-region]")?.getAttribute("data-sensitive-region") ?? "")
      .split(",")
      .filter(Boolean)
      .map((kind, index) => ({
        kind,
        label: kind,
        rect: { x: 10 + index * 12, y: 10, width: 10, height: 10 },
      }));
    return {
      supported: true,
      platform: "douyin",
      pageVersion,
      signature: `douyin:${stableFingerprint([pageVersion, anchor, captureRegion ? JSON.stringify(captureRegion) : ""])}`,
      captureRegion,
      sensitiveRegions,
    };
  },
});
