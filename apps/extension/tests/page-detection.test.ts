import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";
import { createDouyinAdapter } from "../src/content/page-adapters/douyin";
import { createXiaohongshuAdapter } from "../src/content/page-adapters/xiaohongshu";
import { detectPage } from "../src/content/page-adapters/base";

const fixture = (platform: "douyin" | "xiaohongshu") =>
  readFileSync(
    resolve(
      process.cwd(),
      `tests/fixtures/pages/${platform}/detail-v1.html`,
    ),
    "utf8",
  );

describe("platform page adapters", () => {
  it("detects the supported Douyin operations detail page", () => {
    const document = new JSDOM(fixture("douyin")).window.document;
    const result = createDouyinAdapter().detect({
      url: "https://creator.douyin.com/creator-micro/content/manage/detail",
      document,
    });

    expect(result).toMatchObject({
      supported: true,
      platform: "douyin",
      pageVersion: "douyin-creator-v1",
      captureRegion: { x: 40, y: 80, width: 640, height: 360 },
    });
    expect(result.signature).toMatch(/^douyin:[a-f0-9]{16}$/);
    expect(result.sensitiveRegions.map((region) => region.kind)).toEqual([
      "avatar",
      "nickname",
      "phone",
      "email",
      "dm",
      "internal-id",
    ]);
  });

  it("detects Xiaohongshu independently with its own anchor and signature", () => {
    const document = new JSDOM(fixture("xiaohongshu")).window.document;
    const result = createXiaohongshuAdapter().detect({
      url: "https://creator.xiaohongshu.com/publish/publish-manage/detail",
      document,
    });

    expect(result.supported).toBe(true);
    expect(result.platform).toBe("xiaohongshu");
    expect(result.captureRegion).toEqual({ x: 24, y: 64, width: 720, height: 420 });
    expect(result.signature).toMatch(/^xiaohongshu:[a-f0-9]{16}$/);
  });

  it("rejects unsupported URLs, missing anchors, unknown versions, and platform mismatch", () => {
    const document = new JSDOM(fixture("douyin")).window.document;
    const adapter = createDouyinAdapter();

    expect(
      adapter.detect({
        url: "https://example.test/not-an-operations-page",
        document,
      }).supported,
    ).toBe(false);

    document.querySelector("[data-anchor]")?.remove();
    expect(
      adapter.detect({
        url: "https://creator.douyin.com/creator-micro/content/manage",
        document,
      }).reason,
    ).toBe("missing-anchor");

    const unknown = new JSDOM(fixture("douyin")).window.document;
    unknown.documentElement.dataset.pageVersion = "future-unknown";
    expect(
      adapter.detect({
        url: "https://creator.douyin.com/creator-micro/content/manage",
        document: unknown,
      }).reason,
    ).toBe("unknown-page-version");

    const mismatch = new JSDOM(fixture("douyin")).window.document;
    mismatch.documentElement.dataset.accountPlatform = "xiaohongshu";
    expect(
      adapter.detect({
        url: "https://creator.douyin.com/creator-micro/content/manage",
        document: mismatch,
      }).reason,
    ).toBe("platform-account-mismatch");
  });

  it("uses registry detection without allowing one platform adapter to call another", () => {
    const document = new JSDOM(fixture("douyin")).window.document;
    expect(
      detectPage({
        url: "https://creator.douyin.com/creator-micro/content/manage",
        document,
      }),
    ).toMatchObject({ supported: true, platform: "douyin" });

    const xhsDocument = new JSDOM(fixture("xiaohongshu")).window.document;
    expect(
      detectPage({
        url: "https://creator.xiaohongshu.com/publish/publish-manage",
        document: xhsDocument,
      }),
    ).toMatchObject({ supported: true, platform: "xiaohongshu" });
  });
});
