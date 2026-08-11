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

  it.each([
    ["douyin", createDouyinAdapter, "https://creator.douyin.com/creator-micro/content/manage?tab=all"],
    ["xiaohongshu", createXiaohongshuAdapter, "https://creator.xiaohongshu.com/publish/publish-manage?tab=all"],
  ] as const)("detects same-route %s row replacement but ignores append-only lazy growth", (_platform, createAdapter, url) => {
    const dom = new JSDOM(`<!doctype html><body>
      <div data-account-id="fixture-account"></div>
      <button aria-selected="true">全部作品</button>
      <article data-content-id="row-1">第一条内容</article>
      <article data-content-id="row-2">第二条内容</article>
    </body>`);
    const adapter = createAdapter();
    const first = adapter.detect({ url, document: dom.window.document }).signature;

    const appended = dom.window.document.createElement("article");
    appended.dataset.contentId = "row-3";
    appended.textContent = "延迟加载的新内容";
    dom.window.document.body.append(appended);
    expect(adapter.detect({ url, document: dom.window.document }).signature).toBe(first);

    dom.window.document.querySelector<HTMLElement>('[data-content-id="row-1"]')!.textContent = "同路由替换后的内容";
    expect(adapter.detect({ url, document: dom.window.document }).signature).not.toBe(first);
  });

  it("includes stable query and selected account/filter anchors in the signature", () => {
    const dom = new JSDOM('<!doctype html><body><div data-account-id="account-a"></div><button aria-selected="true">全部</button></body>');
    const adapter = createDouyinAdapter();
    const first = adapter.detect({
      url: "https://creator.douyin.com/creator-micro/content/manage?status=published",
      document: dom.window.document,
    }).signature;
    dom.window.document.querySelector<HTMLElement>("[data-account-id]")!.dataset.accountId = "account-b";
    const accountChanged = adapter.detect({
      url: "https://creator.douyin.com/creator-micro/content/manage?status=published",
      document: dom.window.document,
    }).signature;
    const queryChanged = adapter.detect({
      url: "https://creator.douyin.com/creator-micro/content/manage?status=draft",
      document: dom.window.document,
    }).signature;
    expect(accountChanged).not.toBe(first);
    expect(queryChanged).not.toBe(accountChanged);
  });
});
