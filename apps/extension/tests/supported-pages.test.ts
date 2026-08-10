import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

import { createDouyinAdapter } from "../src/content/page-adapters/douyin";
import {
  effectiveVerificationStatus,
  parseSupportedPages,
} from "../src/content/page-adapters/supported-pages";
import { createXiaohongshuAdapter } from "../src/content/page-adapters/xiaohongshu";

const raw = () =>
  JSON.parse(
    readFileSync(resolve(process.cwd(), "supported-pages.json"), "utf8"),
  ) as unknown;
const fixtureDocument = (platform: "douyin" | "xiaohongshu") =>
  new JSDOM(
    readFileSync(
      resolve(process.cwd(), `tests/fixtures/pages/${platform}/detail-v1.html`),
      "utf8",
    ),
  ).window.document;

describe("supported page registry", () => {
  it("keeps fixture metadata isolated from URL-only runtime detection", () => {
    const pages = parseSupportedPages(raw());
    expect(pages.map((page) => page.platform)).toEqual([
      "douyin",
      "xiaohongshu",
    ]);
    expect(pages[0]).toMatchObject({
      urlPattern:
        "https://creator.douyin.com/creator-micro/content/manage*",
      pageVersion: "douyin-creator-v1",
      pageSignature: "douyin:00000000b2e2e525",
      signaturePrefix: "douyin:",
      requiredAnchors: ["作品管理"],
      verificationStatus: "fixture_verified",
      realPageVerifiedAt: null,
    });
    expect(pages[1]).toMatchObject({
      urlPattern:
        "https://creator.xiaohongshu.com/publish/publish-manage*",
      pageVersion: "xiaohongshu-creator-v1",
      pageSignature: "xiaohongshu:00000000cf6f9aab",
      signaturePrefix: "xiaohongshu:",
      requiredAnchors: ["笔记管理"],
      verificationStatus: "fixture_verified",
      realPageVerifiedAt: null,
    });
    expect(pages[0].requiredAnchors).not.toEqual(pages[1].requiredAnchors);

    const douyin = createDouyinAdapter().detect({
      url: pages[0].urlPattern.replace("*", "/detail"),
      document: fixtureDocument("douyin"),
    });
    const xiaohongshu = createXiaohongshuAdapter().detect({
      url: pages[1].urlPattern.replace("*", "/detail"),
      document: fixtureDocument("xiaohongshu"),
    });
    expect(douyin).toMatchObject({
      supported: true,
      pageVersion: "douyin-visible-tab-v1",
      captureRegion: null,
      sensitiveRegions: [],
    });
    expect(xiaohongshu).toMatchObject({
      supported: true,
      pageVersion: "xiaohongshu-visible-tab-v1",
      captureRegion: null,
      sensitiveRegions: [],
    });
    expect(douyin.signature).not.toBe(pages[0].pageSignature);
    expect(xiaohongshu.signature).not.toBe(pages[1].pageSignature);
  });

  it("rejects broad URLs, real-page claims without evidence, and private data", () => {
    const pages = parseSupportedPages(raw());
    const serialized = JSON.stringify(pages);
    expect(serialized).not.toContain("<all_urls>");
    expect(serialized).not.toMatch(/cookie|bearer|invite[_ -]?code|account[_ -]?name/i);
    for (const page of pages) {
      expect(page.fixtureVerifiedAt).toMatch(/^2026-\d{2}-\d{2}$/);
      expect(page.verifiedBrowsers).toEqual([]);
      expect(page.verifiedOperatingSystems).toEqual([]);
      expect(page.verificationStatus).not.toBe("real_page_verified");
    }
  });

  it("marks fixture evidence stale without upgrading unverified environments", () => {
    const page = parseSupportedPages(raw())[0];
    expect(
      effectiveVerificationStatus(page, new Date("2026-08-01T00:00:00Z")),
    ).toBe("fixture_verified");
    expect(
      effectiveVerificationStatus(page, new Date("2027-01-01T00:00:00Z")),
    ).toBe("stale");
  });

  it("rejects unsupported status values and malformed environment claims", () => {
    const invalid = raw() as Array<Record<string, unknown>>;
    invalid[0] = {
      ...invalid[0],
      verificationStatus: "supported_everywhere",
      verifiedBrowsers: ["Chrome"],
    };
    expect(() => parseSupportedPages(invalid)).toThrow(
      "invalid supported page registry",
    );
  });
});
