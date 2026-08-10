import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";
import { createDouyinAdapter } from "../src/content/page-adapters/douyin";
import { createXiaohongshuAdapter } from "../src/content/page-adapters/xiaohongshu";
import { detectPage } from "../src/content/page-adapters/base";
import { detectSupportedPage } from "../src/content/page-support";

const fixture = (platform: "douyin" | "xiaohongshu") =>
  readFileSync(
    resolve(
      process.cwd(),
      `tests/fixtures/pages/${platform}/detail-v1.html`,
    ),
    "utf8",
  );

describe("platform page adapters", () => {
  it("detects the supported Douyin operations page from its URL alone", () => {
    const document = new JSDOM("<!doctype html>").window.document;
    const result = createDouyinAdapter().detect({
      url: "https://creator.douyin.com/creator-micro/content/manage/detail",
      document,
    });

    expect(result).toMatchObject({
      supported: true,
      platform: "douyin",
      pageVersion: "douyin-visible-tab-v1",
      captureRegion: null,
    });
    expect(result.signature).toMatch(/^douyin:[a-f0-9]{16}$/);
    expect(result.sensitiveRegions).toEqual([]);
  });

  it("detects Xiaohongshu independently from its URL alone", () => {
    const document = new JSDOM("<!doctype html>").window.document;
    const result = createXiaohongshuAdapter().detect({
      url: "https://creator.xiaohongshu.com/publish/publish-manage/detail",
      document,
    });

    expect(result.supported).toBe(true);
    expect(result.platform).toBe("xiaohongshu");
    expect(result.pageVersion).toBe("xiaohongshu-visible-tab-v1");
    expect(result.captureRegion).toBeNull();
    expect(result.signature).toMatch(/^xiaohongshu:[a-f0-9]{16}$/);
  });

  it("rejects unsupported URLs without relying on fixture metadata", () => {
    const document = new JSDOM(fixture("douyin")).window.document;
    const adapter = createDouyinAdapter();

    expect(
      adapter.detect({
        url: "https://example.test/not-an-operations-page",
        document,
      }).supported,
    ).toBe(false);

    document.documentElement.dataset.pageVersion = "future-unknown";
    document.documentElement.dataset.accountPlatform = "xiaohongshu";
    expect(
      adapter.detect({
        url: "https://creator.douyin.com/creator-micro/content/manage",
        document,
      }),
    ).toMatchObject({ supported: true, pageVersion: "douyin-visible-tab-v1" });
  });

  it("uses registry detection without allowing one platform adapter to call another", () => {
    const document = new JSDOM(fixture("douyin")).window.document;
    expect(
      detectPage({
        url: "https://creator.douyin.com/creator-micro/content/manage",
        document,
      }),
    ).toMatchObject({ supported: true, platform: "douyin", captureRegion: null });

    const xhsDocument = new JSDOM(fixture("xiaohongshu")).window.document;
    expect(
      detectPage({
        url: "https://creator.xiaohongshu.com/publish/publish-manage",
        document: xhsDocument,
      }),
    ).toMatchObject({ supported: true, platform: "xiaohongshu", captureRegion: null });
  });

  it("reports support from declared hostname and path only", () => {
    expect(
      detectSupportedPage(
        "https://creator.douyin.com/creator-micro/content/manage?tab=all",
      ),
    ).toMatchObject({
      supported: true,
      platform: "douyin",
      pageVersion: "douyin-visible-tab-v1",
    });
    expect(detectSupportedPage("https://creator.douyin.com/creator-micro/content")).toMatchObject({
      supported: false,
      platform: null,
    });
  });
});
